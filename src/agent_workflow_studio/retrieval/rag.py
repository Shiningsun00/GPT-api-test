from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .chunking import chunk_text
from .embeddings import EmbeddingProvider, cosine_similarity


@dataclass(frozen=True, slots=True)
class TextSource:
    source_id: str
    label: str
    source_type: str
    text: str


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    source_id: str
    label: str
    source_type: str
    chunk_index: int
    text: str
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RAGHit:
    source_id: str
    label: str
    source_type: str
    chunk_index: int
    text: str
    similarity: float


class EmbeddingCache(Protocol):
    def get(self, key: str) -> list[list[float]] | None:
        ...

    def put(self, key: str, value: list[list[float]]) -> None:
        ...


@dataclass(slots=True)
class InMemoryEmbeddingCache:
    values: dict[str, list[list[float]]] = field(default_factory=dict)

    def get(self, key: str) -> list[list[float]] | None:
        value = self.values.get(key)
        return [list(vector) for vector in value] if value is not None else None

    def put(self, key: str, value: list[list[float]]) -> None:
        self.values[key] = [list(vector) for vector in value]


def build_index(sources: Sequence[TextSource], embedder: EmbeddingProvider, *, cache: EmbeddingCache | None = None, max_chunks: int = 300) -> list[IndexedChunk]:
    raw_chunks: list[tuple[TextSource, int, str]] = []
    for source in sources:
        for index, text in enumerate(chunk_text(source.text), start=1):
            raw_chunks.append((source, index, text))
            if len(raw_chunks) >= max_chunks:
                break
        if len(raw_chunks) >= max_chunks:
            break
    if not raw_chunks:
        return []
    cache_key = "|".join(f"{source.source_id}:{index}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}" for source, index, text in raw_chunks)
    vectors = cache.get(cache_key) if cache else None
    if vectors is None:
        vectors = embedder.embed([text for _, _, text in raw_chunks])
        if cache:
            cache.put(cache_key, vectors)
    if len(vectors) != len(raw_chunks):
        raise ValueError("embedding provider returned an unexpected vector count")
    return [IndexedChunk(source_id=source.source_id, label=source.label, source_type=source.source_type, chunk_index=index, text=text, embedding=tuple(float(value) for value in vector)) for (source, index, text), vector in zip(raw_chunks, vectors)]


def retrieve(query: str, index: Sequence[IndexedChunk], embedder: EmbeddingProvider, *, top_k: int = 5) -> list[RAGHit]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not index or not str(query or "").strip():
        return []
    query_vector = embedder.embed([query])[0]
    hits = [RAGHit(source_id=chunk.source_id, label=chunk.label, source_type=chunk.source_type, chunk_index=chunk.chunk_index, text=chunk.text, similarity=cosine_similarity(query_vector, chunk.embedding)) for chunk in index]
    hits.sort(key=lambda hit: hit.similarity, reverse=True)
    return hits[:top_k]


def format_hits(hits: Sequence[RAGHit]) -> str:
    return "\n\n".join(f"[Source: {hit.label} | chunk={hit.chunk_index} | similarity={hit.similarity:.4f}]\n{hit.text}" for hit in hits)
