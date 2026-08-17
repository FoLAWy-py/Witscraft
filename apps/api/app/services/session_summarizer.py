from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Story, StoryBranch, StorySummary
from app.llm.router import LLMGateway
from app.schemas.llm import ChatMessage
from app.services.token_estimator import estimate_tokens


MAX_SOURCE_MESSAGES = 36
SUMMARY_PROMPT_VERSION = "session-summary-v2"
SUMMARY_TRIGGER_USER_REQUESTED = "user_requested"


async def generate_session_summary(
    session: AsyncSession,
    llm_gateway: LLMGateway,
    story: Story,
    branch: StoryBranch,
    *,
    trigger: str = SUMMARY_TRIGGER_USER_REQUESTED,
) -> StorySummary:
    if trigger != SUMMARY_TRIGGER_USER_REQUESTED:
        raise ValueError("Unsupported summary trigger")

    parent_summary, messages = await _load_summary_source(session, story.id, branch.id)
    if not messages:
        raise ValueError("No new messages available to summarize")

    source_text = _format_messages(messages)
    prior_summary = parent_summary.content.strip() if parent_summary else ""
    user_content = (
        f"[Previous cumulative summary]\n{prior_summary or 'None'}\n\n"
        f"[New messages]\n{source_text}"
    )
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
                    "请生成一份可完全替代旧摘要的累积摘要，而不是只总结新增消息。保留仍然有效的旧摘要事实，"
                    "结合新增消息更新 5-8 条高密度要点。必须覆盖：已发生事件、角色关系变化、已确认事实、"
                    "未解决线索、用户明确选择。若新增消息推翻旧信息，以新增消息为准。不要编造输入中没有的信息。"
                ),
            ),
            ChatMessage(role="user", content=user_content),
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
    content = llm_response.text.strip() or _fallback_summary(messages, prior_summary)
    cumulative_message_count = (
        int(parent_summary.message_count or 0) + len(messages)
        if parent_summary
        else len(messages)
    )

    summary = StorySummary(
        user_id=story.user_id,
        story_id=story.id,
        branch_id=branch.id,
        parent_summary_id=parent_summary.id if parent_summary else None,
        from_message_id=(
            parent_summary.from_message_id
            if parent_summary and parent_summary.from_message_id
            else messages[0].id
        ),
        to_message_id=messages[-1].id,
        summary_type="session",
        prompt_version=SUMMARY_PROMPT_VERSION,
        provider=llm_response.provider,
        model=llm_response.model,
        trigger=trigger,
        title=_summary_title(story.title, branch.name, cumulative_message_count),
        content=content,
        message_count=cumulative_message_count,
        token_count=estimate_tokens(user_content),
    )
    session.add(summary)
    await session.flush()

    await session.commit()
    return summary


async def _load_summary_source(
    session: AsyncSession,
    story_id: UUID,
    branch_id: UUID,
) -> tuple[StorySummary | None, list[Message]]:
    latest_summary_result = await session.execute(
        select(StorySummary)
        .where(StorySummary.story_id == story_id, StorySummary.branch_id == branch_id)
        .order_by(desc(StorySummary.created_at), desc(StorySummary.id))
        .limit(1)
    )
    latest_summary = latest_summary_result.scalar_one_or_none()

    query = (
        select(Message)
        .where(Message.story_id == story_id, Message.branch_id == branch_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    if latest_summary and latest_summary.to_message_id:
        to_message = await session.get(Message, latest_summary.to_message_id)
        if to_message and to_message.created_at:
            query = query.where(
                or_(
                    Message.created_at > to_message.created_at,
                    and_(
                        Message.created_at == to_message.created_at,
                        Message.id > to_message.id,
                    ),
                )
            )
    elif latest_summary and latest_summary.created_at:
        query = query.where(Message.created_at > latest_summary.created_at)

    result = await session.execute(query.limit(MAX_SOURCE_MESSAGES))
    return latest_summary, list(result.scalars().all())


def _format_messages(messages: list[Message]) -> str:
    lines = []
    for index, message in enumerate(messages, start=1):
        author = message.meta.get("author") if message.meta else None
        role = author or message.role
        lines.append(f"{index}. [{role}] {message.content.strip()}")
    return "\n".join(lines)


def _summary_title(story_title: str, branch_name: str, message_count: int) -> str:
    return f"{story_title} / {branch_name} / {message_count} messages"


def _fallback_summary(messages: list[Message], prior_summary: str = "") -> str:
    first = messages[0].content.strip()[:120]
    last = messages[-1].content.strip()[:160]
    prefix = f"{prior_summary}\n" if prior_summary else ""
    return (
        f"{prefix}- 新增情节从“{first}”开始。\n"
        f"- 最新进展为“{last}”。\n"
        "- 需要后续继续根据角色目标、既定事实和用户选择推进。"
    )
