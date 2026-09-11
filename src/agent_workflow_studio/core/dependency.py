from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .errors import DependencyValidationError, WorkflowValidationError
from .models import Artifact


@dataclass(frozen=True, slots=True)
class TaskRule:
    required_kinds: frozenset[str] = frozenset()
    allowed_dependency_kinds: frozenset[str] | None = None
    exact_dependency_count: int | None = None
    newest_only_kind: str | None = None


@dataclass(frozen=True, slots=True)
class PlanPolicy:
    task_rules: Mapping[str, TaskRule] = field(default_factory=dict)
    worker_allowed_kinds: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @property
    def allowed_kinds(self) -> frozenset[str]:
        return frozenset(self.task_rules)


def _artifact_kind(artifact: Artifact | Mapping[str, Any]) -> str:
    if isinstance(artifact, Artifact):
        return artifact.kind
    return str(artifact.get("kind", ""))


def _artifact_sequence(artifact: Artifact | Mapping[str, Any]) -> int:
    if isinstance(artifact, Artifact):
        return artifact.sequence
    try:
        return int(artifact.get("sequence", artifact.get("draft_version", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _newest_id(artifacts: Mapping[str, Artifact | Mapping[str, Any]], kind: str) -> str | None:
    candidates = [
        (artifact_id, artifact)
        for artifact_id, artifact in artifacts.items()
        if _artifact_kind(artifact) == kind
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (_artifact_sequence(item[1]), item[0]))[0]


def stabilize_plan_dependencies(
    plan: Mapping[str, Any],
    artifacts: Mapping[str, Artifact | Mapping[str, Any]],
    policy: PlanPolicy | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Repair only deterministic dependency mistakes before strict validation.

    The function never invents new work. It only removes unresolved or duplicate
    dependency ids and binds dependency kinds to the newest already completed
    artifact when a supplied policy makes that repair deterministic.
    """
    repaired = deepcopy(dict(plan))
    assignments = repaired.get("assignments")
    if not isinstance(assignments, list):
        return repaired, []
    notes: list[str] = []
    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            continue
        original = assignment.get("depends_on", [])
        deps = original if isinstance(original, list) else []
        cleaned: list[str] = []
        for dependency in deps:
            if dependency in artifacts and dependency not in cleaned:
                cleaned.append(dependency)
        if cleaned != deps:
            notes.append(f"assignment[{index}] removed invalid or duplicate dependency references")
        kind = str(assignment.get("kind", ""))
        rule = policy.task_rules.get(kind) if policy else None
        if rule:
            if rule.allowed_dependency_kinds is not None:
                filtered = [dep for dep in cleaned if _artifact_kind(artifacts[dep]) in rule.allowed_dependency_kinds]
                if filtered != cleaned:
                    notes.append(f"assignment[{index}] removed dependency kinds not allowed for {kind}")
                cleaned = filtered
            if rule.newest_only_kind:
                newest = _newest_id(artifacts, rule.newest_only_kind)
                replacement = [newest] if newest else []
                if cleaned != replacement:
                    notes.append(f"assignment[{index}] bound {kind} to newest {rule.newest_only_kind}")
                cleaned = replacement
            else:
                for required_kind in sorted(rule.required_kinds):
                    if any(_artifact_kind(artifacts[dep]) == required_kind for dep in cleaned):
                        continue
                    newest = _newest_id(artifacts, required_kind)
                    if newest:
                        cleaned.append(newest)
                        notes.append(f"assignment[{index}] added newest required {required_kind}")
        assignment["depends_on"] = cleaned
    if notes:
        repaired["_dependency_repairs"] = notes
    return repaired, notes


def validate_plan(
    plan: Mapping[str, Any],
    registry: Iterable[Mapping[str, Any]],
    artifacts: Mapping[str, Artifact | Mapping[str, Any]],
    policy: PlanPolicy | None = None,
) -> Mapping[str, Any]:
    action = plan.get("action")
    if action not in {"delegate", "final", "needs_input"}:
        raise WorkflowValidationError("plan action must be delegate, final, or needs_input")
    if action != "delegate":
        return plan
    assignments = plan.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise WorkflowValidationError("delegate action requires assignments")
    registry_keys = {str(item.get("worker_key")) for item in registry}
    seen: set[str] = set()
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            raise WorkflowValidationError("each assignment must be an object")
        worker_key = str(assignment.get("worker_key", ""))
        if worker_key not in registry_keys:
            raise WorkflowValidationError(f"unknown worker key: {worker_key}")
        if worker_key in seen:
            raise WorkflowValidationError("the same worker cannot run twice in one round")
        seen.add(worker_key)
        task = str(assignment.get("task", "")).strip()
        if not task:
            raise WorkflowValidationError("assignment requires a concrete task")
        kind = str(assignment.get("kind", ""))
        if policy and kind not in policy.allowed_kinds:
            raise WorkflowValidationError(f"unsupported task kind: {kind}")
        deps = assignment.get("depends_on", [])
        if not isinstance(deps, list):
            raise DependencyValidationError("depends_on must be a list")
        if any(dep not in artifacts for dep in deps):
            raise DependencyValidationError("assignment references incomplete artifacts")
        if policy:
            rule = policy.task_rules.get(kind)
            if rule:
                dep_kinds = [_artifact_kind(artifacts[dep]) for dep in deps]
                if not rule.required_kinds.issubset(dep_kinds):
                    missing = sorted(rule.required_kinds.difference(dep_kinds))
                    raise DependencyValidationError(f"missing required dependency kinds for {kind}: {missing}")
                if rule.allowed_dependency_kinds is not None and any(dep_kind not in rule.allowed_dependency_kinds for dep_kind in dep_kinds):
                    raise DependencyValidationError(f"invalid dependency kind for {kind}")
                if rule.exact_dependency_count is not None and len(deps) != rule.exact_dependency_count:
                    raise DependencyValidationError(f"{kind} requires exactly {rule.exact_dependency_count} dependencies")
                if rule.newest_only_kind:
                    newest = _newest_id(artifacts, rule.newest_only_kind)
                    if newest is None or deps != [newest]:
                        raise DependencyValidationError(f"{kind} must depend only on the newest {rule.newest_only_kind} artifact")
            allowed = policy.worker_allowed_kinds.get(worker_key)
            if allowed is not None and kind not in allowed:
                raise WorkflowValidationError(f"worker {worker_key} cannot perform task kind {kind}")
    return plan
