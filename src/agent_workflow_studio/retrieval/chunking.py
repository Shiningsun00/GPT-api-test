from __future__ import annotations

DEFAULT_CHUNK_SIZE = 2800
DEFAULT_CHUNK_OVERLAP = 350


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")
    normalized = str(text or "").replace("\x00", " ").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            lower_bound = start + max(1, chunk_size // 2)
            newline = normalized.rfind("\n", lower_bound, end)
            space = normalized.rfind(" ", lower_bound, end)
            split_at = max(newline, space)
            if split_at > start:
                end = split_at + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks
