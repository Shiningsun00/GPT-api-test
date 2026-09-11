from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.models import (
    Agent,
    Artifact,
    ExecutionFile,
    HierarchyConfig,
    LinearStep,
    ReferenceSource,
    ReferenceSourceKind,
    Revision,
    Run,
    RunKind,
    RunStatus,
    WorkerSlot,
    Workflow,
    WorkflowMode,
)
from agent_workflow_studio.core.workflow import new_initial_run, new_session, set_run_status
from agent_workflow_studio.persistence import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_TABLES,
    DurableWorkflowService,
    ExecutionEvent,
    ExternalThreadLink,
    ImmutableEntityError,
    LocalFileStore,
    PendingAttachment,
    PersistenceConflictError,
    SQLitePersistence,
    SecretPersistenceError,
)


class SQLitePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = root / "studio.db"
        self.files_root = root / "files"
        self.persistence = SQLitePersistence(str(self.db_path))
        self.file_store = LocalFileStore(self.files_root)

    def tearDown(self) -> None:
        self.persistence.close()
        self.temp.cleanup()

    def reopen(self) -> None:
        self.persistence.close()
        self.persistence = SQLitePersistence(str(self.db_path))

    def seed_base(self) -> tuple[Workflow, object, Run]:
        stored = self.file_store.store_source(b"permanent evidence")
        source = ReferenceSource(
            id="src-1",
            kind=ReferenceSourceKind.FILE,
            label="evidence.txt",
            sha256=stored.sha256,
            storage_ref=stored.storage_ref,
        )
        self.persistence.sources.save(source)
        agent = Agent(
            id="agent-1",
            name="Writer",
            model="gpt-5.6-luna",
            system_prompt="Use evidence",
            rag_enabled=True,
            source_ids=[source.id],
        )
        self.persistence.agents.save(agent)
        workflow = Workflow(id="workflow-1", name="Linear")
        self.persistence.workflows.save(workflow)
        session = new_session(workflow, session_id="session-1", title="test")
        self.persistence.sessions.save(session)
        completed = set_run_status(new_initial_run(session, run_id="run-1"), RunStatus.COMPLETED)
        self.persistence.runs.save(completed)
        return workflow, session, completed

    def test_schema_is_versioned_idempotent_and_has_required_tables(self) -> None:
        self.assertEqual(self.persistence.db.schema_version, CURRENT_SCHEMA_VERSION)
        self.assertTrue(REQUIRED_TABLES.issubset(self.persistence.db.table_names()))
        self.assertNotIn("checkpoints", self.persistence.db.table_names())
        self.persistence.db.initialize()
        self.assertEqual(self.persistence.db.schema_version, CURRENT_SCHEMA_VERSION)
        schema_sql = "\n".join(
            str(row["sql"] or "")
            for row in self.persistence.db.connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        )
        self.assertNotIn(" BLOB", schema_sql.upper())

    def test_agent_source_and_workflow_round_trip_after_reopen(self) -> None:
        stored = self.file_store.store_source(b"reference bytes")
        source = ReferenceSource(
            id="source-A",
            kind=ReferenceSourceKind.FILE,
            label="reference.pdf",
            sha256=stored.sha256,
            storage_ref=stored.storage_ref,
        )
        self.persistence.sources.save(source)
        manager = Agent(id="manager", name="Manager", model="gpt-5.6-luna")
        worker = Agent(id="worker", name="Worker", model="gpt-5.6-luna", source_ids=[source.id], rag_enabled=True)
        self.persistence.agents.save(manager)
        self.persistence.agents.save(worker)
        workflow = Workflow(
            id="hierarchy",
            name="Hierarchy",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id=manager.id,
                manager_planning_prompt="plan",
                manager_synthesis_prompt="synthesize",
                manager_routing_prompt="route",
                workers=[
                    WorkerSlot(worker_id="slot-1", agent_id=worker.id, additional_prompt="A"),
                    WorkerSlot(worker_id="slot-2", agent_id=worker.id, additional_prompt="B"),
                ],
            ),
        )
        self.persistence.workflows.save(workflow)
        linear = Workflow(
            id="linear-with-step",
            name="Linear with step",
            steps=[LinearStep(step_id="step-1", agent_id=worker.id, additional_prompt="do it")],
        )
        self.persistence.workflows.save(linear)

        self.reopen()
        restored_agent = self.persistence.agents.get(worker.id)
        restored_workflow = self.persistence.workflows.get(workflow.id)
        restored_linear = self.persistence.workflows.get(linear.id)
        self.assertEqual(restored_agent.source_ids, [source.id])
        self.assertEqual(self.persistence.sources.list_for_agent(worker.id)[0].storage_ref, stored.storage_ref)
        self.assertEqual(restored_linear.steps[0].agent_id, worker.id)
        self.assertEqual(restored_linear.steps[0].additional_prompt, "do it")
        self.assertEqual(len(restored_workflow.hierarchy.workers), 2)
        self.assertEqual(restored_workflow.hierarchy.workers[0].agent_id, restored_workflow.hierarchy.workers[1].agent_id)
        self.assertNotEqual(restored_workflow.hierarchy.workers[0].worker_id, restored_workflow.hierarchy.workers[1].worker_id)
        self.assertEqual(self.file_store.read(stored.storage_ref), b"reference bytes")

    def test_followup_message_attachment_and_continuation_run_are_durable(self) -> None:
        _, session, completed = self.seed_base()
        service = DurableWorkflowService(self.persistence, self.file_store)
        result = service.persist_followup(
            session_id=session.id,
            previous_run_id=completed.id,
            content="Revise using this evidence",
            uploads=[PendingAttachment(filename="followup.txt", data=b"new evidence", mime_type="text/plain")],
            message_id="message-2",
            run_id="run-2",
        )
        self.assertEqual(result.run.kind, RunKind.CONTINUATION)
        self.assertEqual(result.run.parent_run_id, completed.id)
        self.assertEqual(result.run.trigger_message_id, result.message.id)
        self.assertEqual(self.persistence.runs.get(completed.id).status, RunStatus.COMPLETED)

        self.reopen()
        restored_run = self.persistence.runs.get("run-2")
        restored_message = self.persistence.messages.get("message-2")
        restored_attachment = self.persistence.attachments.get(restored_message.attachment_ids[0])
        self.assertEqual(restored_run.session_id, session.id)
        self.assertEqual(restored_run.status, RunStatus.CREATED)
        self.assertEqual(restored_message.run_id, restored_run.id)
        self.assertEqual(restored_attachment.scope.value, "turn")
        self.assertEqual(self.file_store.read(restored_attachment.storage_ref), b"new evidence")
        self.assertEqual(len(self.persistence.runs.list(session_id=session.id)), 2)

    def test_outer_transaction_rolls_back_nested_repository_write(self) -> None:
        workflow = Workflow(id="workflow-rb", name="Rollback")
        self.persistence.workflows.save(workflow)
        session = new_session(workflow, session_id="session-rb")
        with self.assertRaises(RuntimeError):
            with self.persistence.db.transaction():
                self.persistence.sessions.save(session)
                raise RuntimeError("force rollback")
        self.assertIsNone(self.persistence.sessions.get(session.id))

    def test_artifacts_dependencies_and_revisions_are_immutable_and_rehydrate(self) -> None:
        _, session, completed = self.seed_base()
        strategy = Artifact(
            id="artifact-strategy",
            session_id=session.id,
            run_id=completed.id,
            kind="strategy",
            producer="worker-3",
            body="strategy",
        )
        draft = Artifact(
            id="artifact-draft",
            session_id=session.id,
            run_id=completed.id,
            kind="draft",
            producer="worker-4",
            body="draft",
            dependencies=(strategy.id,),
            metadata={"token_usage": {"input": 10, "output": 20}},
            sequence=2,
        )
        self.persistence.artifacts.save(strategy)
        self.persistence.artifacts.save(draft)
        revision = Revision(
            id="revision-1",
            session_id=session.id,
            run_id=completed.id,
            version=1,
            final_output="final",
            artifact_ids=(draft.id,),
        )
        self.persistence.revisions.save(revision)
        with self.assertRaises(ImmutableEntityError):
            self.persistence.artifacts.save(replace(draft, body="changed"))
        with self.assertRaises(ImmutableEntityError):
            self.persistence.revisions.save(replace(revision, final_output="changed"))

        self.reopen()
        self.assertEqual(self.persistence.artifacts.get(draft.id).dependencies, (strategy.id,))
        self.assertEqual(self.persistence.revisions.get(revision.id).artifact_ids, (draft.id,))

    def test_run_events_files_targets_and_external_link_round_trip(self) -> None:
        _, session, completed = self.seed_base()
        event = ExecutionEvent(
            id="event-1",
            session_id=session.id,
            run_id=completed.id,
            event_type="worker_completed",
            stage="draft",
            data={"token_usage": {"input": 5}},
        )
        self.persistence.events.save(event)
        stored = self.file_store.store_run_file(completed.id, "input.csv", b"a,b\n1,2")
        run_file = ExecutionFile(
            id="run-file-1",
            run_id=completed.id,
            filename="input.csv",
            sha256=stored.sha256,
            size=stored.size,
            storage_ref=stored.storage_ref,
            target_ids=("slot-1", "slot-2"),
        )
        self.persistence.run_files.save(run_file)
        link = ExternalThreadLink(
            id="link-1",
            provider="discord",
            external_thread_id="thread-123",
            session_id=session.id,
            metadata={"channel_id": "channel-1"},
        )
        self.persistence.external_thread_links.save(link)

        self.reopen()
        self.assertEqual(self.persistence.events.get(event.id).stage, "draft")
        self.assertEqual(self.persistence.run_files.get(run_file.id).target_ids, ("slot-1", "slot-2"))
        self.assertEqual(
            self.persistence.external_thread_links.get_by_external("discord", "thread-123").session_id,
            session.id,
        )

    def test_secret_like_metadata_is_rejected_but_token_usage_is_allowed(self) -> None:
        _, session, completed = self.seed_base()
        self.persistence.events.save(
            ExecutionEvent(
                id="event-safe",
                session_id=session.id,
                run_id=completed.id,
                event_type="usage",
                data={"token_usage": {"input": 1}},
            )
        )
        with self.assertRaises(SecretPersistenceError):
            self.persistence.events.save(
                ExecutionEvent(
                    id="event-secret",
                    session_id=session.id,
                    run_id=completed.id,
                    event_type="bad",
                    data={"api_key": "should-never-persist"},
                )
            )
        forbidden_columns = {
            "api_key", "openai_api_key", "notion_api_key", "discord_token", "access_token", "refresh_token", "password", "secret"
        }
        for table in self.persistence.db.table_names():
            columns = {
                str(row["name"]).lower()
                for row in self.persistence.db.connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            self.assertTrue(columns.isdisjoint(forbidden_columns), f"secret column found in {table}: {columns & forbidden_columns}")

    def test_terminal_run_cannot_be_reactivated_and_single_active_run_is_enforced(self) -> None:
        workflow, session, completed = self.seed_base()
        with self.assertRaises(PersistenceConflictError):
            self.persistence.runs.save(replace(completed, status=RunStatus.RUNNING, completed_at=None))

        active = Run(id="active-1", session_id=session.id, workflow_id=workflow.id, status=RunStatus.CREATED)
        self.persistence.runs.save(active)
        second_session = new_session(workflow, session_id="session-2")
        self.persistence.sessions.save(second_session)
        second_active = Run(id="active-2", session_id=second_session.id, workflow_id=workflow.id, status=RunStatus.CREATED)
        with self.assertRaises(PersistenceConflictError):
            self.persistence.runs.save(second_active)


if __name__ == "__main__":
    unittest.main()
