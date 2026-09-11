from __future__ import annotations

import sqlite3

from agent_workflow_studio.core.models import HierarchyConfig, LinearStep, WorkerSlot, Workflow, WorkflowMode

from .errors import PersistenceConflictError
from .sqlite import SQLitePersistence as BaseSQLitePersistence
from .sqlite import WorkflowRepository as BaseWorkflowRepository
from .sqlite import _integrity, _iso, _json, _loads, _parse_dt, _reject_secret_mapping


class PolicyWorkflowRepository(BaseWorkflowRepository):
    """Workflow repository with durable policy/template configuration.

    `policy_id=None` means generic execution. Domain-specific bindings live in
    `policy_config`, keyed by Workflow/WorkerSlot identifiers rather than Agent names.
    """

    def save(self, entity: Workflow) -> None:
        hierarchy = entity.hierarchy
        _reject_secret_mapping(entity.policy_config, "workflow.policy_config")
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO workflows(
                        id, name, mode, include_original_prompt, has_hierarchy,
                        manager_agent_id, manager_planning_prompt, manager_synthesis_prompt,
                        manager_routing_prompt, created_at, updated_at, policy_id, policy_config_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        mode=excluded.mode,
                        include_original_prompt=excluded.include_original_prompt,
                        has_hierarchy=excluded.has_hierarchy,
                        manager_agent_id=excluded.manager_agent_id,
                        manager_planning_prompt=excluded.manager_planning_prompt,
                        manager_synthesis_prompt=excluded.manager_synthesis_prompt,
                        manager_routing_prompt=excluded.manager_routing_prompt,
                        policy_id=excluded.policy_id,
                        policy_config_json=excluded.policy_config_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        entity.id,
                        entity.name,
                        entity.mode.value,
                        int(entity.include_original_prompt),
                        int(hierarchy is not None),
                        hierarchy.manager_agent_id if hierarchy else None,
                        hierarchy.manager_planning_prompt if hierarchy else "",
                        hierarchy.manager_synthesis_prompt if hierarchy else "",
                        hierarchy.manager_routing_prompt if hierarchy else "",
                        _iso(entity.created_at),
                        _iso(entity.updated_at),
                        entity.policy_id,
                        _json(dict(entity.policy_config)),
                    ),
                )
                conn.execute("DELETE FROM workflow_nodes WHERE workflow_id = ?", (entity.id,))
                for position, step in enumerate(entity.steps):
                    conn.execute(
                        """
                        INSERT INTO workflow_nodes(workflow_id, step_id, position, agent_id, additional_prompt)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (entity.id, step.step_id, position, step.agent_id, step.additional_prompt),
                    )
                conn.execute("DELETE FROM workflow_workers WHERE workflow_id = ?", (entity.id,))
                if hierarchy:
                    for position, worker in enumerate(hierarchy.workers):
                        conn.execute(
                            """
                            INSERT INTO workflow_workers(workflow_id, worker_id, position, agent_id, additional_prompt)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (entity.id, worker.worker_id, position, worker.agent_id, worker.additional_prompt),
                        )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def get(self, entity_id: str) -> Workflow | None:
        row = self.db.connection.execute("SELECT * FROM workflows WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        step_rows = self.db.connection.execute(
            "SELECT * FROM workflow_nodes WHERE workflow_id = ? ORDER BY position, step_id", (entity_id,)
        ).fetchall()
        worker_rows = self.db.connection.execute(
            "SELECT * FROM workflow_workers WHERE workflow_id = ? ORDER BY position, worker_id", (entity_id,)
        ).fetchall()
        hierarchy = None
        if bool(row["has_hierarchy"]):
            hierarchy = HierarchyConfig(
                manager_agent_id=row["manager_agent_id"],
                manager_planning_prompt=row["manager_planning_prompt"],
                manager_synthesis_prompt=row["manager_synthesis_prompt"],
                manager_routing_prompt=row["manager_routing_prompt"],
                workers=[
                    WorkerSlot(
                        worker_id=item["worker_id"],
                        agent_id=item["agent_id"],
                        additional_prompt=item["additional_prompt"],
                    )
                    for item in worker_rows
                ],
            )
        return Workflow(
            id=row["id"],
            name=row["name"],
            mode=WorkflowMode(row["mode"]),
            steps=[
                LinearStep(step_id=item["step_id"], agent_id=item["agent_id"], additional_prompt=item["additional_prompt"])
                for item in step_rows
            ],
            include_original_prompt=bool(row["include_original_prompt"]),
            hierarchy=hierarchy,
            policy_id=row["policy_id"] or None,
            policy_config=_loads(row["policy_config_json"], {}),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )


class SQLitePersistence(BaseSQLitePersistence):
    """Policy-aware persistence facade used by product code from R1 onward."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.workflows = PolicyWorkflowRepository(self.db)
