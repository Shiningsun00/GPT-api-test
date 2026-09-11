from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.migration import LegacyWorkspaceError, LegacyWorkspaceImporter
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence


def build_workspace(*, schema_version: int = 4, bad_hash: bool = False, secret: str = "do-not-persist") -> bytes:
    evidence = b"verified legacy robot evidence"
    digest = hashlib.sha256(evidence).hexdigest()
    manifest = {
        "schema_version": schema_version,
        "app": "Agent Workflow Studio legacy",
        "api_key": secret,
        "agents": {
            "manager": {"id": "manager", "name": "Manager", "model": "fake"},
            "worker": {
                "id": "worker",
                "name": "Worker",
                "model": "fake",
                "rag_enabled": True,
                "rag_files": [
                    {
                        "name": "evidence.txt",
                        "sha256": ("0" * 64) if bad_hash else digest,
                        "size": len(evidence),
                    }
                ],
                "notion_enabled": True,
                "notion_sources": ["01234567-89ab-cdef-0123-456789abcdef"],
            },
        },
        "workflow": [],
        "include_original_prompt": True,
        "workflow_mode": "hierarchical",
        "hierarchy": {
            "manager_agent_id": "manager",
            "manager_planning_prompt": "plan",
            "manager_synthesis_prompt": "synthesize",
            "manager_routing_prompt": "route",
            "workers": [
                {"worker_id": "slot-a", "agent_id": "worker", "additional_prompt": "first"},
                {"worker_id": "slot-b", "agent_id": "worker", "additional_prompt": "second"},
            ],
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("rag_files/worker/evidence.txt", evidence)
    return output.getvalue()


class Step9MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.persistence = SQLitePersistence(str(self.root / "domain.sqlite"))
        self.files = LocalFileStore(self.root / "files")
        self.importer = LegacyWorkspaceImporter(self.persistence, self.files)

    def tearDown(self) -> None:
        self.persistence.close()
        self.tmp.cleanup()

    def test_schema_v4_import_preserves_rag_notion_and_duplicate_worker_slots(self) -> None:
        secret = "legacy-super-secret-value"
        report = self.importer.import_bytes(build_workspace(secret=secret))
        self.assertEqual(report.schema_version, 4)
        self.assertEqual(set(report.imported_agents), {"manager", "worker"})
        self.assertEqual(len(report.imported_workflows), 1)
        self.assertTrue(any("secret-like" in warning for warning in report.warnings))

        worker = self.persistence.agents.get("worker")
        self.assertIsNotNone(worker)
        self.assertTrue(worker.notion_enabled)
        self.assertEqual(worker.notion_sources, ["01234567-89ab-cdef-0123-456789abcdef"])
        self.assertEqual(len(worker.source_ids), 1)
        source = self.persistence.sources.get(worker.source_ids[0])
        self.assertIsNotNone(source)
        self.assertEqual(self.files.read(source.storage_ref), b"verified legacy robot evidence")

        workflow = self.persistence.workflows.get(report.imported_workflows[0])
        self.assertEqual([slot.worker_id for slot in workflow.hierarchy.workers], ["slot-a", "slot-b"])
        self.assertEqual([slot.agent_id for slot in workflow.hierarchy.workers], ["worker", "worker"])

        disk_bytes = (self.root / "domain.sqlite").read_bytes()
        wal = self.root / "domain.sqlite-wal"
        if wal.exists():
            disk_bytes += wal.read_bytes()
        self.assertNotIn(secret.encode(), disk_bytes)

    def test_all_supported_schema_versions_are_accepted(self) -> None:
        for version in (1, 2, 3, 4):
            with tempfile.TemporaryDirectory() as tmp:
                persistence = SQLitePersistence(str(Path(tmp) / "domain.sqlite"))
                try:
                    report = LegacyWorkspaceImporter(persistence, LocalFileStore(Path(tmp) / "files")).import_bytes(
                        build_workspace(schema_version=version)
                    )
                    self.assertEqual(report.schema_version, version)
                finally:
                    persistence.close()

    def test_conflict_policy_skip_is_idempotent(self) -> None:
        data = build_workspace()
        first = self.importer.import_bytes(data)
        second = self.importer.import_bytes(data, conflict_policy="skip")
        self.assertEqual(set(second.skipped_agents), {"manager", "worker"})
        self.assertEqual(second.imported_agents, ())
        self.assertEqual(second.imported_workflows, ())
        self.assertEqual(len(self.persistence.workflows.list()), len(first.imported_workflows))

    def test_bad_rag_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(LegacyWorkspaceError, "sha256 mismatch"):
            self.importer.import_bytes(build_workspace(bad_hash=True))

    def test_zip_path_traversal_is_rejected(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"schema_version": 4, "agents": {}}))
            archive.writestr("../escape.txt", "bad")
        with self.assertRaisesRegex(LegacyWorkspaceError, "unsafe ZIP path"):
            self.importer.import_bytes(output.getvalue())

    def test_unsupported_schema_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported workspace schema"):
            self.importer.import_bytes(build_workspace(schema_version=99))


if __name__ == "__main__":
    unittest.main()
