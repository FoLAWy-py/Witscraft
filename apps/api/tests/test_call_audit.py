import asyncio

import pytest

from app.config import Settings
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway
from app.schemas.llm import ChatMessage, LLMRequest, LLMResponse
from app.services.embeddings import EmbeddingService


class CapturingAuditor(CallAuditor):
    def __init__(self, settings: Settings):
        super().__init__(settings, request_id="request-123")
        self.rows = []

    async def _persist(self, row) -> bool:
        self.rows.append(row)
        return True


class SuccessfulAdapter:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            provider=request.provider,
            model=request.model,
            text="生成结果",
            input_tokens=20,
            output_tokens=10,
            latency_ms=12,
        )


class FailingAdapter:
    async def generate(self, _request: LLMRequest) -> LLMResponse:
        raise RuntimeError("provider unavailable")


def _request(secret: str = "不要记录这段完整 Prompt") -> LLMRequest:
    return LLMRequest(
        provider="deepinfra",
        model="test-model",
        purpose="state_update",
        messages=[ChatMessage(role="user", content=secret)],
    )


def test_gateway_records_success_and_versioned_cost_without_prompt_text() -> None:
    settings = Settings(
        model_pricing={
            "deepinfra:test-model": {
                "input_per_million": 1.0,
                "output_per_million": 2.0,
            }
        },
        model_pricing_version="2026-08-test",
    )
    auditor = CapturingAuditor(settings)
    gateway = LLMGateway(settings, auditor=auditor)
    gateway.adapters["deepinfra"] = SuccessfulAdapter()

    response = asyncio.run(gateway.generate(_request()))

    assert response.call_id == str(auditor.rows[0].id)
    assert response.cost_estimate == pytest.approx(0.00004)
    row = auditor.rows[0]
    assert row.status == "succeeded"
    assert row.call_type == "llm"
    assert row.pricing_version == "2026-08-test"
    assert row.token_usage_estimated is False
    assert "不要记录这段完整 Prompt" not in str(row.request)
    assert "生成结果" not in str(row.response)


def test_gateway_records_failed_calls_before_reraising() -> None:
    settings = Settings()
    auditor = CapturingAuditor(settings)
    gateway = LLMGateway(settings, auditor=auditor)
    gateway.adapters["deepinfra"] = FailingAdapter()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(gateway.generate(_request()))

    row = auditor.rows[0]
    assert row.status == "failed"
    assert row.input_tokens is not None
    assert row.error == "RuntimeError: provider unavailable"


def test_embedding_calls_share_audit_context_and_are_free_in_dry_run() -> None:
    settings = Settings(dry_run_llm=True)
    auditor = CapturingAuditor(settings)
    service = EmbeddingService(settings, auditor=auditor)

    vectors = asyncio.run(
        service.embed_many(
            ["第一条记忆", "第二条记忆"],
            purpose="embedding_memory",
        )
    )

    assert len(vectors) == 2
    row = auditor.rows[0]
    assert row.call_type == "embedding"
    assert row.provider == "local"
    assert row.purpose == "embedding_memory"
    assert row.request["input_count"] == 2
    assert float(row.cost_estimate) == 0.0


def test_embedding_cache_hit_records_avoided_usage_at_zero_cost() -> None:
    settings = Settings(
        openai_api_key="test-key",
        model_pricing={
            "openai:text-embedding-3-large": {"embedding_per_million": 1.0}
        },
    )
    auditor = CapturingAuditor(settings)
    service = EmbeddingService(settings, auditor=auditor)

    asyncio.run(
        service.record_cache_hit(
            "重复查询",
            [0.1, 0.2],
            purpose="embedding_query",
        )
    )

    row = auditor.rows[0]
    assert row.provider == "openai"
    assert row.cache_hit is True
    assert row.input_tokens == 0
    assert row.request["avoided_input_tokens"] > 0
    assert row.response["dimensions"] == 2
    assert float(row.cost_estimate) == 0.0
