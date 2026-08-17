import asyncio
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from uuid import UUID, uuid4

import anyio
from fastapi import HTTPException
from sqlalchemy import and_, case, delete, desc, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.bootstrap import DEFAULT_BRANCH_ID, DEFAULT_STORY_ID
from app.db.models import (
    CanonFact,
    Character,
    GenerationRequest,
    MemoryItem,
    Message,
    ModelCall,
    Story,
    StoryBranch,
    StoryStateSnapshot,
    StorySummary,
    UserPreference,
    World,
)
from app.llm.model_registry import get_model
from app.llm.router import LLMGateway
from app.schemas.chat import ChatRequest, ChatResponse, StoryState
from app.schemas.llm import ChatMessage, LLMRequest, LLMResponse
from app.services.consistency_checker import check_response_consistency
from app.services.context_assembler import ContextAssembly, assemble_story_context
from app.services.embeddings import EmbeddingService, cosine_similarity, embedding_content_hash
from app.services.state_extractor import extract_story_updates_with_llm
from app.services.turn_context import TurnContext


STORY_CHOICES_MARKER = "[STORY_CHOICES]"
STORY_CHOICES_PATTERN = re.compile(
    r"(?:\[STORY_CHOICES\]|STORY_CHOICES\s*:|【剧情(?:推进)?选项】|剧情(?:推进)?选项\s*[:：])",
    re.IGNORECASE,
)
MEMORY_RESULT_LIMIT = 8
MEMORY_VECTOR_SEARCH_MIN_ITEMS = 40
MEMORY_CANDIDATE_LIMIT = 128
MEMORY_ACCEPTANCE_THRESHOLD = 5
MEMORY_DUPLICATE_SIMILARITY = 0.88
MEMORY_EVENT_MARKERS = (
    "发现",
    "得知",
    "揭露",
    "确认",
    "决定",
    "承诺",
    "背叛",
    "救下",
    "死亡",
    "失踪",
    "获得",
    "拾到",
    "拿到",
    "交给",
    "失去",
    "摧毁",
    "解锁",
    "打开",
    "关闭",
    "逃离",
    "抵达",
    "离开",
    "改变",
    "成为",
    "拒绝",
    "同意",
    "袭击",
    "受伤",
    "牺牲",
    "discovers",
    "learns",
    "reveals",
    "confirms",
    "decides",
    "promises",
    "betrays",
    "rescues",
    "dies",
    "vanishes",
    "obtains",
    "loses",
    "destroys",
    "unlocks",
    "escapes",
    "arrives",
    "leaves",
)
MEMORY_CONSEQUENCE_MARKERS = (
    "因此",
    "导致",
    "从此",
    "不再",
    "首次",
    "终于",
    "永久",
    "秘密",
    "真相",
    "therefore",
    "permanently",
    "secret",
    "truth",
)


@dataclass(frozen=True)
class PreparedMemory:
    content: str
    importance: int
    entity_tags: tuple[str, ...]
    embedding: list[float]
    embedding_model: str
    embedding_dimensions: int
    embedding_version: str
    content_hash: str
    embedded_at: datetime


def _normalize_story_choices(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("choices") or value.get("options") or []
    if not isinstance(value, list):
        return []
    blocked = ("自定义", "custom", "other")
    choices: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        option = re.sub(r"^[A-Ca-c1-3][.、):：]\s*", "", item.strip())
        normalized = option.casefold()
        if not option or any(token in normalized for token in blocked) or option in choices:
            continue
        choices.append(option)
        if len(choices) == 3:
            break
    return choices if len(choices) >= 2 else []


def _parse_story_choices(raw_choices: str) -> list[str]:
    stripped = raw_choices.strip()
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    try:
        return _normalize_story_choices(json.loads(stripped))
    except (json.JSONDecodeError, TypeError):
        lines = [
            re.sub(r"^(?:[-*•]|[A-Ca-c1-3][.、):：])\s*", "", line).strip()
            for line in stripped.splitlines()
            if line.strip()
        ]
        return _normalize_story_choices(lines)


def split_story_response(text: str, interaction_mode: str) -> tuple[str, list[str]]:
    match = STORY_CHOICES_PATTERN.search(text)
    marker_index = match.start() if match else -1
    content = (text[:marker_index] if match else text).strip()
    if interaction_mode != "choices" or match is None:
        return content, []
    return content, _parse_story_choices(text[match.end() :])


def visible_stream_story_text(text: str) -> str:
    marker_index = text.find(STORY_CHOICES_MARKER)
    if marker_index >= 0:
        return text[:marker_index]
    held_suffix = len(STORY_CHOICES_MARKER) - 1
    return text[: max(0, len(text) - held_suffix)]


class StoryEngine:
    def __init__(self, llm_gateway: LLMGateway, session: AsyncSession, user_id: UUID):
        self.llm_gateway = llm_gateway
        self.session = session
        self.user_id = user_id
        self.embedding_service = EmbeddingService(
            llm_gateway.settings,
            auditor=llm_gateway.auditor,
        )
        self.turn_context = TurnContext()
        self._active_generation_id: UUID | None = None

    async def send(self, request: ChatRequest) -> ChatResponse:
        story_id = self._parse_uuid(request.story_id, DEFAULT_STORY_ID)
        story = await self._get_story(story_id)
        branch_id = self._parse_uuid(request.branch_id, story.current_branch_id or DEFAULT_BRANCH_ID)
        branch = await self._get_branch(story.id, branch_id)
        generation, replay = await self._claim_generation(request, story, branch)
        if replay is not None:
            return replay
        self._begin_audit_turn(story.id)

        target_message, source_user_text, generation_request = await self._prepare_generation_command(
            request,
            story,
            branch,
        )
        user_message: Message | None = None
        if target_message is None:
            user_message = Message(
                story_id=story.id,
                branch_id=branch.id,
                role="user",
                content=request.message,
                meta={"author": "你"},
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(user_message)
            await self.session.flush()
            generation.user_message_id = user_message.id
            await self.session.commit()

        state, relationships, context = await self._assemble_context(
            story,
            branch,
            generation_request,
            exclude_message_id=target_message.id if target_message else None,
            recent_exclude_message_ids={user_message.id} if user_message else None,
        )
        prompt_messages = context.prompt_messages
        await self.session.commit()

        if generation_request.provider and generation_request.model:
            option = get_model(generation_request.model)
            llm_request = LLMRequest(
                provider=generation_request.provider,
                model=generation_request.model,
                messages=prompt_messages,
                purpose=generation_request.purpose,
                max_output_tokens=generation_request.max_output_tokens
                or (option.default_max_output_tokens if option else 2400),
                temperature=option.temperature if option else 0.82,
                top_p=option.top_p if option else 0.92,
                reasoning_effort=option.reasoning_effort if option else None,
                stream=generation_request.stream,
            )
        else:
            llm_request = self.llm_gateway.request_for_purpose(
                generation_request.purpose,
                prompt_messages,
            )

        llm_request = self.llm_gateway.normalize_request(llm_request)
        llm_response = await self.llm_gateway.generate(llm_request)
        response_content, response_choices = split_story_response(
            llm_response.text,
            story.interaction_mode or "choices",
        )
        response_choices = await self._ensure_story_choices(
            story.interaction_mode or "choices",
            response_content,
            response_choices,
            context,
        )
        response_content, consistency_check, consistency_revision = await self._apply_consistency_policy(
            response_content,
            state,
            context,
            story.consistency_mode or "auto",
        )
        llm_response = llm_response.model_copy(update={"text": response_content})

        perspective_character = await self._main_character_name(story)
        await self.session.commit()
        extraction = await extract_story_updates_with_llm(
            self.llm_gateway,
            state,
            source_user_text,
            llm_response.text,
            relationships=relationships,
            perspective_character=perspective_character,
        )
        prepared_memories, prepared_canon_facts = await self._prepare_extracted_knowledge(
            story,
            branch,
            extraction.memories,
            extraction.canon_facts,
            entity_names=self._memory_entity_names(
                extraction.state,
                extraction.relationships,
                perspective_character,
            ),
        )

        assistant_message = target_message or Message(
            story_id=story.id,
            branch_id=branch.id,
            role="assistant",
            content=llm_response.text,
            token_count=llm_response.output_tokens,
            meta={"author": "叙事引擎", "time": state.time, "choices": response_choices},
            created_at=datetime.now(timezone.utc),
        )
        if target_message is None:
            self.session.add(assistant_message)
        else:
            await self._delete_message_derivatives(target_message.id)
            assistant_message.content = llm_response.text
            assistant_message.token_count = llm_response.output_tokens
        await self.session.flush()

        assistant_message.meta = {
            "author": "叙事引擎",
            "time": extraction.state.time,
            "choices": response_choices,
            "consistency_check": consistency_check,
            "consistency_revision": consistency_revision,
        }
        state_snapshot = StoryStateSnapshot(
            story_id=story.id,
            branch_id=branch.id,
            message_id=assistant_message.id,
            state={
                "location": extraction.state.location,
                "time": extraction.state.time,
                "mood": extraction.state.mood,
                "objective": extraction.state.objective,
                "inventory": extraction.state.inventory,
                "open_threads": extraction.state.open_threads,
                "relationships": extraction.relationships,
            },
        )
        self.session.add(state_snapshot)
        added_memories = self._add_prepared_memories(
            story,
            branch,
            assistant_message.id,
            prepared_memories,
            extraction.source,
        )
        self._add_prepared_canon_facts(
            story,
            branch,
            assistant_message.id,
            prepared_canon_facts,
            extraction.source,
        )

        model_call_id = await self._ensure_primary_model_call(
            story,
            llm_request,
            llm_response,
            generation_request.purpose,
        )
        updated_memories = self._merge_memory_results(
            context.preview.get("sections", {}).get("retrieved_memories", []),
            added_memories,
        )
        updated_canon_facts = await self._load_canon_facts(story.id, branch.id)
        response = ChatResponse(
            message_id=str(assistant_message.id),
            content=llm_response.text,
            story_state=extraction.state,
            retrieved_memories=updated_memories,
            canon_facts=updated_canon_facts,
            choices=response_choices,
            model_call={
                "id": model_call_id,
                "provider": llm_response.provider,
                "model": llm_response.model,
                "purpose": generation_request.purpose,
                "latency_ms": llm_response.latency_ms,
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
                "cost_estimate": llm_response.cost_estimate,
                "dry_run": llm_response.raw.get("dry_run", False),
                "consistency_check": consistency_check,
                "consistency_revision": consistency_revision,
            },
            idempotency_key=generation.idempotency_key,
            branch_version=generation.expected_branch_version + 1,
        )
        await self._complete_generation(generation, branch, assistant_message, response)
        await self.session.commit()
        return response

    async def stream(self, request: ChatRequest) -> AsyncIterator[dict]:
        story_id = self._parse_uuid(request.story_id, DEFAULT_STORY_ID)
        story = await self._get_story(story_id)
        branch_id = self._parse_uuid(request.branch_id, story.current_branch_id or DEFAULT_BRANCH_ID)
        branch = await self._get_branch(story.id, branch_id)
        try:
            generation, replay = await self._claim_generation(request, story, branch)
        except HTTPException as error:
            yield {"type": "error", "status": error.status_code, "detail": error.detail}
            return
        if replay is not None:
            yield {"type": "start", "replayed": True}
            yield {"type": "done", "response": replay.model_dump()}
            return
        self._begin_audit_turn(story.id)

        user_message = Message(
            story_id=story.id,
            branch_id=branch.id,
            role="user",
            content=request.message,
            meta={"author": "你"},
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(user_message)
        await self.session.flush()
        generation.user_message_id = user_message.id
        await self.session.commit()

        state, relationships, context = await self._assemble_context(
            story,
            branch,
            request,
            recent_exclude_message_ids={user_message.id},
        )
        prompt_messages = context.prompt_messages
        await self.session.commit()

        if request.provider and request.model:
            option = get_model(request.model)
            llm_request = LLMRequest(
                provider=request.provider,
                model=request.model,
                messages=prompt_messages,
                purpose=request.purpose,
                max_output_tokens=request.max_output_tokens
                or (option.default_max_output_tokens if option else 2400),
                temperature=option.temperature if option else 0.82,
                top_p=option.top_p if option else 0.92,
                reasoning_effort=option.reasoning_effort if option else None,
                stream=True,
            )
        else:
            llm_request = self.llm_gateway.request_for_purpose(request.purpose, prompt_messages)
            llm_request = llm_request.model_copy(update={"stream": True})

        llm_request = self.llm_gateway.normalize_request(llm_request)
        started = time.perf_counter()
        chunks: list[str] = []
        delivered_text = ""
        stream_message: Message | None = None
        last_checkpoint_at = 0.0
        last_checkpoint_characters = 0
        yield {
            "type": "start",
            "provider": llm_request.provider,
            "model": llm_request.model,
            "purpose": llm_request.purpose,
        }

        try:
            async for chunk in self.llm_gateway.stream(llm_request):
                chunks.append(chunk)
                visible_text = visible_stream_story_text("".join(chunks))
                delta = visible_text[len(delivered_text) :]
                if not delta:
                    continue
                delivered_text = visible_text
                now = time.monotonic()
                should_checkpoint = self._should_checkpoint_stream(
                    has_checkpoint=stream_message is not None,
                    current_characters=len(visible_text),
                    checkpoint_characters=last_checkpoint_characters,
                    now=now,
                    checkpoint_at=last_checkpoint_at,
                    character_threshold=self.llm_gateway.settings.stream_checkpoint_characters,
                    time_threshold=self.llm_gateway.settings.stream_checkpoint_seconds,
                )
                if should_checkpoint:
                    stream_message = await self._save_stream_partial(
                        story,
                        branch,
                        stream_message,
                        visible_text,
                    )
                    last_checkpoint_at = now
                    last_checkpoint_characters = len(visible_text)
                yield {"type": "delta", "content": delta}
        except asyncio.CancelledError:
            partial_text = visible_stream_story_text("".join(chunks)).strip()
            with anyio.CancelScope(shield=True):
                with suppress(Exception):
                    await self.session.rollback()
                if partial_text:
                    with suppress(Exception):
                        await self._persist_partial_stream(
                            story,
                            branch,
                            llm_request,
                            partial_text,
                            int((time.perf_counter() - started) * 1000),
                            stream_message,
                        )
            raise

        raw_response_text = "".join(chunks)
        response_content, response_choices = split_story_response(
            raw_response_text,
            story.interaction_mode or "choices",
        )
        response_choices = await self._ensure_story_choices(
            story.interaction_mode or "choices",
            response_content,
            response_choices,
            context,
        )
        remaining_text = response_content[len(delivered_text) :]
        if remaining_text:
            stream_message = await self._save_stream_partial(
                story,
                branch,
                stream_message,
                response_content,
            )
            yield {"type": "delta", "content": remaining_text}
        final_content, consistency_check, consistency_revision = await self._apply_consistency_policy(
            response_content,
            state,
            context,
            story.consistency_mode or "auto",
        )
        if final_content != response_content:
            response_content = final_content
            stream_message = await self._save_stream_partial(
                story,
                branch,
                stream_message,
                response_content,
            )
            yield {"type": "replace", "content": response_content}
        llm_response = LLMResponse(
            provider=self.llm_gateway.last_stream_provider or llm_request.provider,
            model=self.llm_gateway.last_stream_model or llm_request.model,
            text=response_content,
            raw={"stream": True, "dry_run": False},
            latency_ms=int((time.perf_counter() - started) * 1000),
            call_id=self.llm_gateway.last_stream_call_id,
            cost_estimate=self.llm_gateway.last_stream_cost_estimate,
        )
        response = await self._persist_completed_stream(
            story,
            branch,
            request,
            state,
            relationships,
            context,
            llm_request,
            llm_response,
            stream_message,
            response_choices,
            consistency_check,
            consistency_revision,
            generation,
        )
        yield {"type": "done", "response": response.model_dump()}

    async def preview_context(self, request: ChatRequest) -> dict:
        story_id = self._parse_uuid(request.story_id, DEFAULT_STORY_ID)
        story = await self._get_story(story_id)
        self._begin_audit_turn(story.id)
        branch_id = self._parse_uuid(request.branch_id, story.current_branch_id or DEFAULT_BRANCH_ID)
        branch = await self._get_branch(story.id, branch_id)
        _, _, context = await self._assemble_context(story, branch, request)
        return {
            "story_id": str(story.id),
            "branch_id": str(branch.id),
            "purpose": request.purpose,
            **context.preview,
        }

    async def _prepare_generation_command(
        self,
        request: ChatRequest,
        story: Story,
        branch: StoryBranch,
    ) -> tuple[Message | None, str, ChatRequest]:
        if request.command is None:
            return None, request.message, request

        target_id = self._parse_uuid(request.target_message_id, uuid4())
        target = await self.session.get(Message, target_id)
        if (
            target is None
            or target.story_id != story.id
            or target.branch_id != branch.id
            or target.role != "assistant"
        ):
            raise HTTPException(status_code=404, detail="Assistant message not found")

        result = await self.session.execute(
            select(Message)
            .where(Message.story_id == story.id, Message.branch_id == branch.id)
            .order_by(
                Message.created_at.asc(),
                case((Message.role == "user", 0), (Message.role == "assistant", 1), else_=2),
                Message.id.asc(),
            )
        )
        messages = list(result.scalars().all())
        target_index = next(
            (index for index, message in enumerate(messages) if message.id == target.id),
            -1,
        )
        source_user = next(
            (message for message in reversed(messages[:target_index]) if message.role == "user"),
            None,
        )
        if source_user is None:
            raise HTTPException(status_code=409, detail="No user prompt precedes this reply")

        if request.command == "regenerate":
            prompt = (
                f"{source_user.content}\n\n"
                "请重新生成这次回复。采用不同但同样合理的叙事路径，不解释重试过程。"
            )
        else:
            instruction = request.message.strip() or "提升文笔、节奏与画面感，保持事实和情节不变"
            prompt = (
                "请重写下面这段助手回复，只输出重写后的小说正文。\n"
                f"用户原始指令：{source_user.content}\n"
                f"重写要求：{instruction}\n"
                f"原回复：{target.content}"
            )
        return (
            target,
            source_user.content,
            request.model_copy(
                update={
                    "message": prompt,
                    "command": None,
                    "target_message_id": None,
                    "stream": False,
                }
            ),
        )

    async def _delete_message_derivatives(self, message_id: UUID) -> None:
        await self.session.execute(
            delete(StoryStateSnapshot).where(StoryStateSnapshot.message_id == message_id)
        )
        await self.session.execute(
            delete(MemoryItem).where(MemoryItem.source_message_id == message_id)
        )
        await self.session.execute(
            delete(CanonFact).where(CanonFact.source_message_id == message_id)
        )

    async def _assemble_context(
        self,
        story: Story,
        branch: StoryBranch,
        request: ChatRequest,
        exclude_message_id: UUID | None = None,
        recent_exclude_message_ids: set[UUID] | None = None,
    ) -> tuple[StoryState, list[dict], ContextAssembly]:
        state = await self._load_state(story.id, branch.id, exclude_message_id)
        relationships = await self._load_relationships(story.id, branch.id, exclude_message_id)
        memories = await self._load_memories(story.id, branch.id, request.message)
        canon_facts = await self._load_canon_facts(story.id, branch.id)
        world_context = await self._load_world_context(story)
        character_context = await self._load_character_context(story)
        preferences = await self._load_user_preferences(story.user_id)
        summary = await self._load_latest_summary(story.id, branch.id)
        recent_exclusions = set(recent_exclude_message_ids or ())
        if exclude_message_id is not None:
            recent_exclusions.add(exclude_message_id)
        recent_messages = await self._load_recent_messages(
            story.id,
            branch.id,
            recent_exclusions,
            summary.to_message_id if summary else None,
        )
        context = assemble_story_context(
            request.message,
            state,
            memories,
            canon_facts,
            world_context,
            character_context,
            preferences,
            story.custom_prompt or "",
            story.interaction_mode or "choices",
            recent_messages,
            summary.content if summary else "",
        )
        return state, relationships, context

    def _check_consistency(self, response_text: str, state: StoryState, context: ContextAssembly) -> dict:
        sections = context.preview.get("sections", {})
        return check_response_consistency(
            response_text,
            state,
            sections.get("canon_facts", []),
            sections.get("character", {}),
            sections.get("world", {}),
        )

    async def _ensure_story_choices(
        self,
        interaction_mode: str,
        response_text: str,
        choices: list[str],
        context: ContextAssembly,
    ) -> list[str]:
        if interaction_mode != "choices" or len(choices) >= 2:
            return choices
        sections = context.preview.get("sections", {})
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是互动小说选项编辑。根据已经完成的正文生成 3 个简短、具体、互斥的下一步行动选项。"
                    "选项必须由用户作出决定，不得替用户执行，不得包含自定义、Custom、Other。"
                    "只返回 JSON 对象：{\"choices\":[\"...\",\"...\",\"...\"]}。"
                ),
            ),
            ChatMessage(
                role="developer",
                content=(
                    f"用户偏好：{sections.get('user_preferences', [])}\n"
                    f"小说 Prompt：{sections.get('story_prompt', '')}\n"
                    f"当前状态：{sections.get('state', {})}"
                ),
            ),
            ChatMessage(role="user", content=f"正文：\n{response_text[-5000:]}"),
        ]
        request = self.llm_gateway.request_for_purpose("normal_chat", messages).model_copy(
            update={
                "max_output_tokens": 500,
                "temperature": 0.55,
                "top_p": 0.88,
                "response_format": "json",
                "stream": False,
            }
        )
        try:
            response = await self.llm_gateway.generate(
                self.llm_gateway.normalize_request(request)
            )
            return _parse_story_choices(response.text)
        except Exception:
            return []

    async def _apply_consistency_policy(
        self,
        response_text: str,
        state: StoryState,
        context: ContextAssembly,
        mode: str,
    ) -> tuple[str, dict, dict]:
        if mode == "off":
            check = {"status": "off", "issue_count": 0, "issues": []}
            return response_text, check, {
                "attempted": False,
                "accepted": False,
                "reason": "checking_disabled",
            }

        initial_check = self._check_consistency(response_text, state, context)
        if mode != "auto" or initial_check["status"] != "fail":
            return response_text, initial_check, {
                "attempted": False,
                "accepted": False,
                "reason": "manual_review" if initial_check["status"] == "fail" else "check_passed",
            }

        revision_request = self.llm_gateway.request_for_purpose(
            "consistency_check",
            self._build_consistency_revision_messages(response_text, initial_check, context),
        )
        revision_request = self.llm_gateway.normalize_request(
            revision_request.model_copy(
                update={
                    "max_output_tokens": min(max(revision_request.max_output_tokens, 1024), 4096),
                    "temperature": min(revision_request.temperature, 0.35),
                    "top_p": min(revision_request.top_p, 0.85),
                    "stream": False,
                }
            )
        )
        try:
            revised_response = await self.llm_gateway.generate(revision_request)
        except Exception:
            return response_text, initial_check, {
                "attempted": True,
                "accepted": False,
                "reason": "revision_failed",
                "provider": revision_request.provider,
                "model": revision_request.model,
                "initial_check": initial_check,
            }
        revised_text = revised_response.text.strip()
        revised_check = self._check_consistency(revised_text, state, context)
        accepted = bool(revised_text) and revised_check["issue_count"] <= initial_check["issue_count"]
        return (
            revised_text if accepted else response_text,
            revised_check if accepted else initial_check,
            {
                "attempted": True,
                "accepted": accepted,
                "reason": "accepted_revision" if accepted else "kept_original",
                "provider": revision_request.provider,
                "model": revision_request.model,
                "initial_check": initial_check,
            },
        )

    def _build_consistency_revision_messages(
        self,
        response_text: str,
        consistency_check: dict,
        context: ContextAssembly,
    ) -> list[ChatMessage]:
        sections = context.preview.get("sections", {})
        return [
            ChatMessage(
                role="system",
                content="你是小说连续性修订器。只输出修订后的正文，不解释修改过程，不输出 Markdown 标题。",
            ),
            ChatMessage(
                role="developer",
                content=(
                    "保留原文的叙事风格、段落节奏和剧情意图，仅修复列出的参数、人物、剧情或世界设定冲突。\n"
                    f"冲突：{consistency_check['issues']}\n"
                    f"场景状态：{sections.get('state', {})}\n"
                    f"角色档案：{sections.get('character', {})}\n"
                    f"世界规则：{sections.get('world', {})}\n"
                    f"既定事实：{sections.get('canon_facts', [])}"
                ),
            ),
            ChatMessage(role="user", content=response_text),
        ]

    async def _save_stream_partial(
        self,
        story: Story,
        branch: StoryBranch,
        assistant_message: Message | None,
        partial_text: str,
    ) -> Message:
        if assistant_message is None:
            assistant_message = Message(
                story_id=story.id,
                branch_id=branch.id,
                role="assistant",
                content=partial_text,
                meta={"author": "叙事引擎", "partial": True, "stream": True},
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(assistant_message)
            await self.session.flush()
        else:
            assistant_message.content = partial_text
            assistant_message.meta = {"author": "叙事引擎", "partial": True, "stream": True}
        try:
            await self.session.commit()
        except asyncio.CancelledError:
            with suppress(Exception):
                await self.session.rollback()
            raise
        return assistant_message

    async def _persist_partial_stream(
        self,
        story: Story,
        branch: StoryBranch,
        llm_request: LLMRequest,
        partial_text: str,
        latency_ms: int,
        assistant_message: Message | None = None,
    ) -> None:
        if assistant_message is None:
            assistant_message = Message(
                story_id=story.id,
                branch_id=branch.id,
                role="assistant",
                content=partial_text,
                meta={"author": "叙事引擎", "partial": True, "stream": True},
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(assistant_message)
            await self.session.flush()
        else:
            assistant_message.content = partial_text
            assistant_message.meta = {"author": "叙事引擎", "partial": True, "stream": True}
        await self.session.commit()

    async def _persist_completed_stream(
        self,
        story: Story,
        branch: StoryBranch,
        request: ChatRequest,
        state,
        relationships: list[dict],
        context: ContextAssembly,
        llm_request: LLMRequest,
        llm_response: LLMResponse,
        assistant_message: Message | None = None,
        response_choices: list[str] | None = None,
        consistency_check: dict | None = None,
        consistency_revision: dict | None = None,
        generation: GenerationRequest | None = None,
    ) -> ChatResponse:
        choices = response_choices or []
        perspective_character = await self._main_character_name(story)
        await self.session.commit()
        extraction = await extract_story_updates_with_llm(
            self.llm_gateway,
            state,
            request.message,
            llm_response.text,
            relationships=relationships,
            perspective_character=perspective_character,
        )
        prepared_memories, prepared_canon_facts = await self._prepare_extracted_knowledge(
            story,
            branch,
            extraction.memories,
            extraction.canon_facts,
            entity_names=self._memory_entity_names(
                extraction.state,
                extraction.relationships,
                perspective_character,
            ),
        )

        if assistant_message is None:
            assistant_message = Message(
                story_id=story.id,
                branch_id=branch.id,
                role="assistant",
                content=llm_response.text,
                meta={"author": "叙事引擎", "time": state.time, "stream": True, "choices": choices},
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(assistant_message)
            await self.session.flush()
        else:
            assistant_message.content = llm_response.text
            assistant_message.meta = {
                "author": "叙事引擎",
                "time": state.time,
                "stream": True,
                "choices": choices,
            }

        consistency_check = consistency_check or self._check_consistency(llm_response.text, state, context)
        consistency_revision = consistency_revision or {
            "attempted": False,
            "accepted": False,
            "reason": "not_requested",
        }
        assistant_message.meta = {
            "author": "叙事引擎",
            "time": extraction.state.time,
            "stream": True,
            "choices": choices,
            "consistency_check": consistency_check,
            "consistency_revision": consistency_revision,
        }
        state_snapshot = StoryStateSnapshot(
            story_id=story.id,
            branch_id=branch.id,
            message_id=assistant_message.id,
            state={
                "location": extraction.state.location,
                "time": extraction.state.time,
                "mood": extraction.state.mood,
                "objective": extraction.state.objective,
                "inventory": extraction.state.inventory,
                "open_threads": extraction.state.open_threads,
                "relationships": extraction.relationships,
            },
        )
        self.session.add(state_snapshot)
        added_memories = self._add_prepared_memories(
            story,
            branch,
            assistant_message.id,
            prepared_memories,
            extraction.source,
        )
        self._add_prepared_canon_facts(
            story,
            branch,
            assistant_message.id,
            prepared_canon_facts,
            extraction.source,
        )

        model_call_id = await self._ensure_primary_model_call(
            story,
            llm_request,
            llm_response,
            request.purpose,
        )
        updated_memories = self._merge_memory_results(
            context.preview.get("sections", {}).get("retrieved_memories", []),
            added_memories,
        )
        updated_canon_facts = await self._load_canon_facts(story.id, branch.id)
        response = ChatResponse(
            message_id=str(assistant_message.id),
            content=llm_response.text,
            story_state=extraction.state,
            retrieved_memories=updated_memories,
            canon_facts=updated_canon_facts,
            choices=choices,
            model_call={
                "id": model_call_id,
                "provider": llm_response.provider,
                "model": llm_response.model,
                "purpose": request.purpose,
                "latency_ms": llm_response.latency_ms,
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
                "cost_estimate": llm_response.cost_estimate,
                "dry_run": False,
                "consistency_check": consistency_check,
                "consistency_revision": consistency_revision,
            },
            idempotency_key=generation.idempotency_key if generation else None,
            branch_version=(generation.expected_branch_version + 1) if generation else branch.version,
        )
        if generation is not None:
            await self._complete_generation(generation, branch, assistant_message, response)
        await self.session.commit()
        return response

    async def _claim_generation(
        self,
        request: ChatRequest,
        story: Story,
        branch: StoryBranch,
    ) -> tuple[GenerationRequest, ChatResponse | None]:
        key = request.idempotency_key or str(uuid4())
        request.idempotency_key = key
        request_hash = self._generation_request_hash(request)
        active = await self.session.scalar(
            select(GenerationRequest).where(
                GenerationRequest.branch_id == branch.id,
                GenerationRequest.status == "processing",
            )
        )
        if active is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=self.llm_gateway.settings.generation_stale_seconds
            )
            if active.updated_at is not None and active.updated_at < cutoff:
                active.status = "failed"
                active.error = "Generation lease expired before completion"
                await self.session.commit()
            elif active.idempotency_key != key:
                raise HTTPException(
                    status_code=409,
                    detail="Another generation is already active for this branch",
                )
        existing = await self.session.scalar(
            select(GenerationRequest).where(
                GenerationRequest.user_id == self.user_id,
                GenerationRequest.idempotency_key == key,
            )
        )
        if existing is not None:
            return self._resolve_existing_generation(existing, request_hash)

        expected_version = request.branch_version if request.branch_version is not None else branch.version
        if expected_version != branch.version:
            raise HTTPException(
                status_code=409,
                detail="Branch changed since it was loaded; refresh before generating again",
            )
        generation = GenerationRequest(
            user_id=self.user_id,
            story_id=story.id,
            branch_id=branch.id,
            idempotency_key=key,
            request_hash=request_hash,
            status="processing",
            expected_branch_version=expected_version,
        )
        self.session.add(generation)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(GenerationRequest).where(
                    GenerationRequest.user_id == self.user_id,
                    GenerationRequest.idempotency_key == key,
                )
            )
            if existing is not None:
                return self._resolve_existing_generation(existing, request_hash)
            raise HTTPException(
                status_code=409,
                detail="Another generation is already active for this branch",
            ) from None
        self._active_generation_id = generation.id
        return generation, None

    def _resolve_existing_generation(
        self,
        generation: GenerationRequest,
        request_hash: str,
    ) -> tuple[GenerationRequest, ChatResponse | None]:
        if generation.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was reused with a different request")
        if generation.status == "completed" and generation.response:
            return generation, ChatResponse.model_validate(generation.response)
        detail = (
            "This generation is still processing"
            if generation.status == "processing"
            else "This generation did not complete; submit a new request with a new idempotency key"
        )
        raise HTTPException(status_code=409, detail=detail)

    @staticmethod
    def _generation_request_hash(request: ChatRequest) -> str:
        payload = request.model_dump(
            mode="json",
            exclude={"idempotency_key"},
            exclude_none=True,
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _should_checkpoint_stream(
        *,
        has_checkpoint: bool,
        current_characters: int,
        checkpoint_characters: int,
        now: float,
        checkpoint_at: float,
        character_threshold: int,
        time_threshold: float,
    ) -> bool:
        return (
            not has_checkpoint
            or current_characters - checkpoint_characters >= character_threshold
            or now - checkpoint_at >= time_threshold
        )

    async def _complete_generation(
        self,
        generation: GenerationRequest,
        branch: StoryBranch,
        assistant_message: Message,
        response: ChatResponse,
    ) -> None:
        result = await self.session.execute(
            update(StoryBranch)
            .where(
                StoryBranch.id == branch.id,
                StoryBranch.version == generation.expected_branch_version,
            )
            .values(version=StoryBranch.version + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Branch changed while the response was being generated",
            )
        generation.status = "completed"
        generation.assistant_message_id = assistant_message.id
        generation.response = response.model_dump(mode="json")
        generation.error = None
        self._active_generation_id = None

    async def fail_active_generation(
        self,
        error: BaseException,
        *,
        cancelled: bool = False,
    ) -> None:
        generation_id = self._active_generation_id
        if generation_id is None:
            return
        with suppress(Exception):
            await self.session.rollback()
            message = str(error).strip() or error.__class__.__name__
            await self.session.execute(
                update(GenerationRequest)
                .where(
                    GenerationRequest.id == generation_id,
                    GenerationRequest.status == "processing",
                )
                .values(
                    status="cancelled" if cancelled else "failed",
                    error=f"{error.__class__.__name__}: {message}"[:1000],
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.commit()
        self._active_generation_id = None

    async def _get_story(self, story_id: UUID) -> Story:
        result = await self.session.execute(
            select(Story).where(Story.id == story_id, Story.user_id == self.user_id).limit(1)
        )
        story = result.scalar_one_or_none()
        if story is not None:
            return story

        raise HTTPException(status_code=404, detail="Story not found")

    def _begin_audit_turn(self, story_id: UUID) -> None:
        self.turn_context = TurnContext()
        auditor = getattr(self.llm_gateway, "auditor", None)
        if auditor is not None:
            auditor.begin_turn(story_id)

    async def _ensure_primary_model_call(
        self,
        story: Story,
        llm_request: LLMRequest,
        llm_response: LLMResponse,
        purpose: str,
    ) -> str:
        if llm_response.call_id:
            return llm_response.call_id

        model_call = ModelCall(
            user_id=story.user_id,
            story_id=story.id,
            provider=llm_response.provider,
            model=llm_response.model,
            purpose=purpose,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=llm_response.latency_ms,
            request={
                "provider": llm_request.provider,
                "model": llm_request.model,
                "purpose": llm_request.purpose,
                "max_output_tokens": llm_request.max_output_tokens,
                "temperature": llm_request.temperature,
                "top_p": llm_request.top_p,
                "stream": llm_request.stream,
            },
            response={
                "output_characters": len(llm_response.text),
                "dry_run": llm_response.raw.get("dry_run", False),
            },
        )
        self.session.add(model_call)
        await self.session.flush()
        return str(model_call.id)

    async def _get_branch(self, story_id: UUID, branch_id: UUID) -> StoryBranch:
        branch = await self.session.get(StoryBranch, branch_id)
        if branch is not None and branch.story_id == story_id:
            return branch

        result = await self.session.execute(
            select(StoryBranch).where(StoryBranch.story_id == story_id).order_by(StoryBranch.created_at.asc()).limit(1)
        )
        fallback = result.scalar_one_or_none()
        if fallback is None:
            fallback = StoryBranch(id=uuid4(), story_id=story_id, name="main")
            self.session.add(fallback)
            await self.session.flush()
        return fallback

    async def _load_state(
        self,
        story_id: UUID,
        branch_id: UUID,
        exclude_message_id: UUID | None = None,
    ) -> StoryState:
        snapshot_state = await self._load_snapshot_state(
            story_id,
            branch_id,
            exclude_message_id,
        )
        if snapshot_state is None:
            return StoryState()
        return StoryState(
            location=snapshot_state.get("location", "未知地点"),
            time=snapshot_state.get("time", "未知时间"),
            mood=snapshot_state.get("mood", "未定义"),
            objective=snapshot_state.get("objective", "继续推进剧情"),
            inventory=snapshot_state.get("inventory", []),
            open_threads=snapshot_state.get("open_threads", []),
        )

    async def _load_snapshot_state(
        self,
        story_id: UUID,
        branch_id: UUID,
        exclude_message_id: UUID | None = None,
    ) -> dict | None:
        cache_key = (story_id, branch_id, exclude_message_id)
        if cache_key in self.turn_context.snapshot_states:
            return self.turn_context.snapshot_states[cache_key]

        query = select(StoryStateSnapshot).where(
            StoryStateSnapshot.story_id == story_id,
            StoryStateSnapshot.branch_id == branch_id,
        )
        if exclude_message_id is not None:
            query = query.where(
                or_(
                    StoryStateSnapshot.message_id.is_(None),
                    StoryStateSnapshot.message_id != exclude_message_id,
                )
            )
        result = await self.session.execute(
            query
            .order_by(desc(StoryStateSnapshot.created_at))
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        snapshot_state = dict(snapshot.state) if snapshot is not None else None
        self.turn_context.snapshot_states[cache_key] = snapshot_state
        return snapshot_state

    async def _load_relationships(
        self,
        story_id: UUID,
        branch_id: UUID,
        exclude_message_id: UUID | None = None,
    ) -> list[dict]:
        snapshot_state = await self._load_snapshot_state(
            story_id,
            branch_id,
            exclude_message_id,
        )
        if snapshot_state is None:
            return []
        relationships = snapshot_state.get("relationships", [])
        return relationships if isinstance(relationships, list) else []

    async def _load_memories(self, story_id: UUID, branch_id: UUID, query: str | None = None) -> list[str]:
        normalized_query = (query or "").strip()
        cache_key = (story_id, branch_id, normalized_query)
        cached = self.turn_context.memory_results.get(cache_key)
        if cached is not None:
            return list(cached)

        result = await self.session.execute(
            select(MemoryItem)
            .where(
                MemoryItem.story_id == story_id,
                MemoryItem.branch_id == branch_id,
                MemoryItem.is_active.is_(True),
            )
            .order_by(desc(MemoryItem.importance), desc(MemoryItem.updated_at))
            .limit(MEMORY_CANDIDATE_LIMIT)
        )
        memories = list(result.scalars().all())
        if not memories:
            selected: list[str] = []
        elif not normalized_query:
            selected = [item.content for item in memories[:MEMORY_RESULT_LIMIT]]
        else:
            threshold = getattr(
                getattr(self.embedding_service, "settings", None),
                "memory_vector_search_min_items",
                MEMORY_VECTOR_SEARCH_MIN_ITEMS,
            )
            compatible_candidates = any(
                self.embedding_service.is_model_version_compatible(
                    model=memory.embedding_model,
                    version=memory.embedding_version,
                )
                for memory in memories
            )
            query_embedding = (
                await self._embed_query_once(normalized_query)
                if len(memories) > threshold and compatible_candidates
                else []
            )
            recency_scores = self._memory_recency_scores(memories)
            ranked = []
            for index, memory in enumerate(memories):
                semantic_score = (
                    cosine_similarity(query_embedding, memory.embedding)
                    if query_embedding
                    and self.embedding_service.is_compatible(
                        model=memory.embedding_model,
                        dimensions=memory.embedding_dimensions,
                        version=memory.embedding_version,
                        vector=query_embedding,
                    )
                    else 0.0
                )
                keyword_score = self._memory_keyword_score(normalized_query, memory.content)
                entity_score = self._memory_entity_score(
                    normalized_query,
                    memory.entity_tags or [],
                )
                importance_score = min(1.0, max(0.0, float(memory.importance or 0) / 10))
                score = (
                    semantic_score * 0.55
                    + keyword_score * 0.30
                    + entity_score * 0.20
                    + importance_score * 0.20
                    + recency_scores[index] * 0.05
                )
                ranked.append((score, -index, memory))
            ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
            selected = [memory.content for _, _, memory in ranked[:MEMORY_RESULT_LIMIT]]

        self.turn_context.memory_results[cache_key] = tuple(selected)
        return selected

    @staticmethod
    def _memory_search_terms(value: str) -> set[str]:
        normalized = value.casefold()
        terms = set(re.findall(r"[a-z0-9_]{2,}", normalized))
        for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
            if len(segment) == 1:
                terms.add(segment)
            for size in (2, 3):
                terms.update(
                    segment[index : index + size]
                    for index in range(max(0, len(segment) - size + 1))
                )
        return terms

    @classmethod
    def _memory_keyword_score(cls, query: str, content: str) -> float:
        query_terms = cls._memory_search_terms(query)
        if not query_terms:
            return 0.0
        content_terms = cls._memory_search_terms(content)
        return len(query_terms & content_terms) / len(query_terms)

    @classmethod
    def _memory_entity_score(cls, query: str, entity_tags: list) -> float:
        normalized_query = re.sub(r"[^\w]+", "", query.casefold())
        query_terms = cls._memory_search_terms(query)
        matched = 0
        valid_tags = [str(tag).strip() for tag in entity_tags if str(tag).strip()]
        for tag in valid_tags:
            normalized_tag = re.sub(r"[^\w]+", "", tag.casefold())
            if (
                (
                    bool(normalized_query and normalized_tag)
                    and (
                        normalized_query in normalized_tag
                        or normalized_tag in normalized_query
                    )
                )
                or query_terms & cls._memory_search_terms(tag)
            ):
                matched += 1
        return matched / len(valid_tags) if valid_tags else 0.0

    @staticmethod
    def _memory_recency_scores(memories: list[MemoryItem]) -> list[float]:
        timestamps = [
            updated_at.timestamp() if (updated_at := getattr(memory, "updated_at", None)) else None
            for memory in memories
        ]
        dated = [timestamp for timestamp in timestamps if timestamp is not None]
        oldest = min(dated) if dated else None
        newest = max(dated) if dated else None
        scores: list[float] = []
        for memory, timestamp in zip(memories, timestamps, strict=True):
            if timestamp is not None and oldest is not None and newest is not None and newest > oldest:
                scores.append((timestamp - oldest) / (newest - oldest))
            else:
                scores.append(min(1.0, max(0.0, float(memory.recency_score or 0))))
        return scores

    async def _embed_query_once(self, query: str) -> list[float]:
        normalized = query.strip()
        if not normalized:
            return []
        turn_context = getattr(self, "turn_context", None)
        if turn_context is None:
            turn_context = TurnContext()
            self.turn_context = turn_context
        cache = turn_context.query_embeddings
        if normalized not in cache:
            cache[normalized] = await self.embedding_service.embed(
                normalized,
                purpose="embedding_query",
            )
        else:
            record_cache_hit = getattr(self.embedding_service, "record_cache_hit", None)
            if record_cache_hit is not None:
                await record_cache_hit(
                    normalized,
                    cache[normalized],
                    purpose="embedding_query",
                )
        return cache[normalized]

    async def _load_canon_facts(self, story_id: UUID, branch_id: UUID) -> list[str]:
        result = await self.session.execute(
            select(CanonFact)
            .where(
                CanonFact.story_id == story_id,
                CanonFact.branch_id == branch_id,
                CanonFact.is_active.is_(True),
            )
            .order_by(
                case((CanonFact.fact_type == "llm_state_extraction", 0), else_=1),
                desc(CanonFact.importance),
                desc(CanonFact.created_at),
            )
            .limit(12)
        )
        return [fact.content for fact in result.scalars().all()]

    async def _prepare_extracted_knowledge(
        self,
        story: Story,
        branch: StoryBranch,
        memories: list[str],
        canon_facts: list[str],
        *,
        entity_names: list[str] | None = None,
    ) -> tuple[list[PreparedMemory], list[str]]:
        recent_memories = (
            await self._load_recent_memory_candidates(story.id, branch.id) if memories else []
        )
        comparison_memories: list[tuple[str, tuple[str, ...], MemoryItem | None]] = [
            (item.content, tuple(item.entity_tags or []), item) for item in recent_memories
        ]
        pending_memories: list[tuple[str, int, tuple[str, ...]]] = []
        for raw_memory in memories:
            memory = self._normalize_memory_text(raw_memory)
            entity_tags = self._memory_entity_tags(memory, entity_names or [])
            importance = self._memory_importance(memory, entity_tags)
            if importance < MEMORY_ACCEPTANCE_THRESHOLD:
                continue
            duplicate = next(
                (
                    existing
                    for existing_content, existing_entities, existing in comparison_memories
                    if self._memory_is_near_duplicate(
                        memory,
                        entity_tags,
                        existing_content,
                        existing_entities,
                    )
                ),
                None,
            )
            if duplicate is not None:
                self._refresh_duplicate_memory(duplicate, importance, entity_tags)
                continue
            if any(
                existing is None
                and self._memory_is_near_duplicate(
                    memory,
                    entity_tags,
                    existing_content,
                    existing_entities,
                )
                for existing_content, existing_entities, existing in comparison_memories
            ):
                continue
            if await self._memory_exists(story.id, branch.id, memory):
                continue
            pending_memories.append((memory, importance, entity_tags))
            comparison_memories.append((memory, entity_tags, None))

        pending_facts: list[str] = []
        for fact in canon_facts:
            if await self._canon_fact_exists(story.id, branch.id, fact):
                continue
            if fact not in pending_facts:
                pending_facts.append(fact)

        await self.session.commit()
        embeddings = (
            await self.embedding_service.embed_many(
                [memory for memory, _, _ in pending_memories],
                purpose="embedding_memory",
            )
            if pending_memories
            else []
        )
        prepared_memories: list[PreparedMemory] = []
        for (memory, importance, entity_tags), embedding in zip(
            pending_memories,
            embeddings,
            strict=True,
        ):
            metadata = self.embedding_service.metadata(memory, embedding)
            prepared_memories.append(
                PreparedMemory(
                    content=memory,
                    importance=importance,
                    entity_tags=entity_tags,
                    embedding=embedding,
                    embedding_model=metadata.model,
                    embedding_dimensions=metadata.dimensions,
                    embedding_version=metadata.version,
                    content_hash=metadata.content_hash,
                    embedded_at=metadata.embedded_at,
                )
            )
        return prepared_memories, pending_facts

    async def _load_recent_memory_candidates(
        self,
        story_id: UUID,
        branch_id: UUID,
    ) -> list[MemoryItem]:
        result = await self.session.execute(
            select(MemoryItem)
            .where(
                MemoryItem.story_id == story_id,
                MemoryItem.branch_id == branch_id,
                MemoryItem.is_active.is_(True),
            )
            .order_by(desc(MemoryItem.updated_at))
            .limit(MEMORY_CANDIDATE_LIMIT)
        )
        return list(result.scalars().all())

    @staticmethod
    def _memory_entity_names(
        state: StoryState,
        relationships: list[dict],
        perspective_character: str | None,
    ) -> list[str]:
        names: list[str] = []
        for value in [
            perspective_character,
            *state.inventory,
            *(relationship.get("from") for relationship in relationships),
            *(relationship.get("to") for relationship in relationships),
        ]:
            cleaned = str(value or "").strip()
            if len(cleaned) >= 2 and cleaned not in names:
                names.append(cleaned)
        return names

    @staticmethod
    def _normalize_memory_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip(" \t\r\n，。！？；：,.!?;:\"'`*-")

    @staticmethod
    def _memory_entity_tags(content: str, entity_names: list[str]) -> tuple[str, ...]:
        normalized = content.casefold()
        return tuple(
            entity
            for entity in entity_names
            if entity.casefold() in normalized
        )

    @staticmethod
    def _memory_importance(content: str, entity_tags: tuple[str, ...]) -> int:
        if not content:
            return 0
        normalized = content.casefold()
        importance = 1
        if len(content) >= 16:
            importance += 1
        if entity_tags:
            importance += 2
        if any(marker in normalized for marker in MEMORY_EVENT_MARKERS):
            importance += 3
        if any(marker in normalized for marker in MEMORY_CONSEQUENCE_MARKERS):
            importance += 1
        return min(importance, 10)

    @staticmethod
    def _memory_is_near_duplicate(
        content: str,
        entity_tags: tuple[str, ...],
        existing_content: str,
        existing_entities: tuple[str, ...],
    ) -> bool:
        normalized = re.sub(r"[^\w]+", "", content.casefold())
        existing_normalized = re.sub(r"[^\w]+", "", existing_content.casefold())
        if not normalized or not existing_normalized:
            return False
        if entity_tags and existing_entities and set(entity_tags).isdisjoint(existing_entities):
            return False
        if normalized == existing_normalized:
            return True
        return (
            SequenceMatcher(None, normalized, existing_normalized).ratio()
            >= MEMORY_DUPLICATE_SIMILARITY
        )

    @staticmethod
    def _refresh_duplicate_memory(
        existing: MemoryItem,
        importance: int,
        entity_tags: tuple[str, ...],
    ) -> None:
        existing.importance = max(int(existing.importance or 0), importance)
        existing.entity_tags = list(dict.fromkeys([*(existing.entity_tags or []), *entity_tags]))
        existing.recency_score = 1.0

    def _add_prepared_memories(
        self,
        story: Story,
        branch: StoryBranch,
        source_message_id: UUID,
        memories: list[PreparedMemory],
        source: str,
    ) -> list[str]:
        for memory in memories:
            self.session.add(
                MemoryItem(
                    user_id=story.user_id,
                    story_id=story.id,
                    branch_id=branch.id,
                    character_id=story.main_character_id,
                    memory_type=f"{source}_state_extraction",
                    content=memory.content,
                    importance=memory.importance,
                    entity_tags=list(memory.entity_tags),
                    meta={"source": f"{source}_state_extractor"},
                    embedding=memory.embedding,
                    embedding_model=memory.embedding_model,
                    embedding_dimensions=memory.embedding_dimensions,
                    embedding_version=memory.embedding_version,
                    content_hash=memory.content_hash,
                    embedded_at=memory.embedded_at,
                    source_message_id=source_message_id,
                    is_active=True,
                )
            )
        return [memory.content for memory in memories]

    @staticmethod
    def _merge_memory_results(existing: list[str], added: list[str]) -> list[str]:
        merged: list[str] = []
        for memory in [*added, *existing]:
            if memory and memory not in merged:
                merged.append(memory)
            if len(merged) == MEMORY_RESULT_LIMIT:
                break
        return merged

    def _add_prepared_canon_facts(
        self,
        story: Story,
        branch: StoryBranch,
        source_message_id: UUID,
        facts: list[str],
        source: str,
    ) -> None:
        for fact in facts:
            self.session.add(
                CanonFact(
                    story_id=story.id,
                    branch_id=branch.id,
                    character_id=story.main_character_id,
                    fact_type=f"{source}_state_extraction",
                    content=fact,
                    importance=6,
                    source_message_id=source_message_id,
                    is_active=True,
                )
            )

    async def _memory_exists(self, story_id: UUID, branch_id: UUID, content: str) -> bool:
        result = await self.session.execute(
            select(MemoryItem.id)
            .where(
                MemoryItem.story_id == story_id,
                MemoryItem.branch_id == branch_id,
                or_(
                    MemoryItem.content_hash == embedding_content_hash(content),
                    MemoryItem.content_hash.is_(None),
                ),
                MemoryItem.content == content,
                MemoryItem.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _canon_fact_exists(self, story_id: UUID, branch_id: UUID, content: str) -> bool:
        result = await self.session.execute(
            select(CanonFact.id)
            .where(
                CanonFact.story_id == story_id,
                CanonFact.branch_id == branch_id,
                CanonFact.content == content,
                CanonFact.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _load_world_context(self, story: Story) -> dict:
        if story.world_id is None:
            return {}
        world = await self.session.get(World, story.world_id)
        if world is None:
            return {}
        return {
            "name": world.name,
            "description": world.description or "",
            "genre": world.genre or "",
            "rules": world.rules,
        }

    async def _load_character_context(self, story: Story) -> dict:
        if story.main_character_id is None:
            return {}
        character = await self.session.get(Character, story.main_character_id)
        if character is None:
            return {}
        persona = character.persona or {}
        return {
            "name": character.name,
            "identity": persona.get("identity", character.description or ""),
            "personality": persona.get("personality", ["冷静", "戒备", "慢热"]),
            "goal": persona.get("goal", ""),
            "secret": persona.get("secret", ""),
            "speaking_style": character.speaking_style.get("tone", ""),
            "relationship": character.relationship_to_user.get("status", ""),
        }

    async def _load_user_preferences(self, user_id: UUID) -> list[str]:
        result = await self.session.execute(
            select(UserPreference)
            .where(UserPreference.user_id == user_id, UserPreference.is_active.is_(True))
            .order_by(desc(UserPreference.strength), UserPreference.created_at.asc())
            .limit(8)
        )
        return [preference.content for preference in result.scalars().all()]

    async def _load_recent_messages(
        self,
        story_id: UUID,
        branch_id: UUID,
        exclude_message_ids: set[UUID] | None = None,
        after_message_id: UUID | None = None,
    ) -> list[dict]:
        query = select(Message).where(Message.story_id == story_id, Message.branch_id == branch_id)
        if exclude_message_ids:
            query = query.where(Message.id.notin_(exclude_message_ids))
        if after_message_id is not None:
            covered_message = await self.session.get(Message, after_message_id)
            if covered_message is not None:
                query = query.where(
                    or_(
                        Message.created_at > covered_message.created_at,
                        and_(
                            Message.created_at == covered_message.created_at,
                            Message.id > covered_message.id,
                        ),
                    )
                )
        result = await self.session.execute(
            query
            .order_by(
                desc(Message.created_at),
                desc(Message.id),
            )
            .limit(10)
        )
        messages = list(reversed(result.scalars().all()))
        return [{"role": message.role, "content": message.content} for message in messages]

    async def _load_latest_summary(self, story_id: UUID, branch_id: UUID) -> StorySummary | None:
        result = await self.session.execute(
            select(StorySummary)
            .where(StorySummary.story_id == story_id, StorySummary.branch_id == branch_id)
            .order_by(desc(StorySummary.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _main_character_name(self, story: Story) -> str | None:
        if story.main_character_id is None:
            return None
        character = await self.session.get(Character, story.main_character_id)
        return character.name if character is not None else None

    @staticmethod
    def _parse_uuid(value: str | UUID | None, fallback: UUID) -> UUID:
        if isinstance(value, UUID):
            return value
        if not value:
            return fallback
        try:
            return UUID(value)
        except ValueError:
            return fallback
