from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.models import RunStatus, Workflow
from agent_workflow_studio.core.workflow import new_initial_run, new_session
from agent_workflow_studio.graph import (
    DurableGraphEngine,
    FunctionStageHandler,
    GraphStateValidationError,
    SQLiteGraphCheckpointer,
    StageResult,
    UserInputRequest,
    assert_checkpoint_safe,
    build_graph_state,
)
from agent_workflow_studio.persistence import DurableWorkflowService, LocalFileStore, PendingAttachment, SQLitePersistence


class LangGraphStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.domain_path = root / "domain.sqlite"
        self.checkpoint_path = root / "checkpoints.sqlite"
        self.file_root = root / "files"
        self.persistence = SQLitePersistence(self.domain_path)
        self.file_store = LocalFileStore(self.file_root)
        self.workflow = Workflow(id="w1", name="Generic test workflow")
        self.persistence.workflows.save(self.workflow)
        self.session = new_session(self.workflow, session_id="s1")
        self.persistence.sessions.save(self.session)
        self.initial = new_initial_run(self.session, run_id="r1")
        self.persistence.runs.save(self.initial)

    def tearDown(self) -> None:
        self.persistence.close()
        self.tempdir.cleanup()

    @staticmethod
    def _simple_handler(prefix: str = "done") -> FunctionStageHandler:
        return FunctionStageHandler(
            lambda state, stage, human: StageResult(
                output=f"{prefix}:{stage}:{human if human is not None else '-'}",
                artifact_ref=f"artifact://{state['run_id']}/{stage}",
                metadata={"stage": stage},
            )
        )

    def test_normal_run_persists_state_and_history_after_reopen(self) -> None:
        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine(
            {"a": self._simple_handler(), "b": self._simple_handler()},
            cp,
            persistence=self.persistence,
        )
        result = engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["a", "b"], user_request="go"))
        self.assertTrue(result.completed)
        self.assertEqual(result.state["completed_stages"], ["a", "b"])
        self.assertEqual(result.state["node_history"], ["a", "b"])
        self.assertEqual(self.persistence.runs.get("r1").status, RunStatus.COMPLETED)
        self.assertGreater(len(engine.get_history("r1")), 2)
        cp.close()

        reopened_cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        reopened = DurableGraphEngine(
            {"a": self._simple_handler(), "b": self._simple_handler()},
            reopened_cp,
            persistence=self.persistence,
        )
        restored = reopened.get_state("r1")
        self.assertEqual(restored["completed_stages"], ["a", "b"])
        self.assertEqual(restored["final_output"], "done:b:-")
        self.assertGreater(len(reopened.get_history("r1")), 2)
        reopened_cp.close()

    def test_worker_error_manual_resume_does_not_rerun_completed_stage(self) -> None:
        calls = {"a": 0, "b": 0}

        def first(state, stage, human):
            calls["a"] += 1
            return StageResult(output="A")

        def flaky(state, stage, human):
            calls["b"] += 1
            if calls["b"] == 1:
                raise RuntimeError("temporary worker failure")
            return StageResult(output="B")

        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine(
            {"a": FunctionStageHandler(first), "b": FunctionStageHandler(flaky)},
            cp,
            persistence=self.persistence,
        )
        paused = engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["a", "b"]))
        self.assertEqual(paused.status, RunStatus.PAUSED)
        self.assertEqual(paused.state["completed_stages"], ["a"])
        self.assertEqual(calls, {"a": 1, "b": 1})
        self.assertEqual(self.persistence.runs.get("r1").status, RunStatus.PAUSED)

        resumed = engine.resume_after_error("r1")
        self.assertTrue(resumed.completed)
        self.assertEqual(calls, {"a": 1, "b": 2})
        self.assertEqual(resumed.state["node_history"], ["a", "b"])
        self.assertEqual(set(resumed.state["stage_outputs"]), {"a", "b"})
        cp.close()

    def test_process_reopen_then_manual_resume_after_error(self) -> None:
        root = Path(self.tempdir.name)
        marker = root / "failure-seen"
        a_count = root / "a-count"

        def first(state, stage, human):
            count = int(a_count.read_text() or "0") if a_count.exists() else 0
            a_count.write_text(str(count + 1))
            return StageResult(output="A")

        def flaky(state, stage, human):
            if not marker.exists():
                marker.write_text("1")
                raise RuntimeError("fail once across process reopen")
            return StageResult(output="B")

        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine(
            {"a": FunctionStageHandler(first), "b": FunctionStageHandler(flaky)},
            cp,
            persistence=self.persistence,
        )
        paused = engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["a", "b"]))
        self.assertEqual(paused.status, RunStatus.PAUSED)
        cp.close()

        reopened_cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        reopened = DurableGraphEngine(
            {"a": FunctionStageHandler(first), "b": FunctionStageHandler(flaky)},
            reopened_cp,
            persistence=self.persistence,
        )
        self.assertEqual(self.persistence.runs.get("r1").status, RunStatus.PAUSED)
        self.assertEqual(reopened.get_state("r1")["completed_stages"], ["a"])
        completed = reopened.resume_after_error("r1")
        self.assertTrue(completed.completed)
        self.assertEqual(a_count.read_text(), "1")
        reopened_cp.close()

    def test_interrupt_and_resume_use_same_run_and_thread(self) -> None:
        captured = {}

        def request(state, stage):
            return UserInputRequest("Approve?", {"choice": "yes/no"})

        def execute(state, stage, human):
            captured["answer"] = human
            return StageResult(output=f"approved:{human}")

        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine(
            {"approval": FunctionStageHandler(execute, request)},
            cp,
            persistence=self.persistence,
        )
        waiting = engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["approval"]))
        self.assertEqual(waiting.status, RunStatus.WAITING_FOR_USER)
        self.assertEqual(waiting.thread_id, "r1")
        self.assertTrue(waiting.state["waiting_for_user"])
        self.assertEqual(waiting.state["interrupt_question"], "Approve?")
        self.assertEqual(waiting.interrupts[0]["stage"], "approval")
        self.assertEqual(self.persistence.runs.get("r1").status, RunStatus.WAITING_FOR_USER)

        done = engine.resume_with_user("r1", "yes")
        self.assertTrue(done.completed)
        self.assertEqual(done.thread_id, "r1")
        self.assertEqual(captured["answer"], "yes")
        self.assertEqual(done.state["human_answers"]["approval"], "yes")
        cp.close()

    def test_interrupt_does_not_auto_resume_after_reopen(self) -> None:
        calls = {"execute": 0}

        def request(state, stage):
            return UserInputRequest("Need value")

        def execute(state, stage, human):
            calls["execute"] += 1
            return StageResult(output=str(human))

        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine(
            {"ask": FunctionStageHandler(execute, request)}, cp, persistence=self.persistence
        )
        waiting = engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["ask"]))
        self.assertEqual(waiting.status, RunStatus.WAITING_FOR_USER)
        cp.close()

        reopened_cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        reopened = DurableGraphEngine(
            {"ask": FunctionStageHandler(execute, request)}, reopened_cp, persistence=self.persistence
        )
        restored = reopened.get_state("r1")
        self.assertTrue(restored["waiting_for_user"])
        self.assertEqual(calls["execute"], 0)
        self.assertEqual(self.persistence.runs.get("r1").status, RunStatus.WAITING_FOR_USER)
        completed = reopened.resume_with_user("r1", {"value": 42})
        self.assertTrue(completed.completed)
        self.assertEqual(calls["execute"], 1)
        reopened_cp.close()

    def test_completed_run_followup_uses_new_run_thread_and_attachment_refs(self) -> None:
        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine({"first": self._simple_handler()}, cp, persistence=self.persistence)
        initial_result = engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["first"]))
        self.assertTrue(initial_result.completed)

        durable = DurableWorkflowService(self.persistence, self.file_store)
        followup = durable.persist_followup(
            session_id="s1",
            previous_run_id="r1",
            content="revise with this file",
            uploads=[PendingAttachment(filename="evidence.txt", data=b"new evidence")],
            message_id="m2",
            run_id="r2",
        )
        seen_refs = []

        def follow_execute(state, stage, human):
            seen_refs.extend(state["follow_up_attachment_refs"])
            return StageResult(output="revised")

        follow_engine = DurableGraphEngine(
            {"revise": FunctionStageHandler(follow_execute)}, cp, persistence=self.persistence
        )
        result = follow_engine.start_followup(followup, stages=["revise"])
        self.assertTrue(result.completed)
        self.assertEqual(result.run_id, "r2")
        self.assertEqual(result.thread_id, "r2")
        self.assertEqual(result.state["follow_up_message"], "revise with this file")
        self.assertEqual(seen_refs, [followup.attachments[0].storage_ref])
        self.assertEqual(follow_engine.get_state("r1")["run_id"], "r1")
        self.assertEqual(follow_engine.get_state("r2")["run_id"], "r2")
        self.assertEqual(self.persistence.runs.get("r1").status, RunStatus.COMPLETED)
        self.assertEqual(self.persistence.runs.get("r2").status, RunStatus.COMPLETED)
        cp.close()

    def test_checkpoint_state_rejects_bytes_secrets_and_duplicate_stages(self) -> None:
        with self.assertRaises(GraphStateValidationError):
            assert_checkpoint_safe({"payload": b"raw file"})
        with self.assertRaises(GraphStateValidationError):
            assert_checkpoint_safe({"openai_api_key": "do-not-store"})
        with self.assertRaises(GraphStateValidationError):
            build_graph_state(session_id="s1", run_id="r1", stages=["same", "same"])

        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        self.assertTrue(cp.strict)
        unsafe = build_graph_state(session_id="s1", run_id="r1", stages=["a"])
        unsafe["raw_bytes"] = b"nope"  # type: ignore[typeddict-unknown-key]
        engine = DurableGraphEngine({"a": self._simple_handler()}, cp, persistence=self.persistence)
        with self.assertRaises(GraphStateValidationError):
            engine.start(unsafe)
        cp.close()

    def test_lifecycle_events_record_pause_resume_wait_and_completion(self) -> None:
        calls = {"b": 0}

        def flaky(state, stage, human):
            calls["b"] += 1
            if calls["b"] == 1:
                raise RuntimeError("once")
            return StageResult(output="done")

        cp = SQLiteGraphCheckpointer(self.checkpoint_path)
        engine = DurableGraphEngine({"b": FunctionStageHandler(flaky)}, cp, persistence=self.persistence)
        self.assertEqual(
            engine.start(build_graph_state(session_id="s1", run_id="r1", stages=["b"])).status,
            RunStatus.PAUSED,
        )
        self.assertTrue(engine.resume_after_error("r1").completed)
        event_types = [event.event_type for event in self.persistence.events.list(run_id="r1")]
        self.assertEqual(
            event_types,
            ["graph_started", "graph_paused_error", "graph_manual_resume", "graph_completed"],
        )
        cp.close()


if __name__ == "__main__":
    unittest.main()
