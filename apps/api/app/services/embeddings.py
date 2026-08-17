from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.config import Settings
from app.llm.audit import CallAuditor
from app.services.token_estimator import estimate_tokens


EMBEDDING_DIMENSIONS = 128


@dataclass(frozen=True)
class EmbeddingMetadata:
    model: str
    dimensions: int
    version: str
    content_hash: str
    embedded_at: datetime


class EmbeddingService:
    def __init__(self, settings: Settings, auditor: CallAuditor | None = None):
        self.settings = settings
        self.auditor = auditor
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def embed(self, text: str, *, purpose: str = "embedding") -> list[float]:
        vectors = await self.embed_many([text], purpose=purpose)
        return vectors[0] if vectors else []

    async def embed_many(
        self,
        texts: list[str],
        *,
        purpose: str = "embedding",
    ) -> list[list[float]]:
        contents = [text.strip() for text in texts if text.strip()]
        if not contents:
            return []
        started = time.perf_counter()
        input_tokens = sum(estimate_tokens(content) for content in contents)
        if self.settings.dry_run_llm or self.client is None:
            vectors = [deterministic_embed_text(content) for content in contents]
            await self._record_call(
                provider="local",
                model="deterministic-blake2b-128",
                purpose=purpose,
                contents=contents,
                input_tokens=input_tokens,
                vectors=vectors,
                status="succeeded",
                started=started,
                token_usage_estimated=True,
            )
            return vectors

        if self.auditor is not None:
            await self.auditor.ensure_quota(input_tokens)
            self.auditor.reserve_external_call()

        try:
            response = await self.client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=contents,
            )
            usage = getattr(response, "usage", None)
            provider_input_tokens = getattr(usage, "prompt_tokens", None)
            token_usage_estimated = provider_input_tokens is None
            input_tokens = provider_input_tokens or input_tokens
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors = [[float(value) for value in item.embedding] for item in ordered]
        except Exception as error:
            await self._record_call(
                provider="openai",
                model=self.settings.openai_embedding_model,
                purpose=purpose,
                contents=contents,
                input_tokens=input_tokens,
                vectors=[],
                status="failed",
                started=started,
                error=error,
                token_usage_estimated=True,
            )
            raise

        await self._record_call(
            provider="openai",
            model=self.settings.openai_embedding_model,
            purpose=purpose,
            contents=contents,
            input_tokens=input_tokens,
            vectors=vectors,
            status="succeeded",
            started=started,
            token_usage_estimated=token_usage_estimated,
        )
        return vectors

    async def record_cache_hit(
        self,
        text: str,
        vector: list[float],
        *,
        purpose: str = "embedding",
    ) -> None:
        if self.auditor is None:
            return
        provider, model = self._provider_and_model()
        await self.auditor.record_embedding(
            provider=provider,
            model=model,
            purpose=purpose,
            input_count=1,
            input_characters=len(text),
            input_tokens=0,
            avoided_input_tokens=estimate_tokens(text),
            dimensions=len(vector),
            status="succeeded",
            latency_ms=0,
            cache_hit=True,
        )

    def _provider_and_model(self) -> tuple[str, str]:
        if self.settings.dry_run_llm or self.client is None:
            return "local", "deterministic-blake2b-128"
        return "openai", self.settings.openai_embedding_model

    def metadata(self, text: str, vector: list[float]) -> EmbeddingMetadata:
        provider, model = self._provider_and_model()
        return EmbeddingMetadata(
            model=f"{provider}:{model}",
            dimensions=len(vector),
            version=self.settings.embedding_version,
            content_hash=embedding_content_hash(text),
            embedded_at=datetime.now(timezone.utc),
        )

    def is_compatible(
        self,
        *,
        model: str | None,
        dimensions: int | None,
        version: str | None,
        vector: list[float],
    ) -> bool:
        provider, current_model = self._provider_and_model()
        return (
            model == f"{provider}:{current_model}"
            and dimensions == len(vector)
            and version == self.settings.embedding_version
        )

    def is_model_version_compatible(
        self,
        *,
        model: str | None,
        version: str | None,
    ) -> bool:
        provider, current_model = self._provider_and_model()
        return model == f"{provider}:{current_model}" and version == self.settings.embedding_version

    async def _record_call(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        contents: list[str],
        input_tokens: int,
        vectors: list[list[float]],
        status: str,
        started: float,
        error: BaseException | None = None,
        token_usage_estimated: bool = False,
    ) -> None:
        if self.auditor is None:
            return
        await self.auditor.record_embedding(
            provider=provider,
            model=model,
            purpose=purpose,
            input_count=len(contents),
            input_characters=sum(len(content) for content in contents),
            input_tokens=input_tokens,
            dimensions=len(vectors[0]) if vectors else None,
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error,
            token_usage_estimated=token_usage_estimated,
        )


def deterministic_embed_text(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = _tokens(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def embedding_content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    if len(left) != len(right):
        return 0.0
    return sum(float(left[index]) * float(right[index]) for index in range(len(left)))


def _tokens(text: str) -> list[str]:
    cleaned = text.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", cleaned)
    grams: list[str] = []
    grams.extend(words)
    for index in range(max(0, len(words) - 1)):
        grams.append(f"{words[index]}{words[index + 1]}")
    return grams
