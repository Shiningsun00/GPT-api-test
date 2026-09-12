from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agent_workflow_studio.core.models import ExecutionFile, RunStatus
from agent_workflow_studio.core.workflow import new_initial_run
from agent_workflow_studio.migration import LegacyWorkspaceError, LegacyWorkspaceImporter
from agent_workflow_studio.runtime.maintenance import BackupManager, cleanup_local_files

from .app import (
    BackendContext,
    _graph_result_payload,
    _runtime_for_workflow,
    _workflow_for_session,
    _workflow_policy_label,
    create_app as create_core_app,
)


class CleanupPayload(BaseModel):
    apply: bool = False


def _root(context: BackendContext) -> Path:
    database_path = context.persistence.db.path
    if database_path == ":memory:":
        raise HTTPException(status_code=409, detail="maintenance requires file-backed local persistence")
    return Path(database_path).expanduser().resolve().parent


def create_app(context: BackendContext | None = None):
    ctx = context or BackendContext.local()
    app = create_core_app(ctx)
    app.title = "Agent Workflow Studio API"
    app.version = "2.0.0"

    @app.post("/runs/with-files", status_code=201)
    async def start_run_with_files(
        session_id: str = Form(...),
        user_request: str = Form(...),
        policy: str | None = Form(None),
        run_id: str | None = Form(None),
        target_ids: list[str] = Form(default=[]),
        files: list[UploadFile] = File(default=[]),
    ) -> dict[str, Any]:
        session, workflow = _workflow_for_session(ctx, session_id)
        stored_policy = _workflow_policy_label(workflow)
        if policy is not None and policy != stored_policy:
            raise HTTPException(
                status_code=409,
                detail=f"run policy override does not match stored workflow policy: requested={policy}, stored={stored_policy}",
            )
        if ctx.persistence.runs.list_active():
            raise HTTPException(status_code=409, detail="another active run already exists")

        # Resolve and validate the stored Workflow policy before persisting a Run or files.
        runtime = _runtime_for_workflow(ctx, workflow)
        run = new_initial_run(session, run_id=run_id)
        ctx.persistence.runs.save(run)
        stored = []
        execution_files: list[ExecutionFile] = []
        try:
            for upload in files:
                data = await upload.read()
                item = ctx.file_store.store_run_file(run.id, upload.filename or "attachment", data)
                stored.append(item)
                execution_file = ExecutionFile(
                    id=str(uuid4()),
                    run_id=run.id,
                    filename=upload.filename or "attachment",
                    sha256=item.sha256,
                    size=item.size,
                    storage_ref=item.storage_ref,
                    target_ids=tuple(dict.fromkeys(value for value in target_ids if value)),
                )
                ctx.persistence.run_files.save(execution_file)
                execution_files.append(execution_file)
            outcome = runtime.start_initial(run, user_request=user_request)
        except Exception:
            latest = ctx.persistence.runs.get(run.id)
            if latest is not None and latest.status == RunStatus.CREATED:
                ctx.persistence.runs.delete(run.id)
                for item in stored:
                    if item.created:
                        ctx.file_store.delete(item.storage_ref)
            raise
        payload = _graph_result_payload(outcome)
        payload["execution_files"] = [item.to_dict() for item in execution_files]
        return payload

    @app.get("/sessions/{session_id}/files")
    def list_session_files(session_id: str) -> list[dict[str, Any]]:
        if ctx.persistence.sessions.get(session_id) is None:
            raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
        run_ids = {item.id for item in ctx.persistence.runs.list(session_id=session_id)}
        return [item.to_dict() for item in ctx.persistence.run_files.list() if item.run_id in run_ids]

    @app.get("/maintenance/status")
    def maintenance_status() -> dict[str, Any]:
        root = _root(ctx)
        return {
            "version": "2.0.0",
            "data_root": str(root),
            "schema_version": ctx.persistence.db.schema_version,
            "counts": {
                "agents": len(ctx.persistence.agents.list()),
                "workflows": len(ctx.persistence.workflows.list()),
                "sessions": len(ctx.persistence.sessions.list()),
                "runs": len(ctx.persistence.runs.list()),
                "revisions": len(ctx.persistence.revisions.list()),
                "sources": len(ctx.persistence.sources.list()),
            },
            "active_runs": [item.id for item in ctx.persistence.runs.list_active()],
            "restore_mode": "offline_cli_only",
        }

    @app.post("/maintenance/backups", status_code=201)
    def create_backup() -> dict[str, object]:
        try:
            return BackupManager(_root(ctx)).create()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/maintenance/validate-backup")
    async def validate_backup(file: UploadFile = File(...)) -> dict[str, object]:
        data = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        try:
            return BackupManager(_root(ctx)).validate(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    @app.post("/maintenance/cleanup")
    def cleanup(payload: CleanupPayload) -> dict[str, object]:
        return cleanup_local_files(ctx.persistence, ctx.file_store, apply=payload.apply).to_dict()

    @app.post("/maintenance/import-workspace", status_code=201)
    async def import_workspace(
        file: UploadFile = File(...),
        conflict_policy: str = Form("fail"),
    ) -> dict[str, object]:
        if ctx.persistence.runs.list_active():
            raise HTTPException(status_code=409, detail="legacy import is blocked while a Run is active")
        data = await file.read()
        try:
            report = LegacyWorkspaceImporter(ctx.persistence, ctx.file_store).import_bytes(
                data,
                conflict_policy=conflict_policy,
            )
        except LegacyWorkspaceError as exc:
            message = str(exc)
            status = 409 if "already exists" in message else 422
            raise HTTPException(status_code=status, detail=message) from exc
        return report.to_dict()

    return app
