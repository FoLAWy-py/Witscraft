from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.llm import ProviderName, StoryPurpose


class StoryState(BaseModel):
    location: str = "未设定"
    time: str = "未设定"
    mood: str = "未设定"
    objective: str = "等待故事开始"
    inventory: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(max_length=4000)
    story_id: str
    branch_id: str | None = None
    provider: ProviderName | None = None
    model: str | None = None
    purpose: StoryPurpose = "normal_chat"
    max_output_tokens: int | None = Field(default=None, ge=128, le=128000)
    stream: bool = False
    command: Literal["regenerate", "rewrite"] | None = None
    target_message_id: str | None = None
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    branch_version: int | None = Field(default=None, ge=0)
    control_mode: Literal["player_action", "continue"] = "player_action"

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        if bool(self.provider) != bool(self.model):
            raise ValueError("provider and model must be supplied together")
        if self.command and not self.target_message_id:
            raise ValueError("target_message_id is required for message commands")
        if self.command and self.stream:
            raise ValueError("message commands use the non-streaming endpoint")
        if not self.command and not self.message.strip():
            raise ValueError("message cannot be blank")
        return self


class CreateStoryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    world_id: str | None = None
    genre: str = Field(min_length=1, max_length=120)
    world_name: str = Field(min_length=1, max_length=180)
    premise: str = Field(min_length=1, max_length=4000)
    protagonist_name: str = Field(min_length=1, max_length=180)
    protagonist_role: str = Field(min_length=1, max_length=2000)
    tone: str = Field(min_length=1, max_length=500)
    style_profile_id: str | None = None
    opening_mode: Literal["blank", "custom"] = "blank"
    opening_text: str = Field(default="", max_length=12000)
    custom_prompt: str = Field(default="", max_length=12000)
    interaction_mode: Literal["choices", "open"] = "choices"
    planned_chapter_count: int = Field(default=12, ge=3, le=120)
    target_chapter_length: int = Field(default=1800, ge=500, le=5000)
    chapter_length_unit: Literal["characters", "words"] = "characters"
    prose_language: str = Field(default="zh-CN", min_length=2, max_length=35)

    @model_validator(mode="after")
    def validate_story_setup(self) -> Self:
        required_fields = (
            "title",
            "genre",
            "world_name",
            "premise",
            "protagonist_name",
            "protagonist_role",
            "tone",
        )
        for field_name in required_fields:
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be blank")
        if self.opening_mode == "custom" and not self.opening_text.strip():
            raise ValueError("opening_text is required for a custom opening")
        if not self.prose_language.strip():
            raise ValueError("prose_language cannot be blank")
        return self


class GenerateStoryDraftRequest(BaseModel):
    title: str = Field(default="", max_length=220)
    genre: str = Field(default="", max_length=120)
    world_name: str = Field(default="", max_length=180)
    premise: str = Field(default="", max_length=4000)
    protagonist_name: str = Field(default="", max_length=180)
    protagonist_role: str = Field(default="", max_length=2000)
    tone: str = Field(default="", max_length=500)
    opening_text: str = Field(default="", max_length=12000)


class StoryInterviewDraft(GenerateStoryDraftRequest):
    style_profile_id: str | None = None
    opening_mode: Literal["blank", "custom"] = "blank"
    custom_prompt: str = Field(default="", max_length=12000)
    interaction_mode: Literal["choices", "open"] = "choices"
    planned_chapter_count: int = Field(default=12, ge=3, le=120)
    target_chapter_length: int = Field(default=1800, ge=500, le=5000)
    chapter_length_unit: Literal["characters", "words"] = "characters"
    prose_language: str = Field(default="zh-CN", min_length=2, max_length=35)


class AnalyzeStyleProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    source_type: Literal["user_owned", "licensed", "public_domain"]
    source_label: str = Field(default="", max_length=220)
    language: str = Field(default="zh-CN", min_length=2, max_length=35)
    raw_text: str = Field(min_length=500, max_length=30_000)
    rights_attested: Literal[True]

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        if not self.name.strip():
            raise ValueError("name cannot be blank")
        if len("".join(self.raw_text.split())) < 500:
            raise ValueError("reference text must contain at least 500 non-whitespace characters")
        if self.source_type in {"licensed", "public_domain"} and not self.source_label.strip():
            raise ValueError("source_label is required for licensed or public-domain text")
        return self


class StyleProfileResponse(BaseModel):
    id: str
    name: str
    source_type: str
    source_label: str | None = None
    content_hash: str
    analysis_version: str
    language: str
    features: dict
    reused: bool


class StoryInterviewMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class StoryInterviewRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    draft: StoryInterviewDraft = Field(default_factory=StoryInterviewDraft)
    history: list[StoryInterviewMessage] = Field(default_factory=list, max_length=20)


class StoryInterviewResponse(BaseModel):
    assistant_message: str = Field(min_length=1, max_length=2000)
    draft: StoryInterviewDraft
    options: list[str] = Field(default_factory=list, max_length=3)
    question_focus: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    ready_for_confirmation: bool = False


class StoryDraftResponse(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    genre: str = Field(min_length=1, max_length=120)
    world_name: str = Field(min_length=1, max_length=180)
    premise: str = Field(min_length=1, max_length=4000)
    protagonist_name: str = Field(min_length=1, max_length=180)
    protagonist_role: str = Field(min_length=1, max_length=2000)
    tone: str = Field(min_length=1, max_length=500)
    opening_text: str = Field(min_length=1, max_length=12000)


class StoryRoadmapChapterDraft(BaseModel):
    chapter_number: int = Field(ge=1, le=120)
    title: str = Field(min_length=1, max_length=220)
    objective: str = Field(min_length=1, max_length=1000)


class StoryRoadmapDraft(BaseModel):
    ending_title: str = Field(min_length=1, max_length=220)
    chapters: list[StoryRoadmapChapterDraft] = Field(min_length=3, max_length=120)


class CreateBranchRequest(BaseModel):
    name: str = Field(default="新分支", min_length=1, max_length=120)


class UpdateBranchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class UpdateStoryRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=220)
    custom_prompt: str | None = Field(default=None, max_length=12000)
    interaction_mode: Literal["choices", "open"] | None = None
    consistency_mode: Literal["manual", "auto", "off"] | None = None
    planned_chapter_count: int | None = Field(default=None, ge=3, le=120)
    branch_id: str | None = None
    roadmap_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.planned_chapter_count is not None and (
            self.branch_id is None or self.roadmap_version is None
        ):
            raise ValueError(
                "branch_id and roadmap_version are required with planned_chapter_count"
            )
        if self.planned_chapter_count is None and (
            self.branch_id is not None or self.roadmap_version is not None
        ):
            raise ValueError(
                "branch_id and roadmap_version are only valid with planned_chapter_count"
            )
        if (
            self.title is None
            and self.custom_prompt is None
            and self.interaction_mode is None
            and self.consistency_mode is None
            and self.planned_chapter_count is None
        ):
            raise ValueError("At least one story field is required")
        if self.title is not None and not self.title.strip():
            raise ValueError("title cannot be blank")
        return self


class UserPreferenceInput(BaseModel):
    preference_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z_]+$")
    content: str = Field(default="", max_length=4000)
    strength: int = Field(default=5, ge=1, le=10)


class UserPreferenceResponse(UserPreferenceInput):
    id: str


class UserPreferencesUpdateRequest(BaseModel):
    preferences: list[UserPreferenceInput] = Field(default_factory=list, max_length=12)


class UserPreferencesResponse(BaseModel):
    preferences: list[UserPreferenceResponse] = Field(default_factory=list)


class UpdateWorldRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=8000)
    genre: str = Field(default="", max_length=120)


class SetStoryWorldRequest(BaseModel):
    world_id: str


class UpdateCharacterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    role: str = Field(default="", max_length=8000)


class UpdateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    importance: int = Field(default=5, ge=1, le=10)


class UpdateCanonFactRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    importance: int = Field(default=5, ge=1, le=10)


class GenerateSummaryRequest(BaseModel):
    provider: ProviderName | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    message_id: str
    content: str
    story_state: StoryState
    retrieved_memories: list[str]
    canon_facts: list[str]
    choices: list[str] = Field(default_factory=list)
    model_call: dict
    idempotency_key: str | None = None
    branch_version: int | None = None


class WorkspaceMessage(BaseModel):
    id: str
    role: str
    content: str
    author: str | None = None
    time: str | None = None
    choices: list[str] = Field(default_factory=list)
    consistency_check: dict | None = None


class WorkspaceResponse(BaseModel):
    story_id: str
    branch_id: str
    branches: list[dict] = Field(default_factory=list)
    stories: list[dict]
    world: dict
    worlds: list[dict] = Field(default_factory=list)
    characters: list[dict]
    messages: list[WorkspaceMessage]
    story_state: StoryState
    relationships: list[dict]
    retrieved_memories: list[str]
    canon_facts: list[str]
    memory_items: list[dict] = Field(default_factory=list)
    canon_fact_items: list[dict] = Field(default_factory=list)
    summaries: list[dict] = Field(default_factory=list)
    model_call: dict | None = None
    onboarding_required: bool = False
    story_prompt: str = ""
    interaction_mode: Literal["choices", "open"] = "choices"
    consistency_mode: Literal["manual", "auto", "off"] = "auto"
    planned_chapter_count: int = 12
    minimum_planned_chapter_count: int = 3
    target_chapter_length: int = 1800
    chapter_length_unit: Literal["characters", "words"] = "characters"
    prose_language: str = "zh-CN"
    roadmap_version: int = 0
    roadmap_source: Literal["provider", "deterministic_fallback", "legacy"] = "legacy"
    ending_title: str = ""
    chapters: list[dict] = Field(default_factory=list)
