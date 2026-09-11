from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from agent_workflow_studio.core.models import Agent, HierarchyConfig, LinearStep, WorkerSlot, Workflow, WorkflowMode

SUPPORTED_WORKSPACE_SCHEMAS = frozenset({1, 2, 3, 4})


@dataclass(slots=True)
class LegacyWorkspaceImport:
    agents: list[Agent] = field(default_factory=list)
    linear_workflow: Workflow | None = None
    hierarchical_workflow: Workflow | None = None
    file_payloads: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def legacy_agent_to_core(agent_id: str, data: Mapping[str, Any]) -> Agent:
    """Map legacy Agent config without carrying file bytes into the Agent model."""
    source_ids: list[str] = []
    for file_item in data.get("rag_files", []) or []:
        if not isinstance(file_item, Mapping):
            continue
        digest = str(file_item.get("sha256", "")).strip()
        if digest:
            source_ids.append(f"file:{digest}")
    return Agent(id=str(data.get("id") or agent_id), name=str(data.get("name") or agent_id), model=str(data.get("model") or "gpt-5.6-luna"), system_prompt=str(data.get("system_prompt", "")), rag_enabled=bool(data.get("rag_enabled", False)), rag_top_k=int(data.get("rag_top_k", 5) or 5), source_ids=list(dict.fromkeys(source_ids)), notion_enabled=bool(data.get("notion_enabled", False)), notion_sources=[str(item) for item in data.get("notion_sources", []) or []])


def legacy_linear_to_workflow(workflow: list[Mapping[str, Any]], *, workflow_id: str = "legacy-linear", name: str = "Imported Linear Workflow", include_original_prompt: bool = True) -> Workflow:
    steps = [LinearStep(step_id=str(item.get("step_id") or f"step-{index}"), agent_id=str(item.get("agent_id", "")), additional_prompt=str(item.get("additional_prompt", ""))) for index, item in enumerate(workflow, start=1)]
    return Workflow(id=workflow_id, name=name, mode=WorkflowMode.LINEAR, steps=steps, include_original_prompt=include_original_prompt)


def legacy_hierarchy_to_workflow(hierarchy: Mapping[str, Any], *, workflow_id: str = "legacy-hierarchical", name: str = "Imported Hierarchical Workflow") -> Workflow:
    workers = [WorkerSlot(worker_id=str(item.get("worker_id") or f"worker-{index}"), agent_id=str(item.get("agent_id", "")), additional_prompt=str(item.get("additional_prompt", ""))) for index, item in enumerate(hierarchy.get("workers", []) or [], start=1)]
    config = HierarchyConfig(manager_agent_id=hierarchy.get("manager_agent_id"), manager_planning_prompt=str(hierarchy.get("manager_planning_prompt", "")), manager_synthesis_prompt=str(hierarchy.get("manager_synthesis_prompt", "")), manager_routing_prompt=str(hierarchy.get("manager_routing_prompt", "")), workers=workers)
    return Workflow(id=workflow_id, name=name, mode=WorkflowMode.HIERARCHICAL, hierarchy=config)


def validate_schema_version(version: int) -> int:
    if version not in SUPPORTED_WORKSPACE_SCHEMAS:
        raise ValueError(f"unsupported workspace schema version: {version}")
    return version
