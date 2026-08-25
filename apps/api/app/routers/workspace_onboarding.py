"""Story onboarding, style-profile, and preference workspace routes."""

import asyncio
import json
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.models import StyleProfile, UserPreference
from app.db.session import get_session
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway
from app.schemas.chat import (
    AnalyzeStyleProfileRequest,
    GenerateStoryDraftRequest,
    StoryDraftResponse,
    StoryInterviewDraft,
    StoryInterviewRequest,
    StoryInterviewResponse,
    StyleProfileResponse,
    UserPreferenceResponse,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
)
from app.schemas.llm import ChatMessage, LLMRequest
from app.services.model_route_service import load_user_purpose_routes
from app.services.quota_service import QuotaExceededError
from app.services.style_profiles import (
    STYLE_ANALYSIS_VERSION,
    analyze_style_features,
    normalize_reference_text,
    public_style_features,
    reference_content_hash,
)

router = APIRouter()
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
    "premise": (
        "目前最想明确故事前提中的哪一部分？",
        ["主角当前面对的问题", "故事开始时发生的事件", "尚未解决的核心矛盾"],
    ),
    "protagonist_name": ("主角的名字更接近哪种感觉？", ["真实日常", "古典含蓄", "鲜明独特"]),
    "protagonist_role": (
        "主角最重要的身份与目标是什么？",
        ["普通人被卷入事件", "专业人士主动调查", "局内人试图逃离"],
    ),
    "tone": (
        "你希望读者最直接感受到哪种叙事气质？",
        ["克制而有画面感", "轻快而有张力", "浓烈而富有诗意"],
    ),
    "opening_text": (
        "你希望自定义开场从哪个瞬间开始？",
        ["冲突发生前一刻", "异常已经出现", "主角做出决定"],
    ),
    "custom_prompt": (
        "专属创作 Prompt 更应优先强化哪一点？",
        ["人物声音与视角", "悬念节奏与伏笔", "世界规则与连续性"],
    ),
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
        for field in (
            "genre",
            "world_name",
            "premise",
            "protagonist_name",
            "protagonist_role",
            "tone",
        )
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
    focus = (
        requested_focus
        or inferred_focus
        or _choose_interview_focus(result.draft, latest_user_message)
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
        position for marker in ("？", "?") if (position := assistant_message.find(marker)) >= 0
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
    escapes = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
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
            if len(codepoint) < 4 or not all(
                item in "0123456789abcdefABCDEF" for item in codepoint
            ):
                break
            output.append(chr(int(codepoint, 16)))
            position += 6
            continue
        if escaped not in escapes:
            break
        output.append(escapes[escaped])
        position += 2
    return "".join(output)


def _style_profile_response(profile: StyleProfile, *, reused: bool) -> StyleProfileResponse:
    return StyleProfileResponse(
        id=str(profile.id),
        name=profile.name,
        source_type=profile.source_type,
        source_label=profile.source_label,
        content_hash=profile.content_hash,
        analysis_version=profile.analysis_version,
        language=profile.language,
        features=public_style_features(profile.features),
        reused=reused,
    )


@router.post("/style-profiles", response_model=StyleProfileResponse)
async def analyze_style_profile(
    request: AnalyzeStyleProfileRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> StyleProfileResponse:
    normalized = normalize_reference_text(request.raw_text)
    content_hash = reference_content_hash(normalized)
    existing = await session.scalar(
        select(StyleProfile).where(
            StyleProfile.user_id == user_id,
            StyleProfile.content_hash == content_hash,
            StyleProfile.analysis_version == STYLE_ANALYSIS_VERSION,
        )
    )
    if existing is not None:
        return _style_profile_response(existing, reused=True)
    profile = StyleProfile(
        user_id=user_id,
        name=request.name.strip(),
        source_type=request.source_type,
        source_label=request.source_label.strip() or None,
        content_hash=content_hash,
        analysis_version=STYLE_ANALYSIS_VERSION,
        language=request.language.strip(),
        features=analyze_style_features(normalized, request.language, content_hash),
    )
    session.add(profile)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        concurrent = await session.scalar(
            select(StyleProfile).where(
                StyleProfile.user_id == user_id,
                StyleProfile.content_hash == content_hash,
                StyleProfile.analysis_version == STYLE_ANALYSIS_VERSION,
            )
        )
        if concurrent is None:
            raise
        return _style_profile_response(concurrent, reused=True)
    await session.refresh(profile)
    return _style_profile_response(profile, reused=False)


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
        f"{item.preference_type}: {item.content}"
        for item in preference_rows
        if item.content.strip()
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
                "planned_chapter_count、minimum_chapter_length、chapter_length_unit、prose_language。"
                "opening_mode 只能是 blank 或 custom。没有可靠信息的字段保持空字符串。"
                "planned_chapter_count 必须为 3 到 120，minimum_chapter_length 必须为 500 到 5000；"
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
    messages.extend(
        ChatMessage(role=item.role, content=item.content) for item in request.history[-20:]
    )
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
                    update={
                        "interaction_mode": request.draft.interaction_mode,
                        "style_profile_id": request.draft.style_profile_id,
                    }
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
                decoded_message = _extract_streamed_json_string(raw_response, "assistant_message")
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
                        update={
                            "interaction_mode": request.draft.interaction_mode,
                            "style_profile_id": request.draft.style_profile_id,
                        }
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
        (await session.execute(select(UserPreference).where(UserPreference.user_id == user_id)))
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
