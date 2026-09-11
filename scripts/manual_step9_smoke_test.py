from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient

from agent_workflow_studio.api import BackendContext, create_app
from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.models import Agent, ReferenceSource, ReferenceSourceKind
from agent_workflow_studio.graph import SQLiteGraphCheckpointer
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence
from agent_workflow_studio.runtime import BackupManager, cleanup_local_files


class FakeProvider:
    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        if "Route the follow-up only" in input_text:
            return ModelResponse(text='{"stages":["w4_draft"]}')
        if "Act as the final editor and routing manager" in input_text:
            return ModelResponse(text="MANAGER FINAL")
        return ModelResponse(text=f"{instructions.split()[0] if instructions else model} OUTPUT")


def legacy_zip() -> bytes:
    evidence = b"legacy source evidence"
    digest = hashlib.sha256(evidence).hexdigest()
    manifest = {
        "schema_version": 4,
        "agents": {
            "legacy-agent": {
                "id": "legacy-agent",
                "name": "Legacy Agent",
                "model": "fake",
                "rag_enabled": True,
                "rag_files": [{"name": "legacy.txt", "sha256": digest, "size": len(evidence)}],
            }
        },
        "workflow": [],
        "hierarchy": {},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("rag_files/legacy-agent/legacy.txt", evidence)
    return output.getvalue()


def seed_career(client: TestClient) -> None:
    assert client.post("/agents", json={"id": "manager", "name": "Manager", "model": "fake"}).status_code == 201
    for i in range(1, 7):
        assert client.post("/agents", json={"id": f"agent-w{i}", "name": f"W{i} worker", "model": "fake", "system_prompt": f"W{i} prompt"}).status_code == 201
    assert client.post(
        "/workflows",
        json={
            "id": "career",
            "name": "Career",
            "mode": "hierarchical",
            "hierarchy": {"manager_agent_id": "manager", "workers": [{"worker_id": f"slot-w{i}", "agent_id": f"agent-w{i}"} for i in range(1, 7)]},
        },
    ).status_code == 201
    assert client.post("/sessions", json={"id": "session-1", "workflow_id": "career"}).status_code == 201


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        persistence = SQLitePersistence(str(root / "domain.sqlite"))
        checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        files = LocalFileStore(root / "files")
        context = BackendContext(persistence=persistence, checkpointer=checkpointer, file_store=files, provider=FakeProvider(), owns_resources=False)
        with TestClient(create_app(context)) as client:
            print("[1/5] Initial Run + execution file")
            seed_career(client)
            response = client.post(
                "/runs/with-files",
                data={"session_id": "session-1", "user_request": "Use the attached evidence."},
                files={"files": ("initial.txt", b"initial verified file", "text/plain")},
            )
            assert response.status_code == 201, response.text
            assert response.json()["status"] == "COMPLETED"
            assert len(client.get("/sessions/session-1/files").json()) == 1
            print("      PASS")

            print("[2/5] Live SQLite + files backup")
            backup = client.post("/maintenance/backups")
            assert backup.status_code == 201, backup.text
            archive = Path(backup.json()["path"])
            assert BackupManager(root).validate(archive)["valid"]
            print("      PASS")

            print("[3/5] Legacy Workspace import")
            imported = client.post(
                "/maintenance/import-workspace",
                data={"conflict_policy": "fail"},
                files={"file": ("agent_workspace.zip", legacy_zip(), "application/zip")},
            )
            assert imported.status_code == 201, imported.text
            assert "legacy-agent" in imported.json()["imported_agents"]
            print("      PASS")

            print("[4/5] Safe cleanup dry-run")
            orphan = files.store_run_file("orphan", "orphan.txt", b"orphan")
            dry = cleanup_local_files(persistence, files)
            assert orphan.storage_ref in dry.candidates
            assert files.resolve(orphan.storage_ref).exists()
            print("      PASS")

            print("[5/5] Restore into fresh stopped data root")
            restored = root / "restored"
            BackupManager(root).restore(archive, restored)
            reopened = SQLitePersistence(str(restored / "domain.sqlite"))
            try:
                assert reopened.sessions.get("session-1") is not None
                assert reopened.revisions.list(session_id="session-1")
            finally:
                reopened.close()
            print("      PASS")

        checkpointer.close()
        persistence.close()
    print("\nSTEP 9 MAINTENANCE SMOKE TEST = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
