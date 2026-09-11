from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from agent_workflow_studio.core.models import (
    Agent,
    Artifact,
    ExecutionFile,
    HierarchyConfig,
    LinearStep,
    Message,
    MessageAttachment,
    ReferenceSource,
    Revision,
    Run,
    RunStatus,
    WorkerSlot,
    Workflow,
    WorkflowMode,
    WorkflowSession,
)

from .db import SQLiteDatabase
from .errors import ImmutableEntityError, PersistenceConflictError, SecretPersistenceError
from .records import ExecutionEvent, ExternalThreadLink

_FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "apikey",
    "openai_api_key",
    "notion_api_key",
    "discord_token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "client_secret",
}


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def _reject_secret_mapping(value: Any, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in _FORBIDDEN_SECRET_KEYS:
                raise SecretPersistenceError(f"secret-like field is not allowed in persistence: {path}.{key}")
            _reject_secret_mapping(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_mapping(item, f"{path}[{index}]")


def _integrity(exc: sqlite3.IntegrityError) -> PersistenceConflictError:
    return PersistenceConflictError(str(exc))


class AgentRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: Agent) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO agents(
                        id, name, model, system_prompt, rag_enabled, rag_top_k,
                        notion_enabled, notion_sources_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        model=excluded.model,
                        system_prompt=excluded.system_prompt,
                        rag_enabled=excluded.rag_enabled,
                        rag_top_k=excluded.rag_top_k,
                        notion_enabled=excluded.notion_enabled,
                        notion_sources_json=excluded.notion_sources_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        entity.id,
                        entity.name,
                        entity.model,
                        entity.system_prompt,
                        int(entity.rag_enabled),
                        entity.rag_top_k,
                        int(entity.notion_enabled),
                        _json(entity.notion_sources),
                        _iso(entity.created_at),
                        _iso(entity.updated_at),
                    ),
                )
                conn.execute("DELETE FROM agent_sources WHERE agent_id = ?", (entity.id,))
                for position, source_id in enumerate(entity.source_ids):
                    conn.execute(
                        "INSERT INTO agent_sources(agent_id, source_id, position) VALUES (?, ?, ?)",
                        (entity.id, source_id, position),
                    )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def get(self, entity_id: str) -> Agent | None:
        row = self.db.connection.execute("SELECT * FROM agents WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        source_rows = self.db.connection.execute(
            "SELECT source_id FROM agent_sources WHERE agent_id = ? ORDER BY position, source_id",
            (entity_id,),
        ).fetchall()
        return Agent.from_dict(
            {
                "id": row["id"],
                "name": row["name"],
                "model": row["model"],
                "system_prompt": row["system_prompt"],
                "rag_enabled": bool(row["rag_enabled"]),
                "rag_top_k": row["rag_top_k"],
                "source_ids": [item["source_id"] for item in source_rows],
                "notion_enabled": bool(row["notion_enabled"]),
                "notion_sources": _loads(row["notion_sources_json"], []),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    def list(self) -> list[Agent]:
        ids = [row["id"] for row in self.db.connection.execute("SELECT id FROM agents ORDER BY created_at, id")]
        return [item for entity_id in ids if (item := self.get(entity_id)) is not None]

    def delete(self, entity_id: str) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM agents WHERE id = ?", (entity_id,))
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc


class SourceRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: ReferenceSource) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO sources(id, kind, label, sha256, storage_ref, notion_ref, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        label=excluded.label,
                        sha256=excluded.sha256,
                        storage_ref=excluded.storage_ref,
                        notion_ref=excluded.notion_ref
                    """,
                    (
                        entity.id,
                        entity.kind.value,
                        entity.label,
                        entity.sha256,
                        entity.storage_ref,
                        entity.notion_ref,
                        _iso(entity.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def get(self, entity_id: str) -> ReferenceSource | None:
        row = self.db.connection.execute("SELECT * FROM sources WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        return ReferenceSource.from_dict(dict(row))

    def list(self) -> list[ReferenceSource]:
        rows = self.db.connection.execute("SELECT * FROM sources ORDER BY created_at, id").fetchall()
        return [ReferenceSource.from_dict(dict(row)) for row in rows]

    def list_for_agent(self, agent_id: str) -> list[ReferenceSource]:
        ids = [
            row["source_id"]
            for row in self.db.connection.execute(
                "SELECT source_id FROM agent_sources WHERE agent_id = ? ORDER BY position, source_id", (agent_id,)
            )
        ]
        return [item for source_id in ids if (item := self.get(source_id)) is not None]

    def delete(self, entity_id: str) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM sources WHERE id = ?", (entity_id,))
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc


class WorkflowRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: Workflow) -> None:
        hierarchy = entity.hierarchy
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO workflows(
                        id, name, mode, include_original_prompt, has_hierarchy,
                        manager_agent_id, manager_planning_prompt, manager_synthesis_prompt,
                        manager_routing_prompt, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        mode=excluded.mode,
                        include_original_prompt=excluded.include_original_prompt,
                        has_hierarchy=excluded.has_hierarchy,
                        manager_agent_id=excluded.manager_agent_id,
                        manager_planning_prompt=excluded.manager_planning_prompt,
                        manager_synthesis_prompt=excluded.manager_synthesis_prompt,
                        manager_routing_prompt=excluded.manager_routing_prompt,
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
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    def list(self) -> list[Workflow]:
        ids = [row["id"] for row in self.db.connection.execute("SELECT id FROM workflows ORDER BY created_at, id")]
        return [item for entity_id in ids if (item := self.get(entity_id)) is not None]

    def delete(self, entity_id: str) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM workflows WHERE id = ?", (entity_id,))
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc


class SessionRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: WorkflowSession) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_sessions(id, workflow_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        workflow_id=excluded.workflow_id,
                        title=excluded.title,
                        updated_at=excluded.updated_at
                    """,
                    (entity.id, entity.workflow_id, entity.title, _iso(entity.created_at), _iso(entity.updated_at)),
                )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def get(self, entity_id: str) -> WorkflowSession | None:
        row = self.db.connection.execute("SELECT * FROM workflow_sessions WHERE id = ?", (entity_id,)).fetchone()
        return WorkflowSession.from_dict(dict(row)) if row is not None else None

    def list(self) -> list[WorkflowSession]:
        rows = self.db.connection.execute("SELECT * FROM workflow_sessions ORDER BY created_at, id").fetchall()
        return [WorkflowSession.from_dict(dict(row)) for row in rows]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM workflow_sessions WHERE id = ?", (entity_id,))


class RunRepository:
    _ACTIVE = (RunStatus.CREATED.value, RunStatus.RUNNING.value, RunStatus.WAITING_FOR_USER.value)

    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: Run) -> None:
        existing = self.db.connection.execute("SELECT status FROM runs WHERE id = ?", (entity.id,)).fetchone()
        if existing is not None:
            existing_status = RunStatus(existing["status"])
            if existing_status.terminal and entity.status != existing_status:
                raise PersistenceConflictError(
                    f"terminal run {entity.id} cannot transition from {existing_status.value} to {entity.status.value}"
                )
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO runs(
                        id, session_id, workflow_id, kind, status, parent_run_id, trigger_message_id,
                        created_at, updated_at, started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        session_id=excluded.session_id,
                        workflow_id=excluded.workflow_id,
                        kind=excluded.kind,
                        status=excluded.status,
                        parent_run_id=excluded.parent_run_id,
                        trigger_message_id=excluded.trigger_message_id,
                        updated_at=excluded.updated_at,
                        started_at=excluded.started_at,
                        completed_at=excluded.completed_at
                    """,
                    (
                        entity.id,
                        entity.session_id,
                        entity.workflow_id,
                        entity.kind.value,
                        entity.status.value,
                        entity.parent_run_id,
                        entity.trigger_message_id,
                        _iso(entity.created_at),
                        _iso(entity.updated_at),
                        _iso(entity.started_at),
                        _iso(entity.completed_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def get(self, entity_id: str) -> Run | None:
        row = self.db.connection.execute("SELECT * FROM runs WHERE id = ?", (entity_id,)).fetchone()
        return Run.from_dict(dict(row)) if row is not None else None

    def list(self, *, session_id: str | None = None) -> list[Run]:
        if session_id is None:
            rows = self.db.connection.execute("SELECT * FROM runs ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY created_at, id", (session_id,)
            ).fetchall()
        return [Run.from_dict(dict(row)) for row in rows]

    def list_active(self) -> list[Run]:
        marks = ",".join("?" for _ in self._ACTIVE)
        rows = self.db.connection.execute(
            f"SELECT * FROM runs WHERE status IN ({marks}) ORDER BY created_at, id", self._ACTIVE
        ).fetchall()
        return [Run.from_dict(dict(row)) for row in rows]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (entity_id,))


class MessageRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: Message) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO messages(id, session_id, run_id, role, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        session_id=excluded.session_id,
                        run_id=excluded.run_id,
                        role=excluded.role,
                        content=excluded.content
                    """,
                    (entity.id, entity.session_id, entity.run_id, entity.role.value, entity.content, _iso(entity.created_at)),
                )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def _attachment_ids(self, message_id: str) -> list[str]:
        rows = self.db.connection.execute(
            "SELECT id FROM message_attachments WHERE message_id = ? ORDER BY created_at, id", (message_id,)
        ).fetchall()
        return [row["id"] for row in rows]

    def get(self, entity_id: str) -> Message | None:
        row = self.db.connection.execute("SELECT * FROM messages WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["attachment_ids"] = self._attachment_ids(entity_id)
        return Message.from_dict(data)

    def list(self, *, session_id: str | None = None, run_id: str | None = None) -> list[Message]:
        clauses = []
        params: list[str] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.connection.execute(f"SELECT id FROM messages{where} ORDER BY created_at, id", params).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM messages WHERE id = ?", (entity_id,))


class AttachmentRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: MessageAttachment) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO message_attachments(
                        id, message_id, filename, sha256, size, storage_ref, scope, mime_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.id,
                        entity.message_id,
                        entity.filename,
                        entity.sha256,
                        entity.size,
                        entity.storage_ref,
                        entity.scope.value,
                        entity.mime_type,
                        _iso(entity.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ImmutableEntityError(f"attachment is immutable or invalid: {exc}") from exc

    def get(self, entity_id: str) -> MessageAttachment | None:
        row = self.db.connection.execute("SELECT * FROM message_attachments WHERE id = ?", (entity_id,)).fetchone()
        return MessageAttachment.from_dict(dict(row)) if row is not None else None

    def list(self, *, message_id: str | None = None) -> list[MessageAttachment]:
        if message_id is None:
            rows = self.db.connection.execute("SELECT * FROM message_attachments ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT * FROM message_attachments WHERE message_id = ? ORDER BY created_at, id", (message_id,)
            ).fetchall()
        return [MessageAttachment.from_dict(dict(row)) for row in rows]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM message_attachments WHERE id = ?", (entity_id,))


class ArtifactRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: Artifact) -> None:
        _reject_secret_mapping(entity.metadata, "artifact.metadata")
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO artifacts(id, session_id, run_id, kind, producer, body, metadata_json, sequence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.id,
                        entity.session_id,
                        entity.run_id,
                        entity.kind,
                        entity.producer,
                        entity.body,
                        _json(dict(entity.metadata)),
                        entity.sequence,
                        _iso(entity.created_at),
                    ),
                )
                for position, dependency_id in enumerate(entity.dependencies):
                    conn.execute(
                        """
                        INSERT INTO artifact_dependencies(artifact_id, depends_on_artifact_id, position)
                        VALUES (?, ?, ?)
                        """,
                        (entity.id, dependency_id, position),
                    )
        except sqlite3.IntegrityError as exc:
            raise ImmutableEntityError(f"artifact is immutable or invalid: {exc}") from exc

    def get(self, entity_id: str) -> Artifact | None:
        row = self.db.connection.execute("SELECT * FROM artifacts WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        deps = [
            item["depends_on_artifact_id"]
            for item in self.db.connection.execute(
                "SELECT depends_on_artifact_id FROM artifact_dependencies WHERE artifact_id = ? ORDER BY position",
                (entity_id,),
            ).fetchall()
        ]
        data = dict(row)
        data["metadata"] = _loads(data.pop("metadata_json"), {})
        data["dependencies"] = deps
        return Artifact.from_dict(data)

    def list(self, *, run_id: str | None = None) -> list[Artifact]:
        if run_id is None:
            rows = self.db.connection.execute("SELECT id FROM artifacts ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT id FROM artifacts WHERE run_id = ? ORDER BY sequence, created_at, id", (run_id,)
            ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM artifacts WHERE id = ?", (entity_id,))


class RevisionRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: Revision) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO revisions(id, session_id, run_id, version, final_output, feedback, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.id,
                        entity.session_id,
                        entity.run_id,
                        entity.version,
                        entity.final_output,
                        entity.feedback,
                        _iso(entity.created_at),
                    ),
                )
                for position, artifact_id in enumerate(entity.artifact_ids):
                    conn.execute(
                        "INSERT INTO revision_artifacts(revision_id, artifact_id, position) VALUES (?, ?, ?)",
                        (entity.id, artifact_id, position),
                    )
                for position, attachment_id in enumerate(entity.attachment_ids):
                    conn.execute(
                        "INSERT INTO revision_attachments(revision_id, attachment_id, position) VALUES (?, ?, ?)",
                        (entity.id, attachment_id, position),
                    )
        except sqlite3.IntegrityError as exc:
            raise ImmutableEntityError(f"revision is immutable or invalid: {exc}") from exc

    def get(self, entity_id: str) -> Revision | None:
        row = self.db.connection.execute("SELECT * FROM revisions WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        artifact_ids = [
            item["artifact_id"]
            for item in self.db.connection.execute(
                "SELECT artifact_id FROM revision_artifacts WHERE revision_id = ? ORDER BY position", (entity_id,)
            ).fetchall()
        ]
        attachment_ids = [
            item["attachment_id"]
            for item in self.db.connection.execute(
                "SELECT attachment_id FROM revision_attachments WHERE revision_id = ? ORDER BY position", (entity_id,)
            ).fetchall()
        ]
        data = dict(row)
        data["artifact_ids"] = artifact_ids
        data["attachment_ids"] = attachment_ids
        return Revision.from_dict(data)

    def list(self, *, session_id: str | None = None) -> list[Revision]:
        if session_id is None:
            rows = self.db.connection.execute("SELECT id FROM revisions ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT id FROM revisions WHERE session_id = ? ORDER BY version, created_at", (session_id,)
            ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM revisions WHERE id = ?", (entity_id,))


class ExecutionEventRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: ExecutionEvent) -> None:
        _reject_secret_mapping(entity.data, "execution_event.data")
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO execution_events(id, session_id, run_id, event_type, stage, data_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.id,
                        entity.session_id,
                        entity.run_id,
                        entity.event_type,
                        entity.stage,
                        _json(dict(entity.data)),
                        _iso(entity.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ImmutableEntityError(f"execution event is immutable or invalid: {exc}") from exc

    def get(self, entity_id: str) -> ExecutionEvent | None:
        row = self.db.connection.execute("SELECT * FROM execution_events WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["data"] = _loads(data.pop("data_json"), {})
        return ExecutionEvent.from_dict(data)

    def list(self, *, run_id: str | None = None) -> list[ExecutionEvent]:
        if run_id is None:
            rows = self.db.connection.execute("SELECT * FROM execution_events ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT * FROM execution_events WHERE run_id = ? ORDER BY created_at, id", (run_id,)
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["data"] = _loads(data.pop("data_json"), {})
            result.append(ExecutionEvent.from_dict(data))
        return result

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM execution_events WHERE id = ?", (entity_id,))


class ExecutionFileRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: ExecutionFile) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO run_files(id, run_id, filename, sha256, size, storage_ref, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.id,
                        entity.run_id,
                        entity.filename,
                        entity.sha256,
                        entity.size,
                        entity.storage_ref,
                        _iso(entity.created_at),
                    ),
                )
                for position, target_id in enumerate(entity.target_ids):
                    conn.execute(
                        "INSERT INTO run_file_targets(run_file_id, target_id, position) VALUES (?, ?, ?)",
                        (entity.id, target_id, position),
                    )
        except sqlite3.IntegrityError as exc:
            raise ImmutableEntityError(f"execution file is immutable or invalid: {exc}") from exc

    def get(self, entity_id: str) -> ExecutionFile | None:
        row = self.db.connection.execute("SELECT * FROM run_files WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        targets = [
            item["target_id"]
            for item in self.db.connection.execute(
                "SELECT target_id FROM run_file_targets WHERE run_file_id = ? ORDER BY position", (entity_id,)
            ).fetchall()
        ]
        data = dict(row)
        data["target_ids"] = targets
        return ExecutionFile.from_dict(data)

    def list(self, *, run_id: str | None = None) -> list[ExecutionFile]:
        if run_id is None:
            rows = self.db.connection.execute("SELECT id FROM run_files ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT id FROM run_files WHERE run_id = ? ORDER BY created_at, id", (run_id,)
            ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM run_files WHERE id = ?", (entity_id,))


class ExternalThreadLinkRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def save(self, entity: ExternalThreadLink) -> None:
        _reject_secret_mapping(entity.metadata, "external_thread_link.metadata")
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO external_thread_links(
                        id, provider, external_thread_id, session_id, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        provider=excluded.provider,
                        external_thread_id=excluded.external_thread_id,
                        session_id=excluded.session_id,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        entity.id,
                        entity.provider,
                        entity.external_thread_id,
                        entity.session_id,
                        _json(dict(entity.metadata)),
                        _iso(entity.created_at),
                        _iso(entity.updated_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise _integrity(exc) from exc

    def get(self, entity_id: str) -> ExternalThreadLink | None:
        row = self.db.connection.execute("SELECT * FROM external_thread_links WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["metadata"] = _loads(data.pop("metadata_json"), {})
        return ExternalThreadLink.from_dict(data)

    def get_by_external(self, provider: str, external_thread_id: str) -> ExternalThreadLink | None:
        row = self.db.connection.execute(
            "SELECT id FROM external_thread_links WHERE provider = ? AND external_thread_id = ?",
            (provider, external_thread_id),
        ).fetchone()
        return self.get(row["id"]) if row is not None else None

    def list(self, *, session_id: str | None = None) -> list[ExternalThreadLink]:
        if session_id is None:
            rows = self.db.connection.execute("SELECT id FROM external_thread_links ORDER BY created_at, id").fetchall()
        else:
            rows = self.db.connection.execute(
                "SELECT id FROM external_thread_links WHERE session_id = ? ORDER BY created_at, id", (session_id,)
            ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def delete(self, entity_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM external_thread_links WHERE id = ?", (entity_id,))


class SQLitePersistence:
    """Domain persistence facade. LangGraph checkpointers intentionally do not live here."""

    def __init__(self, path: str) -> None:
        self.db = SQLiteDatabase(path)
        self.sources = SourceRepository(self.db)
        self.agents = AgentRepository(self.db)
        self.workflows = WorkflowRepository(self.db)
        self.sessions = SessionRepository(self.db)
        self.runs = RunRepository(self.db)
        self.messages = MessageRepository(self.db)
        self.attachments = AttachmentRepository(self.db)
        self.artifacts = ArtifactRepository(self.db)
        self.revisions = RevisionRepository(self.db)
        self.events = ExecutionEventRepository(self.db)
        self.run_files = ExecutionFileRepository(self.db)
        self.external_thread_links = ExternalThreadLinkRepository(self.db)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SQLitePersistence":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
