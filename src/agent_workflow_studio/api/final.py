from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agent_workflow_studio.migration import LegacyWorkspaceError, LegacyWorkspaceImporter
from agent_workflow_studio.runtime.maintenance import BackupManager, cleanup_local_files

from .app import BackendContext, create_app as create_core_app


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
