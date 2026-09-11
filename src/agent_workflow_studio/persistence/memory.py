from __future__ import annotations

from copy import deepcopy
from typing import Generic, TypeVar

from .interfaces import KeyedEntity

T = TypeVar("T", bound=KeyedEntity)


class InMemoryRepository(Generic[T]):
    """STEP 1 repository used for tests and core composition before SQLite."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def get(self, entity_id: str) -> T | None:
        value = self._items.get(entity_id)
        return deepcopy(value) if value is not None else None

    def list(self) -> list[T]:
        return [deepcopy(value) for value in self._items.values()]

    def save(self, entity: T) -> None:
        self._items[entity.id] = deepcopy(entity)

    def delete(self, entity_id: str) -> None:
        self._items.pop(entity_id, None)

    def clear(self) -> None:
        self._items.clear()
