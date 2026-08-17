from dataclasses import asdict, dataclass

from app.schemas.llm import ModelOption, StoryPurpose


@dataclass(frozen=True)
class PurposeBudget:
    max_input_tokens: int
    default_output_tokens: int
    hard_output_tokens: int


MODEL_REGISTRY: list[ModelOption] = [
    ModelOption(
        provider="deepinfra",
        model="Qwen/Qwen3-Max",
        label="Qwen3-MAX",
        family="qwen",
        best_for=["normal_chat", "critical_story_generation", "summary_generation", "state_update", "event_extraction", "consistency_check"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.82,
        top_p=0.92,
        notes="Default model for Chinese prose, creation interviews, structured updates, and continuity work.",
    ),
    ModelOption(
        provider="deepinfra",
        model="Qwen/Qwen3-235B-A22B-Instruct-2507",
        label="Qwen3-235B-A22B-Instruct-2507",
        family="qwen",
        best_for=["normal_chat", "critical_story_generation", "summary_generation", "consistency_check"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.84,
        top_p=0.92,
        notes="Large Qwen instruct model for Chinese prose, lore expansion, and character voice.",
    ),
    ModelOption(
        provider="deepinfra",
        model="deepseek-ai/DeepSeek-V4-Pro",
        label="DeepSeek-V4-Pro",
        family="deepseek",
        best_for=["normal_chat", "critical_story_generation", "state_update", "consistency_check"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.8,
        top_p=0.92,
        notes="DeepSeek V4 Pro endpoint for demanding prose, planning, and continuity tasks.",
    ),
    ModelOption(
        provider="openai",
        model="gpt-5.5",
        label="GPT-5.5",
        family="gpt",
        best_for=["critical_story_generation", "consistency_check", "state_update"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.78,
        top_p=0.92,
        reasoning_effort="medium",
        notes="OpenAI frontier model for high-stakes chapters, consistency checks, and long-context planning.",
    ),
    ModelOption(
        provider="deepinfra",
        model="zai-org/GLM-5.2",
        label="GLM-5.2",
        family="glm",
        best_for=["normal_chat", "state_update", "event_extraction"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.8,
        top_p=0.92,
        notes="GLM 5.2 endpoint for Chinese narrative generation and structured extraction.",
    ),
    ModelOption(
        provider="deepinfra",
        model="moonshotai/Kimi-K2.5",
        label="Kimi-K2.5",
        family="kimi",
        best_for=["normal_chat", "critical_story_generation", "summary_generation"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.82,
        top_p=0.92,
        notes="Kimi K2.5 endpoint for long-context scene development and narrative planning.",
    ),
    ModelOption(
        provider="deepinfra",
        model="anthropic/claude-fable-5",
        label="Claude Fable 5",
        family="claude",
        best_for=["normal_chat", "critical_story_generation", "consistency_check"],
        default_max_output_tokens=8192,
        hard_max_output_tokens=32768,
        temperature=0.78,
        top_p=0.92,
        notes="Claude Fable 5 endpoint for character voice, prose refinement, and continuity review.",
    ),
]


PURPOSE_DEFAULTS: dict[StoryPurpose, str] = {
    "critical_story_generation": "Qwen/Qwen3-Max",
    "normal_chat": "Qwen/Qwen3-Max",
    "state_update": "Qwen/Qwen3-Max",
    "event_extraction": "Qwen/Qwen3-Max",
    "summary_generation": "Qwen/Qwen3-Max",
    "consistency_check": "Qwen/Qwen3-Max",
}


PURPOSE_BUDGETS: dict[StoryPurpose, PurposeBudget] = {
    "critical_story_generation": PurposeBudget(16000, 4800, 8192),
    "normal_chat": PurposeBudget(10000, 2400, 4096),
    "state_update": PurposeBudget(8000, 1000, 1800),
    "event_extraction": PurposeBudget(6000, 800, 1400),
    "summary_generation": PurposeBudget(12000, 1200, 1800),
    "consistency_check": PurposeBudget(12000, 1200, 2400),
}


PURPOSE_FALLBACKS: dict[StoryPurpose, list[str]] = {
    "critical_story_generation": ["Qwen/Qwen3-235B-A22B-Instruct-2507", "gpt-5.5"],
    "normal_chat": ["Qwen/Qwen3-235B-A22B-Instruct-2507", "zai-org/GLM-5.2"],
    "state_update": ["zai-org/GLM-5.2", "gpt-5.5"],
    "event_extraction": ["zai-org/GLM-5.2"],
    "summary_generation": ["Qwen/Qwen3-235B-A22B-Instruct-2507", "moonshotai/Kimi-K2.5"],
    "consistency_check": ["Qwen/Qwen3-235B-A22B-Instruct-2507", "gpt-5.5"],
}


def list_models() -> list[ModelOption]:
    return MODEL_REGISTRY


def get_model(model: str) -> ModelOption | None:
    return next((item for item in MODEL_REGISTRY if item.model == model), None)


def choose_model(purpose: StoryPurpose) -> ModelOption:
    preferred = PURPOSE_DEFAULTS[purpose]
    model = get_model(preferred)
    if model is None:
        raise RuntimeError(f"Model registry is missing default model {preferred}")
    return model


def purpose_budget(purpose: StoryPurpose) -> PurposeBudget:
    return PURPOSE_BUDGETS[purpose]


def serialized_purpose_budgets() -> dict[StoryPurpose, dict[str, int]]:
    return {purpose: asdict(budget) for purpose, budget in PURPOSE_BUDGETS.items()}


def fallback_models(purpose: StoryPurpose, current_model: str) -> list[ModelOption]:
    return [
        option
        for model_name in PURPOSE_FALLBACKS[purpose]
        if model_name != current_model and (option := get_model(model_name)) is not None
    ]
