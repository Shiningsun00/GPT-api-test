from __future__ import annotations

from typing import Any, Sequence

from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.errors import ProviderError

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    result: dict[str, Any] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(usage, name, None)
        if value is not None:
            result[name] = value
    return result


def _make_client(api_key: str | None, timeout: float, max_retries: int) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderError("openai package is required to create the OpenAI adapter") from exc
    return OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)


class OpenAIModelProvider:
    """OpenAI Responses API adapter behind the core ModelProvider boundary."""

    def __init__(self, api_key: str | None = None, *, timeout: float = 180.0, max_retries: int = 1, client: Any | None = None) -> None:
        self.client = client if client is not None else _make_client(api_key, timeout, max_retries)

    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        try:
            response = self.client.responses.create(model=model, instructions=instructions, input=input_text, store=False)
        except Exception as exc:
            raise ProviderError(f"OpenAI response generation failed: {exc}") from exc
        return ModelResponse(text=str(getattr(response, "output_text", "") or ""), usage=_usage_dict(getattr(response, "usage", None)), raw=response)


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str | None = None, *, model: str = DEFAULT_EMBEDDING_MODEL, timeout: float = 180.0, max_retries: int = 1, client: Any | None = None) -> None:
        self.model = model
        self.client = client if client is not None else _make_client(api_key, timeout, max_retries)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(model=self.model, input=list(texts))
        except Exception as exc:
            raise ProviderError(f"OpenAI embedding failed: {exc}") from exc
        ordered = sorted(response.data, key=lambda item: getattr(item, "index", 0))
        return [list(item.embedding) for item in ordered]
