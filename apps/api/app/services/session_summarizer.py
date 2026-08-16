from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Story, StoryBranch, StorySummary
from app.llm.router import LLMGateway
from app.schemas.llm import ChatMessage
from app.services.token_estimator import estimate_tokens


MAX_SOURCE_MESSAGES = 36


async def generate_session_summary(
    session: AsyncSession,
    llm_gateway: LLMGateway,
    story: Story,
    branch: StoryBranch,
) -> StorySummary:
    messages = await _load_messages_for_summary(session, story.id, branch.id)
    if not messages:
        raise ValueError("No messages available to summarize")

    source_text = _format_messages(messages)
    llm_request = llm_gateway.request_for_purpose(
        "summary_generation",
        [
            ChatMessage(
                role="system",
                content="你是长篇小说工程中的会话摘要器。只输出可直接存入资料库的中文摘要。",
            ),
            ChatMessage(
                role="developer",
                content=(
                    "请用 5-8 条高密度要点总结这段故事会话。必须覆盖：已发生事件、角色关系变化、"
                    "已确认事实、未解决线索、用户明确选择。不要编造原文没有的信息。"
                ),
            ),
            ChatMessage(role="user", content=source_text),
        ],
    )
    llm_request = llm_gateway.normalize_request(
        llm_request.model_copy(
            update={
                "max_output_tokens": min(llm_request.max_output_tokens, 1400),
                "temperature": min(llm_request.temperature, 0.45),
                "top_p": min(llm_request.top_p, 0.9),
            }
        )
    )
    llm_response = await llm_gateway.generate(llm_request)
    content = llm_response.text.strip() or _fallback_summary(messages)

    summary = StorySummary(
        user_id=story.user_id,
        story_id=story.id,
        branch_id=branch.id,
        from_message_id=messages[0].id,
        to_message_id=messages[-1].id,
        summary_type="session",
        title=_summary_title(story.title, branch.name, messages),
        content=content,
        message_count=len(messages),
        token_count=estimate_tokens(source_text),
    )
    session.add(summary)
    await session.flush()

    await session.commit()
    return summary


async def _load_messages_for_summary(session: AsyncSession, story_id: UUID, branch_id: UUID) -> list[Message]:
    latest_summary_result = await session.execute(
        select(StorySummary)
        .where(StorySummary.story_id == story_id, StorySummary.branch_id == branch_id)
        .order_by(desc(StorySummary.created_at))
        .limit(1)
    )
    latest_summary = latest_summary_result.scalar_one_or_none()

    query = (
        select(Message)
        .where(Message.story_id == story_id, Message.branch_id == branch_id)
        .order_by(Message.created_at.asc())
    )
    if latest_summary and latest_summary.to_message_id:
        to_message = await session.get(Message, latest_summary.to_message_id)
        if to_message and to_message.created_at:
            query = query.where(Message.created_at > to_message.created_at)

    result = await session.execute(query.limit(MAX_SOURCE_MESSAGES))
    messages = list(result.scalars().all())
    if len(messages) >= 2:
        return messages

    fallback_result = await session.execute(
        select(Message)
        .where(Message.story_id == story_id, Message.branch_id == branch_id)
        .order_by(desc(Message.created_at))
        .limit(18)
    )
    return list(reversed(fallback_result.scalars().all()))


def _format_messages(messages: list[Message]) -> str:
    lines = []
    for index, message in enumerate(messages, start=1):
        author = message.meta.get("author") if message.meta else None
        role = author or message.role
        lines.append(f"{index}. [{role}] {message.content.strip()}")
    return "\n".join(lines)


def _summary_title(story_title: str, branch_name: str, messages: list[Message]) -> str:
    return f"{story_title} / {branch_name} / {len(messages)} turns"


def _fallback_summary(messages: list[Message]) -> str:
    first = messages[0].content.strip()[:120]
    last = messages[-1].content.strip()[:160]
    return f"- 本段从“{first}”开始。\n- 最新进展为“{last}”。\n- 需要后续继续根据角色目标、既定事实和用户选择推进。"
