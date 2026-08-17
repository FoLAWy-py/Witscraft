from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete

from app.config import Settings
from app.db.models import ModelCall
from app.db.session import AsyncSessionLocal
from app.logging_security import redact_sensitive_text
from app.schemas.llm import LLMRequest, LLMResponse
from app.services.token_estimator import estimate_tokens
from app.services.quota_service import ensure_quota


logger = logging.getLogger(__name__)
MILLION = Decimal("1000000")


class CallAuditor:
    def __init__(
        self,
        settings: Settings,
        *,
        user_id: UUID | None = None,
        story_id: UUID | None = None,
        request_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.user_id = user_id
        self.story_id = story_id
        self.request_id = request_id
        self.turn_id = uuid4()

    def begin_turn(self, story_id: UUID | None = None) -> UUID:
        self.story_id = story_id
        self.turn_id = uuid4()
        return self.turn_id

    async def ensure_quota(self, requested_tokens: int) -> None:
        if self.user_id is None or self.settings.dry_run_llm:
            return
        async with AsyncSessionLocal() as session:
            await ensure_quota(session, self.user_id, requested_tokens, self.settings)

    async def record_llm(
        self,
        request: LLMRequest,
        response: LLMResponse | None,
        *,
        status: str,
        latency_ms: int,
        first_token_latency_ms: int | None = None,
        error: BaseException | None = None,
        attempt: int = 1,
    ) -> tuple[str | None, float | None]:
        estimated_input = sum(estimate_tokens(message.content) for message in request.messages)
        estimated_output = estimate_tokens(response.text) if response else None
        input_tokens = response.input_tokens if response and response.input_tokens is not None else estimated_input
        output_tokens = (
            response.output_tokens
            if response and response.output_tokens is not None
            else estimated_output
        )
        usage_estimated = not response or response.input_tokens is None or response.output_tokens is None
        dry_run = bool(response and response.raw.get("dry_run", False))
        cost = self._estimate_cost(
            request.provider,
            request.model,
            input_tokens,
            output_tokens,
            dry_run=dry_run,
        )
        call_id = uuid4()
        row = ModelCall(
            id=call_id,
            user_id=self.user_id,
            story_id=self.story_id,
            turn_id=self.turn_id,
            request_id=self.request_id,
            call_type="llm",
            provider=request.provider,
            model=request.model,
            purpose=request.purpose,
            attempt=attempt,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            first_token_latency_ms=first_token_latency_ms,
            token_usage_estimated=usage_estimated,
            cache_hit=False,
            pricing_version=self.settings.model_pricing_version,
            cost_estimate=cost,
            request={
                "message_count": len(request.messages),
                "message_roles": [message.role for message in request.messages],
                "input_characters": sum(len(message.content) for message in request.messages),
                "max_output_tokens": request.max_output_tokens,
                "temperature": request.temperature,
                "top_p": request.top_p,
                "response_format": request.response_format,
                "stream": request.stream,
            },
            response={
                "output_characters": len(response.text) if response else 0,
                "dry_run": dry_run,
            },
            error=self._safe_error(error),
        )
        persisted = await self._persist(row)
        return (str(call_id) if persisted else None, float(cost) if cost is not None else None)

    async def record_embedding(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        input_count: int,
        input_characters: int,
        input_tokens: int,
        dimensions: int | None,
        status: str,
        latency_ms: int,
        error: BaseException | None = None,
        cache_hit: bool = False,
        token_usage_estimated: bool = False,
        avoided_input_tokens: int = 0,
    ) -> str | None:
        cost = (
            Decimal("0")
            if cache_hit
            else self._estimate_cost(provider, model, input_tokens, None, embedding=True)
        )
        call_id = uuid4()
        row = ModelCall(
            id=call_id,
            user_id=self.user_id,
            story_id=self.story_id,
            turn_id=self.turn_id,
            request_id=self.request_id,
            call_type="embedding",
            provider=provider,
            model=model,
            purpose=purpose,
            attempt=1,
            status=status,
            input_tokens=input_tokens,
            output_tokens=0,
            latency_ms=latency_ms,
            token_usage_estimated=token_usage_estimated,
            cache_hit=cache_hit,
            pricing_version=self.settings.model_pricing_version,
            cost_estimate=cost,
            request={
                "input_count": input_count,
                "input_characters": input_characters,
                "avoided_input_tokens": avoided_input_tokens,
            },
            response={"dimensions": dimensions},
            error=self._safe_error(error),
        )
        return str(call_id) if await self._persist(row) else None

    def _estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        *,
        embedding: bool = False,
        dry_run: bool = False,
    ) -> Decimal | None:
        if dry_run or provider == "local":
            return Decimal("0")
        pricing = self.settings.model_pricing.get(f"{provider}:{model}")
        if pricing is None:
            pricing = self.settings.model_pricing.get(model)
        if pricing is None:
            return None

        input_rate_key = "embedding_per_million" if embedding else "input_per_million"
        input_rate = Decimal(str(pricing.get(input_rate_key, 0)))
        output_rate = Decimal(str(pricing.get("output_per_million", 0)))
        input_cost = Decimal(input_tokens or 0) * input_rate / MILLION
        output_cost = Decimal(output_tokens or 0) * output_rate / MILLION
        return input_cost + output_cost

    async def _persist(self, row: ModelCall) -> bool:
        try:
            async with AsyncSessionLocal() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    days=self.settings.model_call_retention_days
                )
                await session.execute(delete(ModelCall).where(ModelCall.created_at < cutoff))
                session.add(row)
                await session.commit()
            return True
        except Exception as error:
            logger.error(
                "Failed to persist model call audit record (%s)",
                error.__class__.__name__,
            )
            return False

    @staticmethod
    def _safe_error(error: BaseException | None) -> str | None:
        if error is None:
            return None
        message = str(error).strip() or error.__class__.__name__
        return redact_sensitive_text(f"{error.__class__.__name__}: {message}")[:1000]
