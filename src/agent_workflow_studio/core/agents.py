from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable

from .models import Agent, utc_now


def validate_agent(agent: Agent) -> Agent:
    if not agent.name.strip():
        raise ValueError("agent name is required")
    if not agent.model.strip():
        raise ValueError("agent model is required")
    if agent.rag_top_k < 1:
        raise ValueError("rag_top_k must be at least 1")
    return agent


def clone_agent(agent: Agent, *, new_id: str, new_name: str | None = None) -> Agent:
    return replace(
        agent,
        id=new_id,
        name=(new_name or f"{agent.name} copy").strip(),
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def replace_agent_sources(agent: Agent, source_ids: Iterable[str], *, updated_at: datetime | None = None) -> Agent:
    unique = list(dict.fromkeys(str(source_id) for source_id in source_ids if str(source_id).strip()))
    return replace(agent, source_ids=unique, updated_at=updated_at or utc_now())
