from app.llm.model_registry import (
    MODEL_ROLES,
    PURPOSE_BUDGETS,
    PURPOSE_DEFAULTS,
    list_models,
    serialized_model_roles,
)


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


def test_every_purpose_has_a_bounded_budget() -> None:
    assert set(PURPOSE_BUDGETS) == set(PURPOSE_DEFAULTS)
    for budget in PURPOSE_BUDGETS.values():
        assert budget.max_input_tokens > budget.hard_output_tokens
        assert 128 <= budget.default_output_tokens <= budget.hard_output_tokens


def test_model_roles_partition_story_purposes_and_separate_embedding() -> None:
    routed_roles = [role for role in MODEL_ROLES if role.user_configurable]
    routed_purposes = [purpose for role in routed_roles for purpose in role.purposes]
    assert len(routed_purposes) == len(set(routed_purposes))
    assert set(routed_purposes) == set(PURPOSE_DEFAULTS)

    embedding_role = next(role for role in MODEL_ROLES if role.id == "embedding")
    assert embedding_role.purposes == ()
    assert embedding_role.user_configurable is False
    assert embedding_role.configuration_source == "deployment"


def test_serialized_roles_explain_defaults_without_exposing_credentials() -> None:
    roles = serialized_model_roles(
        embedding_model="text-embedding-test",
        embedding_version="test-v2",
    )
    narrative = next(role for role in roles if role["id"] == "narrative_author")
    assert set(narrative["default_models"]) == {
        "normal_chat",
        "critical_story_generation",
    }
    embedding = next(role for role in roles if role["id"] == "embedding")
    assert embedding["deployment"] == {
        "provider": "openai",
        "model": "text-embedding-test",
        "version": "test-v2",
    }
    assert "api_key" not in str(roles).lower()
