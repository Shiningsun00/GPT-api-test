from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.models import (
    Agent,
    ExecutionFile,
    HierarchyConfig,
    LinearStep,
    RunStatus,
    WorkerSlot,
    Workflow,
    WorkflowMode,
)
from agent_workflow_studio.core.workflow import new_initial_run, new_session
from agent_workflow_studio.graph import GenericWorkflowRuntime, SQLiteGraphCheckpointer
from agent_workflow_studio.persistence import LocalFileStore, PendingAttachment, SQLitePersistence


class ScriptedProvider:
    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict[str, str]] = []

    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        call = {"model": model, "instructions": instructions, "input_text": input_text}
        self.calls.append(call)
        value = self.responder(call, len(self.calls))
        if isinstance(value, Exception):
            raise value
        return ModelResponse(text=str(value), usage={"input_tokens": 1, "output_tokens": 1})


class R2GenericRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.persistence = SQLitePersistence(str(root / "domain.sqlite"))
        self.checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        self.files = LocalFileStore(root / "files")

    def tearDown(self) -> None:
        self.checkpointer.close()
        self.persistence.close()
        self.temp.cleanup()

    def _save_agent(self, agent_id: str, name: str, system_prompt: str) -> Agent:
        agent = Agent(
            id=agent_id,
            name=name,
            model="test-model",
            system_prompt=system_prompt,
        )
        self.persistence.agents.save(agent)
        return agent

    def _seed_run(self, workflow: Workflow, *, run_id: str = "run-1"):
        self.persistence.workflows.save(workflow)
        session = new_session(workflow, session_id="session-1", title="generic test")
        self.persistence.sessions.save(session)
        run = new_initial_run(session, run_id=run_id)
        self.persistence.runs.save(run)
        return session, run

    def test_generic_linear_arbitrary_agents_and_names(self) -> None:
        self._save_agent("a-research", "Researcher", "research-system")
        self._save_agent("a-review", "Quality Reviewer", "review-system")
        workflow = Workflow(
            id="wf-linear",
            name="Arbitrary Linear",
            mode=WorkflowMode.LINEAR,
            steps=[
                LinearStep("collect", "a-research", "Collect evidence"),
                LinearStep("review", "a-review", "Review the result"),
            ],
        )
        session, run = self._seed_run(workflow)

        def respond(call, _index):
            if call["instructions"] == "research-system":
                self.assertIn("generic task", call["input_text"])
                return "research result"
            if call["instructions"] == "review-system":
                self.assertIn("research result", call["input_text"])
                return "reviewed final"
            raise AssertionError(call)

        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=ScriptedProvider(respond),
            file_store=self.files,
        )
        outcome = runtime.start_initial(run, user_request="generic task")
        self.assertEqual(outcome.graph.status, RunStatus.COMPLETED)
        self.assertEqual(outcome.graph.state["node_history"], ["collect", "review"])
        self.assertEqual(outcome.revision.final_output, "reviewed final")
        artifacts = self.persistence.artifacts.list(run_id=run.id)
        self.assertEqual([item.producer for item in artifacts], ["a-research", "a-review"])
        self.assertEqual(artifacts[1].dependencies, (artifacts[0].id,))
        self.assertEqual(self.persistence.runs.get(run.id).status, RunStatus.COMPLETED)
        self.assertEqual(outcome.revision.session_id, session.id)

    def test_generic_hierarchy_manager_two_arbitrary_workers(self) -> None:
        self._save_agent("manager", "Coordinator", "manager-system")
        self._save_agent("research", "Researcher", "research-system")
        self._save_agent("review", "Reviewer", "review-system")
        workflow = Workflow(
            id="wf-hierarchy",
            name="Manager plus two workers",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id="manager",
                manager_planning_prompt="Plan only what is necessary.",
                workers=[
                    WorkerSlot("research-slot", "research", "Research carefully"),
                    WorkerSlot("review-slot", "review", "Review critically"),
                ],
            ),
        )
        _session, run = self._seed_run(workflow)
        manager_calls = 0

        def respond(call, _index):
            nonlocal manager_calls
            if call["instructions"] == "manager-system":
                manager_calls += 1
                if manager_calls == 1:
                    self.assertIn("research-slot", call["input_text"])
                    self.assertIn("review-slot", call["input_text"])
                    return json.dumps(
                        {
                            "action": "delegate",
                            "assignments": [
                                {"worker_id": "research-slot", "instruction": "Find facts"},
                                {"worker_id": "review-slot", "instruction": "Check the facts"},
                            ],
                        }
                    )
                self.assertIn("research evidence", call["input_text"])
                self.assertIn("review verdict", call["input_text"])
                return json.dumps({"action": "final", "final": "generic manager final"})
            if call["instructions"] == "research-system":
                return "research evidence"
            if call["instructions"] == "review-system":
                self.assertIn("research evidence", call["input_text"])
                return "review verdict"
            raise AssertionError(call)

        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=ScriptedProvider(respond),
            file_store=self.files,
        )
        outcome = runtime.start_initial(run, user_request="Analyze an arbitrary topic")
        self.assertEqual(outcome.graph.status, RunStatus.COMPLETED)
        self.assertEqual(outcome.revision.final_output, "generic manager final")
        self.assertEqual(manager_calls, 2)
        history = outcome.graph.state["node_history"]
        self.assertEqual(history[0], "manager:0")
        self.assertIn("worker:0:0:research-slot", history)
        self.assertIn("worker:0:1:review-slot", history)
        self.assertEqual(history[-1], "manager:1")
        artifacts = self.persistence.artifacts.list(run_id=run.id)
        self.assertEqual([item.metadata["worker_id"] for item in artifacts], ["research-slot", "review-slot"])
        self.assertFalse(any(name.startswith("W") for name in ["Coordinator", "Researcher", "Reviewer"]))

    def test_duplicate_agent_can_fill_distinct_worker_slots(self) -> None:
        self._save_agent("manager", "Manager", "manager-system")
        self._save_agent("shared", "Reusable Specialist", "shared-system")
        workflow = Workflow(
            id="wf-duplicate-slot",
            name="Duplicate Agent Slots",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id="manager",
                workers=[
                    WorkerSlot("slot-a", "shared", "Perspective A"),
                    WorkerSlot("slot-b", "shared", "Perspective B"),
                ],
            ),
        )
        _session, run = self._seed_run(workflow)
        manager_calls = 0

        def respond(call, _index):
            nonlocal manager_calls
            if call["instructions"] == "manager-system":
                manager_calls += 1
                if manager_calls == 1:
                    return json.dumps(
                        {
                            "action": "delegate",
                            "assignments": [
                                {"worker_id": "slot-a", "instruction": "A"},
                                {"worker_id": "slot-b", "instruction": "B"},
                            ],
                        }
                    )
                return json.dumps({"action": "final", "final": "combined"})
            if call["instructions"] == "shared-system":
                return "shared worker output"
            raise AssertionError(call)

        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=ScriptedProvider(respond),
            file_store=self.files,
        )
        outcome = runtime.start_initial(run, user_request="Use two perspectives")
        self.assertEqual(outcome.graph.status, RunStatus.COMPLETED)
        artifacts = self.persistence.artifacts.list(run_id=run.id)
        self.assertEqual([item.producer for item in artifacts], ["shared", "shared"])
        self.assertEqual({item.metadata["worker_id"] for item in artifacts}, {"slot-a", "slot-b"})

    def test_manager_needs_input_resumes_same_run_and_thread(self) -> None:
        self._save_agent("manager", "Clarifying Manager", "manager-system")
        workflow = Workflow(
            id="wf-hitl",
            name="Manager HITL",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(manager_agent_id="manager", workers=[]),
        )
        _session, run = self._seed_run(workflow)
        manager_calls = 0

        def respond(call, _index):
            nonlocal manager_calls
            manager_calls += 1
            if manager_calls == 1:
                return json.dumps({"action": "needs_input", "question": "Which audience?"})
            self.assertIn("executives", call["input_text"])
            return json.dumps({"action": "final", "final": "audience-aware result"})

        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=ScriptedProvider(respond),
            file_store=self.files,
        )
        waiting = runtime.start_initial(run, user_request="Write a summary")
        self.assertEqual(waiting.graph.status, RunStatus.WAITING_FOR_USER)
        self.assertEqual(waiting.graph.thread_id, run.id)
        self.assertEqual(waiting.graph.interrupts[0]["question"], "Which audience?")

        completed = runtime.resume_with_user(run.id, "executives")
        self.assertEqual(completed.graph.status, RunStatus.COMPLETED)
        self.assertEqual(completed.graph.run_id, run.id)
        self.assertEqual(completed.graph.thread_id, run.id)
        self.assertEqual(completed.revision.final_output, "audience-aware result")
        self.assertEqual(len(self.persistence.runs.list(session_id=run.session_id)), 1)

    def test_worker_error_manual_resume_does_not_repeat_completed_manager_decision(self) -> None:
        self._save_agent("manager", "Manager", "manager-system")
        self._save_agent("worker", "Fragile Worker", "worker-system")
        workflow = Workflow(
            id="wf-error",
            name="Error Resume",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id="manager",
                workers=[WorkerSlot("worker-slot", "worker")],
            ),
        )
        _session, run = self._seed_run(workflow)
        manager_calls = 0
        worker_calls = 0

        def respond(call, _index):
            nonlocal manager_calls, worker_calls
            if call["instructions"] == "manager-system":
                manager_calls += 1
                if manager_calls == 1:
                    return json.dumps(
                        {
                            "action": "delegate",
                            "assignments": [{"worker_id": "worker-slot", "instruction": "Do it"}],
                        }
                    )
                return json.dumps({"action": "final", "final": "recovered"})
            if call["instructions"] == "worker-system":
                worker_calls += 1
                if worker_calls == 1:
                    return RuntimeError("transient worker failure")
                return "worker recovered output"
            raise AssertionError(call)

        provider = ScriptedProvider(respond)
        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=provider,
            file_store=self.files,
        )
        paused = runtime.start_initial(run, user_request="Recover safely")
        self.assertEqual(paused.graph.status, RunStatus.PAUSED)
        self.assertEqual(manager_calls, 1)
        self.assertEqual(self.persistence.artifacts.list(run_id=run.id), [])

        completed = runtime.resume_after_error(run.id)
        self.assertEqual(completed.graph.status, RunStatus.COMPLETED)
        self.assertEqual(manager_calls, 2)
        self.assertEqual(worker_calls, 2)
        self.assertEqual(len(self.persistence.artifacts.list(run_id=run.id)), 1)
        self.assertEqual(completed.revision.final_output, "recovered")

    def test_followup_file_creates_continuation_run_and_new_revision(self) -> None:
        self._save_agent("manager", "Manager", "manager-system")
        self._save_agent("worker", "File Analyst", "worker-system")
        workflow = Workflow(
            id="wf-followup",
            name="Generic Follow-up",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id="manager",
                workers=[WorkerSlot("analysis-slot", "worker")],
            ),
        )
        session, run = self._seed_run(workflow)
        manager_calls = 0

        def respond(call, _index):
            nonlocal manager_calls
            if call["instructions"] == "manager-system":
                manager_calls += 1
                if manager_calls == 1:
                    return json.dumps({"action": "final", "final": "Revision one"})
                if manager_calls == 2:
                    self.assertIn("Revision one", call["input_text"])
                    self.assertIn("new evidence 42", call["input_text"])
                    return json.dumps(
                        {
                            "action": "delegate",
                            "assignments": [
                                {"worker_id": "analysis-slot", "instruction": "Use the new file"}
                            ],
                        }
                    )
                return json.dumps({"action": "final", "final": "Revision two"})
            if call["instructions"] == "worker-system":
                self.assertIn("new evidence 42", call["input_text"])
                return "file-aware worker result"
            raise AssertionError(call)

        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=ScriptedProvider(respond),
            file_store=self.files,
        )
        first = runtime.start_initial(run, user_request="Initial request")
        self.assertEqual(first.revision.version, 1)

        second = runtime.start_followup(
            session_id=session.id,
            previous_run_id=run.id,
            content="Update using the attached evidence",
            uploads=[PendingAttachment(filename="evidence.txt", data=b"new evidence 42")],
        )
        self.assertEqual(second.graph.status, RunStatus.COMPLETED)
        self.assertNotEqual(second.graph.run_id, run.id)
        continuation = self.persistence.runs.get(second.graph.run_id)
        self.assertEqual(continuation.parent_run_id, run.id)
        self.assertEqual(self.persistence.runs.get(run.id).status, RunStatus.COMPLETED)
        self.assertEqual(second.revision.version, 2)
        self.assertEqual(second.revision.final_output, "Revision two")
        self.assertEqual(len(second.revision.attachment_ids), 1)
        revisions = self.persistence.revisions.list(session_id=session.id)
        self.assertEqual([item.final_output for item in revisions], ["Revision one", "Revision two"])

    def test_initial_execution_file_target_routing_reaches_selected_worker(self) -> None:
        self._save_agent("manager", "Manager", "manager-system")
        self._save_agent("worker-a", "Alpha", "alpha-system")
        self._save_agent("worker-b", "Beta", "beta-system")
        workflow = Workflow(
            id="wf-file-routing",
            name="File Routing",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id="manager",
                workers=[
                    WorkerSlot("alpha-slot", "worker-a"),
                    WorkerSlot("beta-slot", "worker-b"),
                ],
            ),
        )
        _session, run = self._seed_run(workflow)
        stored = self.files.store_run_file(run.id, "target.txt", b"alpha only evidence")
        self.persistence.run_files.save(
            ExecutionFile(
                id="run-file-1",
                run_id=run.id,
                filename="target.txt",
                sha256=stored.sha256,
                size=stored.size,
                storage_ref=stored.storage_ref,
                target_ids=("alpha-slot",),
            )
        )
        manager_calls = 0

        def respond(call, _index):
            nonlocal manager_calls
            if call["instructions"] == "manager-system":
                manager_calls += 1
                if manager_calls == 1:
                    return json.dumps(
                        {
                            "action": "delegate",
                            "assignments": [
                                {"worker_id": "alpha-slot", "instruction": "Analyze file"},
                                {"worker_id": "beta-slot", "instruction": "Independent view"},
                            ],
                        }
                    )
                return json.dumps({"action": "final", "final": "done"})
            if call["instructions"] == "alpha-system":
                self.assertIn("alpha only evidence", call["input_text"])
                return "alpha result"
            if call["instructions"] == "beta-system":
                self.assertNotIn("alpha only evidence", call["input_text"])
                return "beta result"
            raise AssertionError(call)

        runtime = GenericWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=ScriptedProvider(respond),
            file_store=self.files,
        )
        outcome = runtime.start_initial(run, user_request="Route the input file")
        self.assertEqual(outcome.graph.status, RunStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
