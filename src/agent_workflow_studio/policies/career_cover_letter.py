from __future__ import annotations

import re
from typing import Iterable, Mapping

from agent_workflow_studio.core.dependency import PlanPolicy, TaskRule

CAREER_REQUIRED_DEP_KINDS = {
    "intake": frozenset(),
    "analysis": frozenset(),
    "candidates": frozenset({"intake", "analysis"}),
    "selection_review": frozenset({"candidates"}),
    "strategy": frozenset({"candidates", "selection_review"}),
    "draft": frozenset({"strategy"}),
    "review": frozenset({"draft"}),
}

ROLE_ALLOWED_KINDS = {
    "W1": frozenset({"intake"}),
    "W2": frozenset({"analysis"}),
    "W3": frozenset({"candidates", "strategy"}),
    "W4": frozenset({"draft"}),
    "W5": frozenset({"review"}),
    "W6": frozenset({"selection_review", "review"}),
}

CAREER_TASK_RULES = {
    "intake": TaskRule(),
    "analysis": TaskRule(),
    "candidates": TaskRule(required_kinds=frozenset({"intake", "analysis"})),
    "selection_review": TaskRule(required_kinds=frozenset({"candidates"}), allowed_dependency_kinds=frozenset({"candidates"}), exact_dependency_count=1, newest_only_kind="candidates"),
    "strategy": TaskRule(required_kinds=frozenset({"candidates", "selection_review"})),
    "draft": TaskRule(required_kinds=frozenset({"strategy"})),
    "review": TaskRule(required_kinds=frozenset({"draft"}), allowed_dependency_kinds=frozenset({"draft"}), exact_dependency_count=1, newest_only_kind="draft"),
}


def worker_role(name: str) -> str | None:
    match = re.match(r"(W[1-6])(?:\s|$)", str(name or "").strip())
    return match.group(1) if match else None


def build_career_plan_policy(registry: Iterable[Mapping[str, object]]) -> PlanPolicy:
    role_by_worker: dict[str, str] = {}
    for item in registry:
        role = worker_role(str(item.get("name", "")))
        worker_key = str(item.get("worker_key", ""))
        if role and worker_key:
            role_by_worker[worker_key] = role
    worker_allowed: dict[str, frozenset[str]] = {}
    if set(role_by_worker.values()) == set(ROLE_ALLOWED_KINDS):
        worker_allowed = {worker_key: ROLE_ALLOWED_KINDS[role] for worker_key, role in role_by_worker.items()}
    return PlanPolicy(task_rules=CAREER_TASK_RULES, worker_allowed_kinds=worker_allowed)
