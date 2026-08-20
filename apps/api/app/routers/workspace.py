import asyncio
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import case, delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.bootstrap import DEFAULT_CHARACTER_ID, DEFAULT_STORY_ID, DEFAULT_WORLD_ID
from app.db.models import (
    CanonFact,
    Character,
    MemoryItem,
    Message,
    ModelCall,
    Story,
    StoryBranch,
    StoryChapter,
    StorySummary,
    StoryStateSnapshot,
    UserPreference,
    World,
)
from app.db.session import get_session
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway
from app.schemas.chat import (
    CreateBranchRequest,
    CreateStoryRequest,
    GenerateSummaryRequest,
    GenerateStoryDraftRequest,
    SetStoryWorldRequest,
    StoryDraftResponse,
    StoryInterviewDraft,
    StoryInterviewRequest,
    StoryInterviewResponse,
    StoryState,
    UpdateBranchRequest,
    UpdateCanonFactRequest,
    UpdateCharacterRequest,
    UpdateMemoryRequest,
    UpdateStoryRequest,
    UpdateWorldRequest,
    UserPreferenceResponse,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
    WorkspaceMessage,
    WorkspaceResponse,
)
from app.schemas.llm import ChatMessage, LLMRequest
from app.services.embeddings import embedding_content_hash, stored_embedding
from app.services.branch_manager import clone_story_branch
from app.services.memory_embedding_tasks import enqueue_memory_embedding
from app.services.session_summarizer import generate_session_summary
from app.services.quota_service import QuotaExceededError
from app.services.model_route_service import load_user_purpose_routes
from app.services.story_exporter import (
    build_story_export_payload,
    export_filename,
    render_story_json,
    render_story_markdown,
)
from app.services.story_roadmap import plan_initial_roadmap

router = APIRouter(prefix="/workspace", tags=["workspace"])

INTERVIEW_REQUIRED_FIELDS = (
    "title",
    "genre",
    "world_name",
    "premise",
    "protagonist_name",
    "protagonist_role",
    "tone",
    "custom_prompt",
)


def _story_interview_missing_fields(draft: StoryInterviewDraft) -> list[str]:
    missing = [
        field_name
        for field_name in INTERVIEW_REQUIRED_FIELDS
        if not str(getattr(draft, field_name)).strip()
    ]
    if draft.opening_mode == "custom" and not draft.opening_text.strip():
        missing.append("opening_text")
    return missing


INTERVIEW_FALLBACKS = {
    "title": ("先确定书名方向：你更喜欢哪一种？", ["意象感强的书名", "直接点明核心冲突"]),
    "genre": ("这部小说最接近哪种类型？", ["悬疑或推理", "幻想或科幻", "现实或情感"]),
    "world_name": ("故事主要发生在哪一种世界？", ["当代真实城市", "架空世界", "近未来社会"]),
    "premise": ("目前最想明确故事前提中的哪一部分？", ["主角当前面对的问题", "故事开始时发生的事件", "尚未解决的核心矛盾"]),
    "protagonist_name": ("主角的名字更接近哪种感觉？", ["真实日常", "古典含蓄", "鲜明独特"]),
    "protagonist_role": ("主角最重要的身份与目标是什么？", ["普通人被卷入事件", "专业人士主动调查", "局内人试图逃离"]),
    "tone": ("你希望读者最直接感受到哪种叙事气质？", ["克制而有画面感", "轻快而有张力", "浓烈而富有诗意"]),
    "opening_text": ("你希望自定义开场从哪个瞬间开始？", ["冲突发生前一刻", "异常已经出现", "主角做出决定"]),
    "custom_prompt": ("专属创作 Prompt 更应优先强化哪一点？", ["人物声音与视角", "悬念节奏与伏笔", "世界规则与连续性"]),
}


INTERVIEW_FOCUS_HINTS = {
    "title": ("书名", "标题", "名字"),
    "genre": ("类型", "题材", "悬疑", "科幻", "奇幻", "言情", "仙侠"),
    "world_name": ("世界", "城市", "时代", "背景", "地点"),
    "premise": ("故事", "冲突", "秘密", "事件", "困境", "发生"),
    "protagonist_name": ("主角名", "姓名", "叫什么"),
    "protagonist_role": ("主角", "身份", "职业", "目标", "想要"),
    "tone": ("文风", "风格", "气质", "氛围", "节奏"),
    "opening_text": ("开场", "第一幕", "第一段"),
    "custom_prompt": ("prompt", "提示词", "写作约束"),
}


def _choose_interview_focus(
    draft: StoryInterviewDraft,
    latest_user_message: str = "",
) -> str | None:
    missing = _story_interview_missing_fields(draft)
    if not missing:
        return None

    scores = {
        "premise": 100,
        "genre": 80,
        "protagonist_role": 75,
        "world_name": 70,
        "protagonist_name": 58,
        "tone": 50,
        "title": 35,
        "opening_text": 25,
        "custom_prompt": 10,
    }
    if draft.premise.strip():
        scores["genre"] += 25
        scores["protagonist_role"] += 25
        scores["world_name"] += 20
        scores["tone"] += 15
        scores["title"] += 15
    if draft.protagonist_role.strip():
        scores["protagonist_name"] += 25
    if all(
        str(getattr(draft, field)).strip()
        for field in ("genre", "world_name", "premise", "protagonist_name", "protagonist_role", "tone")
    ):
        scores["title"] += 50
        scores["custom_prompt"] += 45

    normalized_message = latest_user_message.casefold()
    for field in missing:
        if any(hint.casefold() in normalized_message for hint in INTERVIEW_FOCUS_HINTS[field]):
            scores[field] += 60
    return max(missing, key=lambda field: scores.get(field, 0))


def _infer_interview_focus(question: str, missing: list[str]) -> str | None:
    normalized = question.casefold()
    for field in missing:
        if any(hint.casefold() in normalized for hint in INTERVIEW_FOCUS_HINTS[field]):
            return field
    return None


def _contextual_interview_fallback(
    field: str,
    draft: StoryInterviewDraft,
) -> tuple[str, list[str]]:
    question, options = INTERVIEW_FALLBACKS[field]
    context_parts = [
        value.strip()
        for value in (draft.genre, draft.world_name, draft.premise[:48])
        if value.strip()
    ][:2]
    if not context_parts:
        return question, options
    return f"结合已经确定的“{' · '.join(context_parts)}”，{question}", options


def _finalize_story_interview(
    result: StoryInterviewResponse,
    latest_user_message: str = "",
) -> StoryInterviewResponse:
    missing = _story_interview_missing_fields(result.draft)
    if not missing:
        return result.model_copy(
            update={
                "assistant_message": "小说已就绪，点击“确认并创建小说”。你也可以先修改故事确认卡中的任何内容。",
                "options": [],
                "question_focus": None,
                "missing_fields": [],
                "ready_for_confirmation": True,
            }
        )

    requested_focus = result.question_focus if result.question_focus in missing else None
    inferred_focus = _infer_interview_focus(result.assistant_message, missing)
    focus = requested_focus or inferred_focus or _choose_interview_focus(
        result.draft, latest_user_message
    )
    if focus is None:
        focus = missing[0]
    fallback_question, fallback_options = _contextual_interview_fallback(focus, result.draft)
    blocked_options = {"自定义", "custom", "custom answer", "other", "其他"}
    options = list(
        dict.fromkeys(
            item.strip()
            for item in result.options
            if item.strip() and item.strip().casefold() not in blocked_options
        )
    )[:3]
    if result.draft.interaction_mode == "open":
        options = []
    elif len(options) < 2:
        options = fallback_options
    assistant_message = result.assistant_message.strip() or fallback_question
    question_positions = [
        position
        for marker in ("？", "?")
        if (position := assistant_message.find(marker)) >= 0
    ]
    if question_positions:
        assistant_message = assistant_message[: min(question_positions) + 1]
    else:
        preface = assistant_message.rstrip("。！!")
        assistant_message = f"{preface}。{fallback_question}" if preface else fallback_question
    return result.model_copy(
        update={
            "assistant_message": assistant_message,
            "options": options,
            "question_focus": focus,
            "missing_fields": missing,
            "ready_for_confirmation": False,
        }
    )


def _extract_streamed_json_string(payload: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', payload)
    if match is None:
        return ""
    position = match.end()
    output: list[str] = []
    escapes = {"\"": "\"", "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while position < len(payload):
        character = payload[position]
        if character == '"':
            break
        if character != "\\":
            output.append(character)
            position += 1
            continue
        if position + 1 >= len(payload):
            break
        escaped = payload[position + 1]
        if escaped == "u":
            codepoint = payload[position + 2 : position + 6]
            if len(codepoint) < 4 or not all(item in "0123456789abcdefABCDEF" for item in codepoint):
                break
            output.append(chr(int(codepoint, 16)))
            position += 6
            continue
        if escaped not in escapes:
            break
        output.append(escapes[escaped])
        position += 2
    return "".join(output)


@router.get("", response_model=WorkspaceResponse)
async def workspace(
    story_id: str | None = None,
    branch_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    stories = await _load_stories(session, user_id)
    worlds = await _load_worlds(session, user_id)
    story = None
    if story_id:
        requested_story_id = _parse_uuid_or_none(story_id)
        if requested_story_id is not None:
            story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        result = await session.execute(
            select(Story).where(Story.user_id == user_id).order_by(Story.created_at.asc()).limit(1)
        )
        story = result.scalar_one_or_none()
    if story is None:
        return _empty_workspace_response(stories, worlds)

    active_branch_id = story.current_branch_id
    requested_branch_id = _parse_uuid_or_none(branch_id or "")
    if requested_branch_id is not None:
        requested_branch = await session.get(StoryBranch, requested_branch_id)
        if requested_branch is not None and requested_branch.story_id == story.id:
            active_branch_id = requested_branch.id
    if active_branch_id is None:
        fallback_branch = await session.scalar(
            select(StoryBranch)
            .where(StoryBranch.story_id == story.id)
            .order_by(StoryBranch.created_at.asc())
            .limit(1)
        )
        active_branch_id = (
            fallback_branch.id
            if fallback_branch is not None
            else UUID("00000000-0000-0000-0000-000000000401")
        )

    branches = await _load_branches(session, story.id, active_branch_id)
    world = await _load_world(session, story.world_id, user_id)
    characters = await _load_characters(session, story.world_id, user_id, story.main_character_id)
    messages = await _load_messages(session, story.id, active_branch_id)
    state, relationships = await _load_state(session, story.id, active_branch_id)
    memory_items = await _load_memory_items(session, story.id, active_branch_id)
    canon_fact_items = await _load_canon_fact_items(session, story.id, active_branch_id)
    summaries = await _load_summaries(session, story.id, active_branch_id)
    model_call = await _load_model_call(session, story.id)
    active_branch = await session.get(StoryBranch, active_branch_id)
    chapters = await _load_chapters(session, story.id, active_branch_id)

    return WorkspaceResponse(
        story_id=str(story.id),
        branch_id=str(active_branch_id),
        branches=branches,
        stories=stories,
        world=world,
        worlds=worlds,
        characters=characters,
        messages=messages,
        story_state=state,
        relationships=relationships,
        retrieved_memories=[memory["content"] for memory in memory_items],
        canon_facts=[fact["content"] for fact in canon_fact_items],
        memory_items=memory_items,
        canon_fact_items=canon_fact_items,
        summaries=summaries,
        model_call=model_call,
        onboarding_required=False,
        story_prompt=story.custom_prompt or "",
        interaction_mode=story.interaction_mode or "choices",
        consistency_mode=story.consistency_mode or "auto",
        planned_chapter_count=story.planned_chapter_count,
        target_chapter_length=story.target_chapter_length,
        chapter_length_unit=story.chapter_length_unit,
        prose_language=story.prose_language,
        roadmap_version=active_branch.roadmap_version if active_branch else 0,
        roadmap_source=active_branch.roadmap_source if active_branch else "legacy",
        ending_title=active_branch.ending_title or "" if active_branch else "",
        chapters=chapters,
    )


@router.post("/stories", response_model=WorkspaceResponse)
async def create_story(
    request: CreateStoryRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    title = request.title.strip()
    genre = request.genre.strip()
    world_name = request.world_name.strip()
    premise = request.premise.strip()
    protagonist_name = request.protagonist_name.strip()
    protagonist_role = request.protagonist_role.strip()
    tone = request.tone.strip()
    opening_text = request.opening_text.strip()
    custom_prompt = request.custom_prompt.strip()
    if request.opening_mode == "custom" and not opening_text:
        raise HTTPException(status_code=422, detail="Custom opening text is required")

    existing_world_id = None
    if request.world_id:
        requested_world_id = _parse_uuid_or_none(request.world_id)
        if requested_world_id is None:
            raise HTTPException(status_code=404, detail="World not found")
        existing_world = await session.get(World, requested_world_id)
        if existing_world is None or existing_world.user_id != user_id:
            raise HTTPException(status_code=404, detail="World not found")
        existing_world_id = existing_world.id

    purpose_routes = await load_user_purpose_routes(session, user_id)
    await session.rollback()
    planned_roadmap = await plan_initial_roadmap(
        request,
        settings=settings,
        user_id=user_id,
        request_id=getattr(http_request.state, "request_id", None),
        purpose_routes=purpose_routes,
    )

    world = None
    if existing_world_id is not None:
        world = await session.get(World, existing_world_id)
        if world is None or world.user_id != user_id:
            raise HTTPException(status_code=404, detail="World not found")
    if world is None:
        world = World(
            id=uuid4(),
            user_id=user_id,
            name=world_name,
            description=premise,
            genre=genre,
            rules={},
            lorebook=[],
            tone={"style": tone},
        )
        session.add(world)

    character = Character(
        id=uuid4(),
        user_id=user_id,
        world_id=world.id,
        name=protagonist_name,
        description=protagonist_role,
        persona={"identity": protagonist_role, "premise": premise},
        speaking_style={"tone": tone},
        relationship_to_user={},
        constraints={},
    )
    story_id = uuid4()
    branch_id = uuid4()
    story = Story(
        id=story_id,
        user_id=user_id,
        world_id=world.id,
        title=title,
        main_character_id=character.id,
        current_branch_id=branch_id,
        status="active",
        custom_prompt=custom_prompt or None,
        interaction_mode=request.interaction_mode,
        planned_chapter_count=request.planned_chapter_count,
        target_chapter_length=request.target_chapter_length,
        chapter_length_unit=request.chapter_length_unit,
        prose_language=request.prose_language.strip(),
    )
    branch = StoryBranch(
        id=branch_id,
        story_id=story_id,
        name="main",
        roadmap_version=1,
        roadmap_source=planned_roadmap.source,
        ending_title=planned_roadmap.draft.ending_title,
    )
    state = StoryState(mood=tone, objective=premise)
    session.add_all([character, story, branch])
    await session.flush()

    snapshot = StoryStateSnapshot(
        story_id=story_id,
        branch_id=branch_id,
        state={
            "location": state.location,
            "time": state.time,
            "mood": state.mood,
            "objective": state.objective,
            "inventory": state.inventory,
            "open_threads": state.open_threads,
            "relationships": [],
        },
    )
    session.add(snapshot)
    opening_message_id = None
    chapter_completed_at = None
    if request.opening_mode == "custom":
        opening_message_id = uuid4()
        chapter_completed_at = datetime.now(timezone.utc)
        session.add(
            Message(
                id=opening_message_id,
                story_id=story_id,
                branch_id=branch_id,
                role="assistant",
                content=opening_text,
                meta={
                    "chapter_number": 1,
                    "chapter_title": planned_roadmap.draft.chapters[0].title,
                },
            )
        )
    session.add_all(
        [
            StoryChapter(
                story_id=story_id,
                branch_id=branch_id,
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                objective=chapter.objective,
                status=(
                    "completed"
                    if chapter.chapter_number == 1 and opening_message_id is not None
                    else "active"
                    if chapter.chapter_number
                    == (2 if opening_message_id is not None else 1)
                    else "planned"
                ),
                roadmap_version=1,
                message_id=(opening_message_id if chapter.chapter_number == 1 else None),
                completed_at=(chapter_completed_at if chapter.chapter_number == 1 else None),
            )
            for chapter in planned_roadmap.draft.chapters
        ]
    )
    await session.commit()

    return await workspace(story_id=str(story_id), session=session, user_id=user_id)


@router.post("/story-draft", response_model=StoryDraftResponse)
async def generate_story_draft(
    request: GenerateStoryDraftRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> StoryDraftResponse:
    auditor = CallAuditor(
        settings,
        user_id=user_id,
        request_id=getattr(http_request.state, "request_id", None),
    )
    purpose_routes = await load_user_purpose_routes(session, user_id)
    gateway = LLMGateway(settings, auditor=auditor, purpose_routes=purpose_routes)
    current = request.model_dump()
    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是中文小说策划编辑。根据用户已有字段补全一套具体、可写、彼此一致的故事方案。"
                "保留用户已有想法的含义，不解释，不使用 Markdown，只返回 JSON 对象。"
                "必须包含 title、genre、world_name、premise、protagonist_name、"
                "protagonist_role、tone、opening_text 八个非空字符串字段。"
                "opening_text 写 120 至 260 个中文字符的小说正文，不写提纲。"
            ),
        ),
        ChatMessage(
            role="user",
            content=f"当前草稿如下；空字符串表示需要你提供灵感：\n{current}",
        ),
    ]
    llm_request = gateway.request_for_purpose("normal_chat", messages).model_copy(
        update={
            "max_output_tokens": 1800,
            "temperature": 0.88,
            "top_p": 0.92,
            "response_format": "json",
            "stream": False,
        }
    )
    try:
        response = await gateway.generate(gateway.normalize_request(llm_request))
        return StoryDraftResponse.model_validate_json(response.text)
    except QuotaExceededError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Story inspiration generation failed") from exc


async def _build_story_interview_request(
    request: StoryInterviewRequest,
    settings: Settings,
    session: AsyncSession,
    user_id: UUID,
    request_id: str | None = None,
) -> tuple[LLMGateway, LLMRequest]:
    preference_rows = list(
        (
            await session.execute(
                select(UserPreference)
                .where(
                    UserPreference.user_id == user_id,
                    UserPreference.is_active.is_(True),
                )
                .order_by(desc(UserPreference.strength), UserPreference.preference_type.asc())
            )
        )
        .scalars()
        .all()
    )
    preference_context = [
        f"{item.preference_type}: {item.content}" for item in preference_rows if item.content.strip()
    ]
    auditor = CallAuditor(settings, user_id=user_id, request_id=request_id)
    purpose_routes = await load_user_purpose_routes(session, user_id)
    gateway = LLMGateway(settings, auditor=auditor, purpose_routes=purpose_routes)
    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是 Witscraft 的小说创建采访编辑。通过自然、简短、无歧义的中文对话收集创作信息。"
                "每次回复只能问一个问题，不得连续询问两个或多个问题，也不重复询问已有内容。"
                "先把用户最新消息中能够确定的所有信息更新进 draft，再结合更新后的完整草稿动态选择下一条最有价值的问题；"
                "不得按固定字段顺序机械追问。后续问题和 options 必须引用并延续用户已经提供的类型、世界、人物、冲突或风格，"
                "用户新增或修改信息后必须重新评估问题重点。故事概念尚未清楚时不要急着索要书名。"
                "保留 draft 中非空字段，除非用户最新消息明确要求修改。"
                "可以基于用户想法提出具体建议，但不要替用户确认；所有内容最终必须由用户在卡片中确认。"
                "当 draft.interaction_mode 为 choices 时，每次提问必须提供 2 到 3 个简短、互斥、与当前故事相关的 options；"
                "options 只能作为当前问题的中性回答示例，不得借提问刻意引导后续剧情走向，不得擅自加入改变命运、"
                "牺牲、背叛、复仇、拯救世界、隐藏阴谋等用户尚未提出的重大方向；如果询问剧情，只围绕用户已明确的元素。"
                "绝对不要把“自定义”、Custom、Other 或其他同义项放进 options，界面会自动添加唯一的自定义入口。"
                "当 interaction_mode 为 open 时，options 必须返回空数组，让用户自由输入。"
                "只返回 JSON，字段顺序必须是 assistant_message、options、question_focus、draft；assistant_message 必须是第一个字段。"
                "question_focus 必须填写本轮唯一问题对应的 draft 字段名；如果已经完整则为 null。"
                "draft 必须包含 title、genre、world_name、"
                "premise、protagonist_name、protagonist_role、tone、opening_mode、opening_text、custom_prompt、interaction_mode、"
                "planned_chapter_count、target_chapter_length、chapter_length_unit、prose_language。"
                "opening_mode 只能是 blank 或 custom。没有可靠信息的字段保持空字符串。"
                "planned_chapter_count 必须为 3 到 120，target_chapter_length 必须为 500 到 5000；"
                "除非用户明确要求改变篇幅，否则保留当前数值和语言单位。"
                "custom_prompt 是必须收集的创建信息，但不要要求用户从零撰写：当类型、故事前提、主角和风格足够明确时，"
                "主动生成一份针对该小说类型的专业、具体、可执行 Prompt，覆盖叙事视角、语言质感、节奏、人物弧光、"
                "伏笔与连续性约束、应避免的问题，并保留给用户编辑。"
                "如果用户要求优化 Prompt，只更新 custom_prompt，保持其他非空字段。"
                "当所有必要字段都已明确时 options 返回空数组，assistant_message 告知小说已就绪并邀请确认创建。"
            ),
        ),
        ChatMessage(
            role="developer",
            content=(
                f"用户长期叙事偏好：{preference_context or ['尚未设置']}\n"
                f"当前可编辑草稿：{request.draft.model_dump_json()}\n"
                f"当前仍缺字段：{_story_interview_missing_fields(request.draft)}\n"
                f"处理最新消息前的建议关注点：{_choose_interview_focus(request.draft, request.message)}。"
                "先吸收最新消息，再自行重算真正的下一问，不必服从这个初始建议。"
            ),
        ),
    ]
    messages.extend(ChatMessage(role=item.role, content=item.content) for item in request.history[-20:])
    messages.append(ChatMessage(role="user", content=request.message.strip()))
    llm_request = gateway.request_for_purpose("normal_chat", messages).model_copy(
        update={
            "max_output_tokens": 1800,
            "temperature": 0.55,
            "top_p": 0.88,
            "response_format": "json",
            "stream": False,
        }
    )
    return gateway, gateway.normalize_request(llm_request)


async def _generate_story_interview(
    request: StoryInterviewRequest,
    settings: Settings,
    session: AsyncSession,
    user_id: UUID,
    request_id: str | None = None,
) -> StoryInterviewResponse:
    gateway, llm_request = await _build_story_interview_request(
        request, settings, session, user_id, request_id
    )
    try:
        response = await gateway.generate(llm_request)
        result = StoryInterviewResponse.model_validate_json(response.text)
        result = result.model_copy(
            update={
                "draft": result.draft.model_copy(
                    update={"interaction_mode": request.draft.interaction_mode}
                )
            }
        )
    except QuotaExceededError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Story interview generation failed") from exc

    return _finalize_story_interview(result, request.message)


@router.post("/story-interview", response_model=StoryInterviewResponse)
async def continue_story_interview(
    request: StoryInterviewRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> StoryInterviewResponse:
    return await _generate_story_interview(
        request,
        settings,
        session,
        user_id,
        getattr(http_request.state, "request_id", None),
    )


@router.post("/story-interview/stream")
async def stream_story_interview(
    request: StoryInterviewRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> StreamingResponse:
    async def events():
        yield f"event: start\ndata: {json.dumps({'type': 'start'})}\n\n"
        try:
            gateway, llm_request = await _build_story_interview_request(
                request,
                settings,
                session,
                user_id,
                getattr(http_request.state, "request_id", None),
            )
            raw_response = ""
            streamed_message = ""
            async for chunk in gateway.stream(llm_request):
                raw_response += chunk
                decoded_message = _extract_streamed_json_string(
                    raw_response, "assistant_message"
                )
                delta = decoded_message[len(streamed_message) :]
                if not delta:
                    continue
                streamed_message = decoded_message
                for offset in range(0, len(delta), 6):
                    payload = {"content": delta[offset : offset + 6]}
                    yield f"event: delta\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    if len(delta) > 12:
                        await asyncio.sleep(0.02)
            parsed_result = StoryInterviewResponse.model_validate_json(raw_response)
            parsed_result = parsed_result.model_copy(
                update={
                    "draft": parsed_result.draft.model_copy(
                        update={"interaction_mode": request.draft.interaction_mode}
                    )
                }
            )
            result = _finalize_story_interview(parsed_result, request.message)
        except QuotaExceededError as error:
            payload = {
                "detail": str(error),
                "status": 429,
                "scope": error.scope,
                "resets_at": error.snapshot.resets_at.isoformat(),
            }
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return
        except Exception:
            payload = {"detail": "Story interview generation failed", "status": 502}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return

        if streamed_message != result.assistant_message:
            replacement = {"content": result.assistant_message}
            yield f"event: replace\ndata: {json.dumps(replacement, ensure_ascii=False)}\n\n"

        payload = {"response": result.model_dump(mode="json")}
        yield f"event: done\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> UserPreferencesResponse:
    rows = list(
        (
            await session.execute(
                select(UserPreference)
                .where(UserPreference.user_id == user_id, UserPreference.is_active.is_(True))
                .order_by(UserPreference.preference_type.asc())
            )
        )
        .scalars()
        .all()
    )
    return UserPreferencesResponse(
        preferences=[
            UserPreferenceResponse(
                id=str(item.id),
                preference_type=item.preference_type,
                content=item.content,
                strength=item.strength,
            )
            for item in rows
        ]
    )


@router.put("/preferences", response_model=UserPreferencesResponse)
async def update_user_preferences(
    request: UserPreferencesUpdateRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> UserPreferencesResponse:
    requested = {item.preference_type: item for item in request.preferences if item.content.strip()}
    if len(requested) != len([item for item in request.preferences if item.content.strip()]):
        raise HTTPException(status_code=422, detail="Preference types must be unique")
    existing = list(
        (
            await session.execute(
                select(UserPreference).where(UserPreference.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    by_type = {item.preference_type: item for item in existing}
    for preference_type, payload in requested.items():
        row = by_type.get(preference_type)
        if row is None:
            row = UserPreference(
                id=uuid4(),
                user_id=user_id,
                preference_type=preference_type,
            )
            session.add(row)
        row.content = payload.content.strip()
        row.strength = payload.strength
        row.source = "user_settings"
        row.is_active = True
    for preference_type, row in by_type.items():
        if preference_type not in requested:
            await session.delete(row)
    await session.commit()
    return await get_user_preferences(session=session, user_id=user_id)


@router.patch("/stories/{story_id}", response_model=WorkspaceResponse)
async def update_story(
    story_id: str,
    request: UpdateStoryRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    if request.title is not None:
        story.title = request.title.strip()
    if request.custom_prompt is not None:
        story.custom_prompt = request.custom_prompt.strip() or None
    if request.interaction_mode is not None:
        story.interaction_mode = request.interaction_mode
    if request.consistency_mode is not None:
        story.consistency_mode = request.consistency_mode
    await session.commit()

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/stories/{story_id}", response_model=WorkspaceResponse)
async def delete_story(
    story_id: str,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    total_result = await session.execute(select(func.count(Story.id)).where(Story.user_id == user_id))
    if (total_result.scalar_one() or 0) <= 1:
        world_id = story.world_id
        await session.execute(
            delete(Story).where(Story.id == requested_story_id, Story.user_id == user_id)
        )
        await session.flush()
        await _delete_orphan_world(session, world_id, user_id)
        await session.commit()
        return _empty_workspace_response([], await _load_worlds(session, user_id))

    fallback_story = None
    active_id = _parse_uuid(active_story_id or "", DEFAULT_STORY_ID)
    if active_id != requested_story_id:
        fallback_story = await _get_story_for_user(session, active_id, user_id)

    if fallback_story is None:
        fallback_result = await session.execute(
            select(Story)
            .where(Story.user_id == user_id, Story.id != requested_story_id)
            .order_by(desc(Story.updated_at))
            .limit(1)
        )
        fallback_story = fallback_result.scalar_one()

    world_id = story.world_id
    await session.execute(
        delete(Story).where(Story.id == requested_story_id, Story.user_id == user_id)
    )
    await session.flush()
    await _delete_orphan_world(session, world_id, user_id)
    await session.commit()

    return await workspace(story_id=str(fallback_story.id), session=session, user_id=user_id)


@router.post("/stories/{story_id}/branches", response_model=WorkspaceResponse)
async def create_branch(
    story_id: str,
    request: CreateBranchRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    source_branch_id = story.current_branch_id or UUID("00000000-0000-0000-0000-000000000401")
    source_branch = await session.get(StoryBranch, source_branch_id)
    if source_branch is None or source_branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Source branch not found")

    branch = await clone_story_branch(
        session,
        story=story,
        source_branch=source_branch,
        user_id=user_id,
        name=request.name.strip() or "新分支",
        settings=settings,
    )
    story.current_branch_id = branch.id
    await session.commit()

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.patch("/stories/{story_id}/branches/{branch_id}", response_model=WorkspaceResponse)
async def update_branch(
    story_id: str,
    branch_id: str,
    request: UpdateBranchRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story, branch = await _get_story_branch_for_user(session, story_id, branch_id, user_id)
    branch.name = request.name.strip()
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.post("/stories/{story_id}/branches/{branch_id}/duplicate", response_model=WorkspaceResponse)
async def duplicate_branch(
    story_id: str,
    branch_id: str,
    request: CreateBranchRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story, source_branch = await _get_story_branch_for_user(session, story_id, branch_id, user_id)
    await clone_story_branch(
        session,
        story=story,
        source_branch=source_branch,
        user_id=user_id,
        name=request.name.strip() or f"{source_branch.name} copy",
        settings=settings,
    )
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/stories/{story_id}/branches/{branch_id}", response_model=WorkspaceResponse)
async def delete_branch(
    story_id: str,
    branch_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story, branch = await _get_story_branch_for_user(session, story_id, branch_id, user_id)
    count_result = await session.execute(
        select(func.count(StoryBranch.id)).where(StoryBranch.story_id == story.id)
    )
    if (count_result.scalar_one() or 0) <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the final branch")

    fallback_branch = None
    if branch.parent_branch_id is not None:
        parent = await session.get(StoryBranch, branch.parent_branch_id)
        if parent is not None and parent.story_id == story.id:
            fallback_branch = parent
    if fallback_branch is None:
        fallback_result = await session.execute(
            select(StoryBranch)
            .where(StoryBranch.story_id == story.id, StoryBranch.id != branch.id)
            .order_by(StoryBranch.created_at.asc(), StoryBranch.id.asc())
            .limit(1)
        )
        fallback_branch = fallback_result.scalar_one()

    await session.execute(
        update(StoryBranch)
        .where(StoryBranch.parent_branch_id == branch.id)
        .values(parent_branch_id=branch.parent_branch_id)
    )
    if story.current_branch_id == branch.id:
        story.current_branch_id = fallback_branch.id
    await session.execute(delete(StoryBranch).where(StoryBranch.id == branch.id))
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.patch("/stories/{story_id}/branches/{branch_id}/activate", response_model=WorkspaceResponse)
async def activate_branch(
    story_id: str,
    branch_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    requested_branch_id = _parse_uuid(branch_id, UUID("00000000-0000-0000-0000-000000000401"))
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")

    story.current_branch_id = branch.id
    await session.commit()

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.post("/stories/{story_id}/branches/{branch_id}/summaries", response_model=WorkspaceResponse)
async def create_summary(
    story_id: str,
    branch_id: str,
    http_request: Request,
    request: GenerateSummaryRequest | None = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    del request
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    requested_branch_id = _parse_uuid(branch_id, UUID("00000000-0000-0000-0000-000000000401"))
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")

    try:
        auditor = CallAuditor(
            settings,
            user_id=user_id,
            story_id=story.id,
            request_id=getattr(http_request.state, "request_id", None),
        )
        await generate_session_summary(
            session,
            LLMGateway(
                settings,
                auditor=auditor,
                purpose_routes=await load_user_purpose_routes(session, user_id),
            ),
            story,
            branch,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.get("/stories/{story_id}/branches/{branch_id}/export")
async def export_story(
    story_id: str,
    branch_id: str,
    format: str = "markdown",
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> Response:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    requested_branch_id = _parse_uuid(branch_id, UUID("00000000-0000-0000-0000-000000000401"))
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")

    payload = await build_story_export_payload(session, story, branch)
    normalized_format = format.strip().lower()
    if normalized_format in {"markdown", "md"}:
        content = render_story_markdown(payload)
        filename = export_filename(story.title, branch.name, "md")
        media_type = "text/markdown; charset=utf-8"
    elif normalized_format == "json":
        content = render_story_json(payload)
        filename = export_filename(story.title, branch.name, "json")
        media_type = "application/json; charset=utf-8"
    else:
        raise HTTPException(status_code=422, detail="Export format must be markdown or json")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/worlds/{world_id}", response_model=WorkspaceResponse)
async def update_world(
    world_id: str,
    request: UpdateWorldRequest,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_world_id = _parse_uuid(world_id, DEFAULT_WORLD_ID)
    world = await session.get(World, requested_world_id)
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="World name cannot be empty")

    world.name = name
    world.description = request.description.strip()
    world.genre = request.genre.strip()
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", DEFAULT_STORY_ID)
    active_story = await _get_story_for_user(session, active_id, user_id)
    if active_story is None:
        result = await session.execute(
            select(Story)
            .where(Story.user_id == user_id, Story.world_id == world.id)
            .order_by(desc(Story.updated_at))
            .limit(1)
        )
        active_story = result.scalar_one_or_none()

    return await workspace(
        story_id=str(active_story.id if active_story else DEFAULT_STORY_ID),
        session=session,
        user_id=user_id,
    )


@router.post("/worlds", response_model=WorkspaceResponse)
async def create_world(
    request: UpdateWorldRequest,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story = await _get_story_for_user(
        session,
        _parse_uuid(active_story_id, DEFAULT_STORY_ID),
        user_id,
    )
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="World name cannot be empty")
    world = World(
        user_id=user_id,
        name=name,
        description=request.description.strip(),
        genre=request.genre.strip(),
        rules={},
        lorebook=[],
        tone={},
    )
    session.add(world)
    await session.flush()
    story.world_id = world.id
    story.main_character_id = None
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.patch("/stories/{story_id}/world", response_model=WorkspaceResponse)
async def set_story_world(
    story_id: str,
    request: SetStoryWorldRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story = await _get_story_for_user(session, _parse_uuid(story_id, DEFAULT_STORY_ID), user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    world = await session.get(World, _parse_uuid(request.world_id, DEFAULT_WORLD_ID))
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")

    story.world_id = world.id
    story.main_character_id = await session.scalar(
        select(Character.id)
        .where(Character.user_id == user_id, Character.world_id == world.id)
        .order_by(Character.created_at.asc())
        .limit(1)
    )
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/worlds/{world_id}", response_model=WorkspaceResponse)
async def delete_world(
    world_id: str,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_world_id = _parse_uuid(world_id, DEFAULT_WORLD_ID)
    world = await session.get(World, requested_world_id)
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")
    story_count = await session.scalar(
        select(func.count(Story.id)).where(Story.user_id == user_id, Story.world_id == world.id)
    )
    if story_count:
        raise HTTPException(status_code=409, detail="World is still used by a story")

    await session.execute(
        delete(Character).where(Character.user_id == user_id, Character.world_id == world.id)
    )
    await session.delete(world)
    await session.commit()
    return await workspace(story_id=active_story_id, session=session, user_id=user_id)


@router.patch("/characters/{character_id}", response_model=WorkspaceResponse)
async def update_character(
    character_id: str,
    request: UpdateCharacterRequest,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_character_id = _parse_uuid(character_id, DEFAULT_CHARACTER_ID)
    character = await session.get(Character, requested_character_id)
    if character is None or character.user_id != user_id:
        raise HTTPException(status_code=404, detail="Character not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Character name cannot be empty")

    character.name = name
    character.description = request.role.strip()
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", DEFAULT_STORY_ID)
    active_story = await _get_story_for_user(session, active_id, user_id)
    if active_story is None:
        result = await session.execute(
            select(Story)
            .where(Story.user_id == user_id, Story.world_id == character.world_id)
            .order_by(desc(Story.updated_at))
            .limit(1)
        )
        active_story = result.scalar_one_or_none()

    return await workspace(
        story_id=str(active_story.id if active_story else DEFAULT_STORY_ID),
        session=session,
        user_id=user_id,
    )


@router.post("/worlds/{world_id}/characters", response_model=WorkspaceResponse)
async def create_character(
    world_id: str,
    request: UpdateCharacterRequest,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    world = await session.get(World, _parse_uuid(world_id, DEFAULT_WORLD_ID))
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")
    story = await _get_story_for_user(
        session,
        _parse_uuid(active_story_id, DEFAULT_STORY_ID),
        user_id,
    )
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Character name cannot be empty")
    character = Character(
        user_id=user_id,
        world_id=world.id,
        name=name,
        description=request.role.strip(),
        persona={"identity": request.role.strip()},
        speaking_style={},
        relationship_to_user={},
        constraints={},
    )
    session.add(character)
    await session.flush()
    if story.world_id == world.id and story.main_character_id is None:
        story.main_character_id = character.id
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/characters/{character_id}", response_model=WorkspaceResponse)
async def delete_character(
    character_id: str,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    character = await session.get(
        Character,
        _parse_uuid(character_id, DEFAULT_CHARACTER_ID),
    )
    if character is None or character.user_id != user_id:
        raise HTTPException(status_code=404, detail="Character not found")
    main_count = await session.scalar(
        select(func.count(Story.id)).where(
            Story.user_id == user_id,
            Story.main_character_id == character.id,
        )
    )
    if main_count:
        raise HTTPException(status_code=409, detail="A story's main character cannot be deleted")

    await session.delete(character)
    await session.commit()
    return await workspace(story_id=active_story_id, session=session, user_id=user_id)


@router.patch("/memories/{memory_id}", response_model=WorkspaceResponse)
async def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    http_request: Request,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_memory_id = _parse_uuid(memory_id, uuid4())
    memory = await session.get(MemoryItem, requested_memory_id)
    if memory is None or memory.user_id != user_id:
        raise HTTPException(status_code=404, detail="Memory not found")

    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Memory content cannot be empty")

    content_hash = embedding_content_hash(content)
    duplicate_id = await session.scalar(
        select(MemoryItem.id)
        .where(
            MemoryItem.id != memory.id,
            MemoryItem.user_id == user_id,
            MemoryItem.story_id == memory.story_id,
            MemoryItem.branch_id == memory.branch_id,
            MemoryItem.is_active.is_(True),
            or_(
                MemoryItem.content_hash == content_hash,
                MemoryItem.content == content,
            ),
        )
        .limit(1)
    )
    if duplicate_id is not None:
        raise HTTPException(status_code=409, detail="An active memory with this content already exists")

    content_changed = memory.content_hash != content_hash
    memory.content = content
    memory.importance = request.importance
    if content_changed:
        memory.entity_tags = []
        memory.embedding = None
        memory.embedding_vector = None
        memory.embedding_model = None
        memory.embedding_dimensions = None
        memory.embedding_version = None
        memory.content_hash = None
        memory.embedded_at = None
        await enqueue_memory_embedding(
            session,
            memory,
            max_attempts=settings.memory_embedding_task_max_attempts,
        )
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", memory.story_id or DEFAULT_STORY_ID)
    return await workspace(story_id=str(active_id), session=session, user_id=user_id)


@router.patch("/canon-facts/{fact_id}", response_model=WorkspaceResponse)
async def update_canon_fact(
    fact_id: str,
    request: UpdateCanonFactRequest,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_fact_id = _parse_uuid(fact_id, uuid4())
    fact = await session.get(CanonFact, requested_fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Canon fact not found")
    story = await _get_story_for_user(session, fact.story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Canon fact not found")

    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Canon fact content cannot be empty")

    fact.content = content
    fact.importance = request.importance
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", fact.story_id or DEFAULT_STORY_ID)
    return await workspace(story_id=str(active_id), session=session, user_id=user_id)


async def _load_stories(session: AsyncSession, user_id: UUID) -> list[dict]:
    result = await session.execute(
        select(Story, World.name)
        .outerjoin(World, Story.world_id == World.id)
        .where(Story.user_id == user_id)
        .order_by(desc(Story.updated_at))
    )
    return [
        {
            "id": str(story.id),
            "title": story.title,
            "world": world_name or "",
            "updated": story.updated_at.isoformat() if story.updated_at else "",
            "wordCount": 0,
            "status": story.status,
        }
        for story, world_name in result.all()
    ]


def _empty_workspace_response(stories: list[dict], worlds: list[dict]) -> WorkspaceResponse:
    return WorkspaceResponse(
        story_id="",
        branch_id="",
        branches=[],
        stories=stories,
        world={},
        worlds=worlds,
        characters=[],
        messages=[],
        story_state=StoryState(),
        relationships=[],
        retrieved_memories=[],
        canon_facts=[],
        memory_items=[],
        canon_fact_items=[],
        summaries=[],
        model_call=None,
        onboarding_required=True,
        story_prompt="",
    )


async def _delete_orphan_world(
    session: AsyncSession,
    world_id: UUID | None,
    user_id: UUID,
) -> None:
    if world_id is None:
        return
    story_count = await session.scalar(
        select(func.count(Story.id)).where(Story.world_id == world_id, Story.user_id == user_id)
    )
    if story_count:
        return
    await session.execute(
        delete(Character).where(Character.world_id == world_id, Character.user_id == user_id)
    )
    await session.execute(delete(World).where(World.id == world_id, World.user_id == user_id))


async def _load_worlds(session: AsyncSession, user_id: UUID) -> list[dict]:
    result = await session.execute(
        select(World, func.count(Story.id))
        .outerjoin(Story, (Story.world_id == World.id) & (Story.user_id == user_id))
        .where(World.user_id == user_id)
        .group_by(World.id)
        .order_by(desc(World.updated_at), World.name.asc())
    )
    return [
        {
            "id": str(world.id),
            "name": world.name,
            "genre": world.genre or "",
            "story_count": story_count,
        }
        for world, story_count in result.all()
    ]


async def _load_branches(session: AsyncSession, story_id: UUID, active_branch_id: UUID) -> list[dict]:
    result = await session.execute(
        select(StoryBranch)
        .where(StoryBranch.story_id == story_id)
        .order_by(StoryBranch.created_at.asc())
    )
    return [
        {
            "id": str(branch.id),
            "name": branch.name,
            "parent_branch_id": str(branch.parent_branch_id) if branch.parent_branch_id else None,
            "created_at": branch.created_at.isoformat() if branch.created_at else "",
            "active": branch.id == active_branch_id,
            "version": branch.version,
            "roadmap_version": branch.roadmap_version,
            "roadmap_source": branch.roadmap_source,
            "ending_title": branch.ending_title or "",
        }
        for branch in result.scalars().all()
    ]


async def _load_world(session: AsyncSession, world_id, user_id: UUID) -> dict:
    if world_id is None:
        return {}
    world = await session.get(World, world_id)
    if world is None or world.user_id != user_id:
        return {}
    return {
        "id": str(world.id),
        "name": world.name,
        "description": world.description,
        "genre": world.genre,
        "rules": world.rules,
        "lorebook": world.lorebook,
        "tone": world.tone,
    }


async def _load_characters(
    session: AsyncSession,
    world_id,
    user_id: UUID,
    main_character_id: UUID | None,
) -> list[dict]:
    query = select(Character).where(Character.user_id == user_id)
    if world_id is not None:
        query = query.where(Character.world_id == world_id)
    result = await session.execute(query.order_by(Character.created_at.asc()))
    characters = []
    for character in result.scalars().all():
        characters.append(
            {
                "id": str(character.id),
                "name": character.name,
                "role": character.description or character.persona.get("identity", ""),
                "present": True,
                "initials": character.name[:1],
                "main": character.id == main_character_id,
            }
        )
    return characters


async def _load_messages(
    session: AsyncSession, story_id: UUID, branch_id: UUID
) -> list[WorkspaceMessage]:
    result = await session.execute(
        select(Message)
        .where(Message.story_id == story_id, Message.branch_id == branch_id)
        .order_by(
            Message.created_at.asc(),
            case((Message.role == "user", 0), (Message.role == "assistant", 1), else_=2),
            Message.id.asc(),
        )
        .limit(80)
    )
    return [
        WorkspaceMessage(
            id=str(message.id),
            role=message.role,
            content=message.content,
            author=message.meta.get("author") if message.meta else None,
            time=message.meta.get("time") if message.meta else None,
            choices=message.meta.get("choices", []) if message.meta else [],
            consistency_check=message.meta.get("consistency_check") if message.meta else None,
        )
        for message in result.scalars().all()
    ]


async def _load_chapters(
    session: AsyncSession,
    story_id: UUID,
    branch_id: UUID,
) -> list[dict]:
    result = await session.execute(
        select(StoryChapter)
        .where(StoryChapter.story_id == story_id, StoryChapter.branch_id == branch_id)
        .order_by(StoryChapter.chapter_number.asc())
    )
    return [
        {
            "id": str(chapter.id),
            "number": chapter.chapter_number,
            "title": chapter.title,
            "objective": chapter.objective or "",
            "status": chapter.status,
            "roadmap_version": chapter.roadmap_version,
            "message_id": str(chapter.message_id) if chapter.message_id else None,
            "completed_at": chapter.completed_at.isoformat() if chapter.completed_at else None,
        }
        for chapter in result.scalars().all()
    ]


async def _load_state(session: AsyncSession, story_id: UUID, branch_id: UUID):
    result = await session.execute(
        select(StoryStateSnapshot)
        .where(StoryStateSnapshot.story_id == story_id, StoryStateSnapshot.branch_id == branch_id)
        .order_by(desc(StoryStateSnapshot.created_at))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return StoryState(), []
    state = StoryState(
        location=snapshot.state.get("location", "未知地点"),
        time=snapshot.state.get("time", "未知时间"),
        mood=snapshot.state.get("mood", "未定义"),
        objective=snapshot.state.get("objective", "继续推进剧情"),
        inventory=snapshot.state.get("inventory", []),
        open_threads=snapshot.state.get("open_threads", []),
    )
    return state, snapshot.state.get("relationships", [])


async def _load_memory_items(session: AsyncSession, story_id: UUID, branch_id: UUID) -> list[dict]:
    result = await session.execute(
        select(MemoryItem)
        .where(MemoryItem.story_id == story_id, MemoryItem.branch_id == branch_id, MemoryItem.is_active.is_(True))
        .order_by(
            case((MemoryItem.meta["source"].astext == "llm_state_extractor", 0), else_=1),
            desc(MemoryItem.importance),
            desc(MemoryItem.updated_at),
        )
        .limit(8)
    )
    return [
        {
            "id": str(memory.id),
            "content": memory.content,
            "importance": memory.importance,
            "type": memory.memory_type,
            "has_embedding": stored_embedding(memory) is not None,
            "embedding_model": memory.embedding_model,
            "embedding_dimensions": memory.embedding_dimensions
            or len(stored_embedding(memory) or []),
            "embedding_version": memory.embedding_version,
        }
        for memory in result.scalars().all()
    ]


async def _load_canon_fact_items(session: AsyncSession, story_id: UUID, branch_id: UUID) -> list[dict]:
    result = await session.execute(
        select(CanonFact)
        .where(CanonFact.story_id == story_id, CanonFact.branch_id == branch_id, CanonFact.is_active.is_(True))
        .order_by(
            case((CanonFact.fact_type == "llm_state_extraction", 0), else_=1),
            desc(CanonFact.importance),
            desc(CanonFact.created_at),
        )
        .limit(12)
    )
    return [
        {
            "id": str(fact.id),
            "content": fact.content,
            "importance": fact.importance,
            "type": fact.fact_type,
        }
        for fact in result.scalars().all()
    ]


async def _load_summaries(session: AsyncSession, story_id: UUID, branch_id: UUID) -> list[dict]:
    result = await session.execute(
        select(StorySummary)
        .where(StorySummary.story_id == story_id, StorySummary.branch_id == branch_id)
        .order_by(desc(StorySummary.created_at))
        .limit(6)
    )
    return [
        {
            "id": str(summary.id),
            "parent_summary_id": (
                str(summary.parent_summary_id) if summary.parent_summary_id else None
            ),
            "title": summary.title,
            "content": summary.content,
            "type": summary.summary_type,
            "prompt_version": summary.prompt_version,
            "provider": summary.provider,
            "model": summary.model,
            "trigger": summary.trigger,
            "message_count": summary.message_count,
            "token_count": summary.token_count,
            "created_at": summary.created_at.isoformat() if summary.created_at else "",
        }
        for summary in result.scalars().all()
    ]


async def _load_model_call(session: AsyncSession, story_id: UUID) -> dict | None:
    result = await session.execute(
        select(ModelCall)
        .where(
            ModelCall.story_id == story_id,
            ModelCall.call_type == "llm",
            ModelCall.status == "succeeded",
            ModelCall.purpose.in_(("normal_chat", "critical_story_generation")),
        )
        .order_by(desc(ModelCall.created_at))
        .limit(1)
    )
    call = result.scalar_one_or_none()
    if call is None:
        return None
    return {
        "id": str(call.id),
        "provider": call.provider,
        "model": call.model,
        "purpose": call.purpose,
        "latency_ms": call.latency_ms,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cost_estimate": float(call.cost_estimate) if call.cost_estimate is not None else None,
        "turn_id": str(call.turn_id) if call.turn_id else None,
        "request_id": call.request_id,
        "status": call.status,
        "pricing_version": call.pricing_version,
        "dry_run": call.response.get("dry_run", False) if call.response else False,
    }


async def _get_story_for_user(session: AsyncSession, story_id: UUID, user_id: UUID) -> Story | None:
    result = await session.execute(select(Story).where(Story.id == story_id, Story.user_id == user_id).limit(1))
    return result.scalar_one_or_none()


async def _get_story_branch_for_user(
    session: AsyncSession,
    story_id: str,
    branch_id: str,
    user_id: UUID,
) -> tuple[Story, StoryBranch]:
    try:
        requested_story_id = UUID(story_id)
        requested_branch_id = UUID(branch_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Story or branch not found") from error

    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")
    return story, branch


def _parse_uuid(value: str, fallback: UUID) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        return fallback


def _parse_uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
