from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.llm import LLMRequest, LLMResponse


class LLMAdapter(ABC):
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a model response for a normalized LLM request."""

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream model text chunks. Adapters can override for native streaming."""
        response = await self.generate(request)
        if response.text:
            yield response.text
