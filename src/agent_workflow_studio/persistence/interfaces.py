from __future__ import annotations

from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


class Repository(Protocol, Generic[T]):
    def get(self, entity_id: str) -> T | None:
        ...

    def list(self) -> list[T]:
        ...

    def save(self, entity: T) -> None:
        ...

    def delete(self, entity_id: str) -> None:
        ...


class KeyedEntity(Protocol):
    id: str
