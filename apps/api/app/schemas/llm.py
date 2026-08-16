from typing import Literal

from pydantic import BaseModel, Field


ProviderName = Literal["openai", "deepinfra"]
MessageRole = Literal["system", "developer", "user", "assistant"]
ResponseFormat = Literal["text", "json"]
StoryPurpose = Literal[
    "critical_story_generation",
    "normal_chat",
    "state_update",
    "event_extraction",
    "summary_generation",
    "consistency_check",
]


class ChatMessage(BaseModel):
    role: MessageRole
    content: str


class LLMRequest(BaseModel):
    provider: ProviderName
    model: str
    messages: list[ChatMessage]
    purpose: StoryPurpose = "normal_chat"
    max_output_tokens: int = Field(default=2400, ge=128, le=128000)
    temperature: float = Field(default=0.82, ge=0, le=2)
    top_p: float = Field(default=0.92, ge=0, le=1)
    reasoning_effort: str | None = None
    response_format: ResponseFormat = "text"
    stream: bool = False
    provider_options: dict = Field(default_factory=dict)


class LLMResponse(BaseModel):
    text: str
    provider: ProviderName
    model: str
    raw: dict = Field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    call_id: str | None = None
    cost_estimate: float | None = None


class ModelOption(BaseModel):
    provider: ProviderName
    model: str
    label: str
    family: str
    best_for: list[str]
    default_max_output_tokens: int
    hard_max_output_tokens: int
    temperature: float
    top_p: float
    reasoning_effort: str | None = None
    notes: str
