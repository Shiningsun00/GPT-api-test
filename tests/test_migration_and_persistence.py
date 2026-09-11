from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.models import Agent
from agent_workflow_studio.migration.workspace_v4 import legacy_agent_to_core, legacy_hierarchy_to_workflow
from agent_workflow_studio.persistence.memory import InMemoryRepository


class MigrationPersistenceTests(unittest.TestCase):
    def test_legacy_agent_does_not_embed_file_bytes(self) -> None:
        legacy = {"name": "A", "model": "gpt-5.6-luna", "rag_enabled": True, "rag_files": [{"name": "a.txt", "bytes": b"secret", "sha256": "abc", "size": 6}]}
        agent = legacy_agent_to_core("a1", legacy)
        data = agent.to_dict()
        self.assertEqual(agent.source_ids, ["file:abc"])
        self.assertNotIn("rag_files", data)
        self.assertNotIn("bytes", str(data))

    def test_legacy_hierarchy_preserves_duplicate_agent_slots(self) -> None:
        workflow = legacy_hierarchy_to_workflow({"manager_agent_id": "manager", "workers": [{"worker_id": "w1", "agent_id": "same"}, {"worker_id": "w2", "agent_id": "same"}]})
        self.assertEqual(len(workflow.hierarchy.workers), 2)
        self.assertEqual(workflow.hierarchy.workers[0].agent_id, workflow.hierarchy.workers[1].agent_id)

    def test_in_memory_repository(self) -> None:
        repo = InMemoryRepository[Agent]()
        agent = Agent(id="a1", name="A", model="m")
        repo.save(agent)
        loaded = repo.get("a1")
        self.assertEqual(loaded.id, "a1")
        loaded.name = "changed"
        self.assertEqual(repo.get("a1").name, "A")


if __name__ == "__main__":
    unittest.main()
