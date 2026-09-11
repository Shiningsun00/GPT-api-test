from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from agent_workflow_studio.core.models import Serializable, utc_now


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True, slots=True)
class ExecutionEvent(Serializable):
    id: str
    session_id: str
    event_type: str
    run_id: str | None = None
    stage: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionEvent":
        return cls(
            id=str(data["id"]),
            session_id=str(data["session_id"]),
            run_id=data.get("run_id"),
            event_type=str(data["event_type"]),
            stage=str(data.get("stage", "")),
            data=dict(data.get("data", {})),
            created_at=_parse_dt(data.get("created_at")) or utc_now(),
        )


@dataclass(slots=True)
class ExternalThreadLink(Serializable):
    id: str
    provider: str
    external_thread_id: str
    session_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("external thread provider is required")
        if not self.external_thread_id.strip():
            raise ValueError("external thread id is required")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExternalThreadLink":
        return cls(
            id=str(data["id"]),
            provider=str(data["provider"]),
            external_thread_id=str(data["external_thread_id"]),
            session_id=str(data["session_id"]),
            metadata=dict(data.get("metadata", {})),
            created_at=_parse_dt(data.get("created_at")) or utc_now(),
            updated_at=_parse_dt(data.get("updated_at")) or utc_now(),
        )
