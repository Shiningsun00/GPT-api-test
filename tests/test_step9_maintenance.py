from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
import unittest
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
from agent_workflow_studio.runtime import (
    BackupManager,
    RuntimeLock,
    RuntimeLockError,
    cleanup_local_files,
    configure_rotating_logging,
)
from agent_workflow_studio.runtime.server import create_product_app


class FakeProvider:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        self.inputs.append(input_text)
        if "Route the follow-up only" in input_text:
            return ModelResponse(text='{"stages":["w4_draft"]}')
        if "Act as the final editor and routing manager" in input_text:
            return ModelResponse(text="MANAGER FINAL")
        return ModelResponse(text=f"{instructions.split()[0] if instructions else model} OUTPUT")


class Step9MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.persistence = SQLitePersistence(str(self.root / "domain.sqlite"))
        self.checkpointer = SQLiteGraphCheckpointer(self.root / "graph.sqlite")
        self.files = LocalFileStore(self.root / "files")

    def tearDown(self) -> None:
        self.checkpointer.close()
        self.persistence.close()
        self.tmp.cleanup()

    def test_backup_validate_restore_and_offline_lock(self) -> None:
        stored = self.files.store_source(b"durable source")
        source = ReferenceSource(
            id=f"file:{stored.sha256}",
            kind=ReferenceSourceKind.FILE,
            label="source.txt",
            sha256=stored.sha256,
            storage_ref=stored.storage_ref,
        )
        self.persistence.sources.save(source)
        self.persistence.agents.save(Agent(id="agent", name="Agent", model="fake", source_ids=[source.id]))

        manager = BackupManager(self.root)
        backup = manager.create()
        self.assertTrue(backup["validation"]["valid"])
        archive = Path(backup["path"])
        self.assertTrue(archive.exists())

        restored_root = self.root / "restored"
        result = manager.restore(archive, restored_root)
        self.assertTrue(result["restored"])
        reopened = SQLitePersistence(str(restored_root / "domain.sqlite"))
        try:
            agent = reopened.agents.get("agent")
            self.assertIsNotNone(agent)
            restored_source = reopened.sources.get(agent.source_ids[0])
            self.assertEqual(LocalFileStore(restored_root / "files").read(restored_source.storage_ref), b"durable source")
        finally:
            reopened.close()

        locked_target = self.root / "locked"
        locked_target.mkdir()
        lock = RuntimeLock(locked_target).acquire()
        try:
            with self.assertRaises(RuntimeLockError):
                manager.restore(archive, locked_target, overwrite=True)
        finally:
            lock.release()

    def test_cleanup_is_dry_run_by_default_and_preserves_referenced_files(self) -> None:
        protected = self.files.store_source(b"keep")
        self.persistence.sources.save(
            ReferenceSource(
                id=f"file:{protected.sha256}",
                kind=ReferenceSourceKind.FILE,
                label="keep.txt",
                sha256=protected.sha256,
                storage_ref=protected.storage_ref,
            )
        )
        orphan = self.files.store_run_file("orphan-run", "orphan.txt", b"delete me")
        dry = cleanup_local_files(self.persistence, self.files)
        self.assertIn(orphan.storage_ref, dry.candidates)
        self.assertNotIn(protected.storage_ref, dry.candidates)
        self.assertTrue(self.files.resolve(orphan.storage_ref).exists())
        applied = cleanup_local_files(self.persistence, self.files, apply=True)
        self.assertEqual(applied.deleted_count, 1)
        self.assertFalse(self.files.resolve(orphan.storage_ref).exists())
        self.assertTrue(self.files.resolve(protected.storage_ref).exists())

    def test_rotating_log_redacts_known_and_token_shaped_secrets(self) -> None:
        secret = "top-secret-value-123"
        logger = configure_rotating_logging(self.root / "logs", secret_values=[secret], max_bytes=180, backup_count=2)
        for _ in range(20):
            logger.info("secret=%s authorization=Bearer abcdefghijklmnop sk-abcdefghijklmno", secret)
        for handler in logger.handlers:
            handler.flush()
        texts = "\n".join(path.read_text(encoding="utf-8") for path in (self.root / "logs").glob("studio.log*"))
        self.assertIn("[REDACTED]", texts)
        self.assertNotIn(secret, texts)
        self.assertNotIn("sk-abcdefghijklmno", texts)
        self.assertGreaterEqual(len(list((self.root / "logs").glob("studio.log*"))), 2)

    def _seed_career(self, client: TestClient) -> None:
        self.assertEqual(client.post("/agents", json={"id": "manager", "name": "Manager", "model": "fake"}).status_code, 201)
        for i in range(1, 7):
            self.assertEqual(client.post("/agents", json={"id": f"agent-w{i}", "name": f"W{i} worker", "model": "fake", "system_prompt": f"W{i} prompt"}).status_code, 201)
        response = client.post(
            "/workflows",
            json={
                "id": "career",
                "name": "Career",
                "mode": "hierarchical",
                "hierarchy": {
                    "manager_agent_id": "manager",
                    "workers": [{"worker_id": f"slot-w{i}", "agent_id": f"agent-w{i}"} for i in range(1, 7)],
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(client.post("/sessions", json={"id": "session-1", "workflow_id": "career"}).status_code, 201)

    def test_final_api_supports_initial_files_and_maintenance(self) -> None:
        provider = FakeProvider()
        context = BackendContext(
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            file_store=self.files,
            provider=provider,
            owns_resources=False,
        )
        with TestClient(create_app(context)) as client:
            self._seed_career(client)
            result = client.post(
                "/runs/with-files",
                data={"session_id": "session-1", "user_request": "Write using verified evidence."},
                files={"files": ("initial.txt", b"VERIFIED INITIAL EVIDENCE", "text/plain")},
            )
            self.assertEqual(result.status_code, 201, result.text)
            payload = result.json()
            self.assertEqual(payload["status"], "COMPLETED")
            self.assertEqual(len(payload["execution_files"]), 1)
            self.assertTrue(any("VERIFIED INITIAL EVIDENCE" in value for value in provider.inputs))
            files = client.get("/sessions/session-1/files").json()
            self.assertEqual(len(files), 1)

            status = client.get("/maintenance/status")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["version"], "2.0.0")
            backup = client.post("/maintenance/backups")
            self.assertEqual(backup.status_code, 201, backup.text)
            self.assertTrue(backup.json()["validation"]["valid"])
            cleanup = client.post("/maintenance/cleanup", json={"apply": False})
            self.assertEqual(cleanup.status_code, 200)
            self.assertFalse(cleanup.json()["apply"])

    def test_product_shell_mounts_api_under_api_prefix(self) -> None:
        context = BackendContext(
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            file_store=self.files,
            provider=FakeProvider(),
            owns_resources=False,
        )
        with TestClient(create_product_app(context)) as client:
            self.assertEqual(client.get("/health").json()["version"], "2.0.0")
            self.assertEqual(client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
