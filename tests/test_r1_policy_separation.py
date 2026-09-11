from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.models import Agent, Artifact, HierarchyConfig, WorkerSlot, Workflow, WorkflowMode
from agent_workflow_studio.core.workflow import new_initial_run, new_session, set_run_status
from agent_workflow_studio.core.models import RunStatus
from agent_workflow_studio.migration import CAREER_POLICY_ID, upgrade_confirmed_legacy_career_workflows
from agent_workflow_studio.persistence import CURRENT_SCHEMA_VERSION, SQLitePersistence, SecretPersistenceError
from agent_workflow_studio.persistence.schema import MIGRATIONS


class R1PolicySeparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "studio.db"
        self.persistence = SQLitePersistence(str(self.db_path))

    def tearDown(self) -> None:
        self.persistence.close()
        self.temp.cleanup()

    def reopen(self) -> None:
        self.persistence.close()
        self.persistence = SQLitePersistence(str(self.db_path))

    def _save_agent(self, agent_id: str, name: str) -> Agent:
        agent = Agent(id=agent_id, name=name, model="gpt-5.6-luna")
        self.persistence.agents.save(agent)
        return agent

    def test_new_workflow_is_generic_by_default_and_round_trips(self) -> None:
        manager = self._save_agent("manager", "Coordinator")
        worker_a = self._save_agent("worker-a", "Researcher")
        worker_b = self._save_agent("worker-b", "Reviewer")
        workflow = Workflow(
            id="generic-hierarchy",
            name="Manager plus two workers",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id=manager.id,
                workers=[
                    WorkerSlot(worker_id="slot-a", agent_id=worker_a.id),
                    WorkerSlot(worker_id="slot-b", agent_id=worker_b.id),
                ],
            ),
        )
        self.persistence.workflows.save(workflow)
        self.reopen()
        restored = self.persistence.workflows.get(workflow.id)
        self.assertIsNone(restored.policy_id)
        self.assertEqual(restored.policy_config, {})
        self.assertEqual([slot.agent_id for slot in restored.hierarchy.workers], [worker_a.id, worker_b.id])

    def test_career_role_binding_is_workflow_slot_metadata_not_agent_name(self) -> None:
        manager = self._save_agent("manager", "Coordinator")
        agents = [self._save_agent(f"agent-{index}", f"Reusable Agent {index}") for index in range(1, 7)]
        workers = [
            WorkerSlot(worker_id=f"career-slot-{index}", agent_id=agent.id)
            for index, agent in enumerate(agents, start=1)
        ]
        slot_roles = {slot.worker_id: f"W{index}" for index, slot in enumerate(workers, start=1)}
        workflow = Workflow(
            id="career-explicit",
            name="Career template",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(manager_agent_id=manager.id, workers=workers),
            policy_id=CAREER_POLICY_ID,
            policy_config={"slot_roles": slot_roles},
        )
        self.persistence.workflows.save(workflow)
        self.reopen()
        restored = self.persistence.workflows.get(workflow.id)
        self.assertEqual(restored.policy_id, CAREER_POLICY_ID)
        self.assertEqual(restored.policy_config["slot_roles"], slot_roles)
        self.assertTrue(all(not agent.name.startswith("W") for agent in agents))

    def test_policy_config_rejects_secret_like_fields(self) -> None:
        workflow = Workflow(
            id="bad-policy",
            name="Bad policy",
            policy_id="example",
            policy_config={"api_key": "must-not-persist"},
        )
        with self.assertRaises(SecretPersistenceError):
            self.persistence.workflows.save(workflow)

    def test_schema_v1_database_upgrades_to_v2_with_generic_default(self) -> None:
        self.persistence.close()
        self.db_path.unlink(missing_ok=True)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            for statement in MIGRATIONS[1]:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'legacy')")
            connection.execute("PRAGMA user_version = 1")
            connection.execute(
                "INSERT INTO workflows(id, name, mode, include_original_prompt, has_hierarchy, manager_agent_id, manager_planning_prompt, manager_synthesis_prompt, manager_routing_prompt, created_at, updated_at) VALUES ('legacy-generic', 'Legacy Generic', 'linear', 1, 0, NULL, '', '', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.commit()
        finally:
            connection.close()
        self.persistence = SQLitePersistence(str(self.db_path))
        self.assertEqual(self.persistence.db.schema_version, CURRENT_SCHEMA_VERSION)
        columns = {row["name"] for row in self.persistence.db.connection.execute("PRAGMA table_info(workflows)")}
        self.assertIn("policy_id", columns)
        self.assertIn("policy_config_json", columns)
        restored = self.persistence.workflows.get("legacy-generic")
        self.assertIsNone(restored.policy_id)
        self.assertEqual(restored.policy_config, {})
        self.persistence.db.initialize()
        self.assertEqual(self.persistence.db.schema_version, CURRENT_SCHEMA_VERSION)

    def test_confirmed_legacy_career_workflow_gets_conservative_upgrade(self) -> None:
        manager = self._save_agent("legacy-manager", "Manager")
        workers = []
        for index in range(1, 7):
            agent = self._save_agent(f"legacy-agent-{index}", f"W{index} Legacy Role")
            workers.append(WorkerSlot(worker_id=f"legacy-slot-{index}", agent_id=agent.id))
        career = Workflow(
            id="legacy-career",
            name="Legacy Career",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(manager_agent_id=manager.id, workers=workers),
        )
        self.persistence.workflows.save(career)
        session = new_session(career, session_id="legacy-career-session")
        self.persistence.sessions.save(session)
        run = set_run_status(new_initial_run(session, run_id="legacy-career-run"), RunStatus.COMPLETED)
        self.persistence.runs.save(run)
        kinds = ["intake", "analysis", "candidates", "selection_review", "strategy", "draft", "review"]
        for index, kind in enumerate(kinds, start=1):
            self.persistence.artifacts.save(
                Artifact(
                    id=f"legacy-artifact-{index}",
                    session_id=session.id,
                    run_id=run.id,
                    kind=kind,
                    producer=workers[min(index - 1, len(workers) - 1)].agent_id,
                    body=kind,
                    sequence=index,
                )
            )

        generic_lookalike = Workflow(id="w1-name-only", name="Not Career")
        self.persistence.workflows.save(generic_lookalike)

        upgraded = upgrade_confirmed_legacy_career_workflows(self.persistence)
        self.assertEqual(upgraded, (career.id,))
        restored = self.persistence.workflows.get(career.id)
        self.assertEqual(restored.policy_id, CAREER_POLICY_ID)
        self.assertEqual(
            restored.policy_config["slot_roles"],
            {f"legacy-slot-{index}": f"W{index}" for index in range(1, 7)},
        )
        self.assertIsNone(self.persistence.workflows.get(generic_lookalike.id).policy_id)
        self.assertEqual(upgrade_confirmed_legacy_career_workflows(self.persistence), ())


if __name__ == "__main__":
    unittest.main()
