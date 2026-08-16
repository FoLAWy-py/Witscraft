from app.llm.model_registry import PURPOSE_DEFAULTS, list_models


EXPECTED_MODELS = {
    "Qwen/Qwen3-Max",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V4-Pro",
    "gpt-5.5",
    "zai-org/GLM-5.2",
    "moonshotai/Kimi-K2.5",
    "anthropic/claude-fable-5",
}


def test_requested_novel_models_are_registered() -> None:
    assert {model.model for model in list_models()} == EXPECTED_MODELS


def test_qwen3_max_is_the_default_for_every_purpose() -> None:
    assert set(PURPOSE_DEFAULTS.values()) == {"Qwen/Qwen3-Max"}
