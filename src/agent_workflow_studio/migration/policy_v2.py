from __future__ import annotations

import re
from dataclasses import replace

from agent_workflow_studio.persistence import SQLitePersistence

CAREER_POLICY_ID = "career_cover_letter"
_CAREER_ARTIFACT_KINDS = frozenset(
    {"intake", "analysis", "candidates", "selection_review", "strategy", "draft", "review"}
)
_LEGACY_ROLE = re.compile(r"^(W[1-6])(?:\s|$)", re.IGNORECASE)


def upgrade_confirmed_legacy_career_workflows(persistence: SQLitePersistence) -> tuple[str, ...]:
    """Upgrade only workflows that carry strong evidence of the old Career policy.

    Generic is the migration default. Legacy Agent-name parsing is used here only as
    a one-time compatibility signal, never as the runtime role-binding mechanism.
    A workflow is upgraded only when:
    - it has no explicit policy yet,
    - it is hierarchical with exactly six worker slots,
    - persisted artifacts include the complete Career artifact-kind set, and
    - the six legacy worker names map uniquely to W1..W6.

    The resulting durable binding is stored as `policy_config.slot_roles` keyed by
    WorkerSlot id, so later runtime code no longer needs Agent names.
    """

    upgraded: list[str] = []
    sessions_by_workflow: dict[str, set[str]] = {}
    for session in persistence.sessions.list():
        sessions_by_workflow.setdefault(session.workflow_id, set()).add(session.id)

    artifacts = persistence.artifacts.list()
    for workflow in persistence.workflows.list():
        if workflow.policy_id is not None or workflow.hierarchy is None:
            continue
        workers = workflow.hierarchy.workers
        if len(workers) != 6:
            continue

        session_ids = sessions_by_workflow.get(workflow.id, set())
        artifact_kinds = {item.kind for item in artifacts if item.session_id in session_ids}
        if not _CAREER_ARTIFACT_KINDS.issubset(artifact_kinds):
            continue

        slot_roles: dict[str, str] = {}
        seen_roles: set[str] = set()
        valid = True
        for slot in workers:
            agent = persistence.agents.get(slot.agent_id)
            match = _LEGACY_ROLE.match(agent.name.strip()) if agent is not None else None
            if match is None:
                valid = False
                break
            role = match.group(1).upper()
            if role in seen_roles:
                valid = False
                break
            seen_roles.add(role)
            slot_roles[slot.worker_id] = role

        if not valid or seen_roles != {f"W{index}" for index in range(1, 7)}:
            continue

        persistence.workflows.save(
            replace(
                workflow,
                policy_id=CAREER_POLICY_ID,
                policy_config={"slot_roles": slot_roles, "migrated_from": "legacy_name_roles"},
            )
        )
        upgraded.append(workflow.id)

    return tuple(upgraded)
