from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.models import Agent, HierarchyConfig, RunStatus, WorkerSlot, Workflow, WorkflowMode
from agent_workflow_studio.core.workflow import new_initial_run, new_session
from agent_workflow_studio.graph import SQLiteGraphCheckpointer, UserInputRequest
from agent_workflow_studio.persistence import LocalFileStore, PendingAttachment, SQLitePersistence
from agent_workflow_studio.policies.career_runtime import (
    CAREER_STAGE_ORDER,
    CareerRegistryError,
    CareerWorkflowRuntime,
    normalize_followup_stages,
)


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        self.calls.append({"model": model, "instructions": instructions, "input_text": input_text})
        if "Route the follow-up only" in input_text:
            return ModelResponse(text='{"stages":["w4_draft"]}')
        if "Act as the final editor and routing manager" in input_text:
            return ModelResponse(text=f"MANAGER FINAL {len(self.calls)}")
        role = instructions.split()[0] if instructions else model
        return ModelResponse(text=f"{role} OUTPUT {len(self.calls)}", usage={"total_tokens": 10})


def build_fixture(root: Path):
    persistence = SQLitePersistence(root / "domain.sqlite")
    file_store = LocalFileStore(root / "data")
    provider = FakeProvider()
    agents = {
        "M": Agent(id="manager", name="Manager", model="fake", system_prompt="MANAGER prompt"),
        **{
            f"W{i}": Agent(id=f"agent-w{i}", name=f"W{i} worker", model="fake", system_prompt=f"W{i} prompt")
            for i in range(1, 7)
        },
    }
    for agent in agents.values():
        persistence.agents.save(agent)
    workflow = Workflow(
        id="career-workflow",
        name="Career Cover Letter",
        mode=WorkflowMode.HIERARCHICAL,
        hierarchy=HierarchyConfig(
            manager_agent_id=agents["M"].id,
            workers=[WorkerSlot(worker_id=f"slot-w{i}", agent_id=agents[f"W{i}"].id) for i in range(1, 7)],
        ),
    )
    persistence.workflows.save(workflow)
    session = new_session(workflow, session_id="session-1", title="Career test")
    run = new_initial_run(session, run_id="run-1")
    persistence.sessions.save(session)
    persistence.runs.save(run)
    return persistence, file_store, provider, workflow, session, run


class CareerWorkflowTests(unittest.TestCase):
    def test_registry_requires_exact_w1_to_w6_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persistence, file_store, provider, workflow, session, run = build_fixture(root)
            workflow.hierarchy.workers = workflow.hierarchy.workers[:-1]
            persistence.workflows.save(workflow)
            checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
            with self.assertRaises(CareerRegistryError):
                CareerWorkflowRuntime(
                    workflow=workflow,
                    persistence=persistence,
                    checkpointer=checkpointer,
                    provider=provider,
                    file_store=file_store,
                )
            checkpointer.close()
            persistence.close()

    def test_initial_workflow_preserves_stage_order_dependencies_artifacts_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persistence, file_store, provider, workflow, session, run = build_fixture(root)
            checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
            runtime = CareerWorkflowRuntime(
                workflow=workflow,
                persistence=persistence,
                checkpointer=checkpointer,
                provider=provider,
                file_store=file_store,
            )
            outcome = runtime.start_initial(run, user_request="Write an application essay from verified evidence.")
            self.assertEqual(outcome.graph.status, RunStatus.COMPLETED)
            self.assertEqual(tuple(outcome.graph.state["node_history"]), CAREER_STAGE_ORDER)
            self.assertIsNotNone(outcome.revision)
            self.assertEqual(outcome.revision.version, 1)
            artifacts = persistence.artifacts.list(run_id=run.id)
            self.assertEqual(len(artifacts), 8)
            by_stage = {item.metadata["stage"]: item for item in artifacts}
            self.assertEqual(by_stage["w3_candidates"].dependencies, tuple(sorted([
                by_stage["w1_intake"].id,
                by_stage["w2_analysis"].id,
            ])))
            self.assertEqual(by_stage["w6_selection_review"].dependencies, (by_stage["w3_candidates"].id,))
            self.assertEqual(by_stage["w3_strategy"].dependencies, tuple(sorted([
                by_stage["w3_candidates"].id,
                by_stage["w6_selection_review"].id,
            ])))
            self.assertEqual(by_stage["w4_draft"].dependencies, (by_stage["w3_strategy"].id,))
            self.assertEqual(by_stage["w5_fact_review"].dependencies, (by_stage["w4_draft"].id,))
            self.assertEqual(by_stage["w6_reader_review"].dependencies, (by_stage["w4_draft"].id,))
            self.assertEqual(by_stage["w4_draft"].producer, "agent-w4")
            self.assertEqual(by_stage["w5_fact_review"].producer, "agent-w5")
            self.assertEqual(by_stage["w6_reader_review"].producer, "agent-w6")
            checkpointer.close()
            persistence.close()

    def test_followup_reruns_only_required_downstream_and_preserves_old_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persistence, file_store, provider, workflow, session, run = build_fixture(root)
            checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
            runtime = CareerWorkflowRuntime(
                workflow=workflow,
                persistence=persistence,
                checkpointer=checkpointer,
                provider=provider,
                file_store=file_store,
            )
            first = runtime.start_initial(run, user_request="Initial application request")
            old_artifacts = tuple(item.id for item in persistence.artifacts.list(run_id=run.id))
            second = runtime.start_followup(
                session_id=session.id,
                previous_run_id=run.id,
                content="Revise the draft using this test result.",
                uploads=[PendingAttachment(filename="evidence.txt", data=b"verified test evidence")],
            )
            self.assertEqual(second.graph.status, RunStatus.COMPLETED)
            self.assertEqual(tuple(second.graph.state["node_history"]), ("w4_draft", "w5_fact_review", "w6_reader_review"))
            self.assertEqual(second.revision.version, 2)
            self.assertEqual(second.graph.state["follow_up_attachment_refs"], [persistence.attachments.list()[0].storage_ref])
            new_artifacts = persistence.artifacts.list(run_id=second.graph.run_id)
            self.assertEqual([item.kind for item in new_artifacts], ["draft", "review", "review"])
            new_draft = next(item for item in new_artifacts if item.kind == "draft")
            reviews = [item for item in new_artifacts if item.kind == "review"]
            self.assertTrue(all(item.dependencies == (new_draft.id,) for item in reviews))
            self.assertEqual(tuple(item.id for item in persistence.artifacts.list(run_id=run.id)), old_artifacts)
            self.assertEqual(len(persistence.revisions.list(session_id=session.id)), 2)
            self.assertTrue(any("verified test evidence" in call["input_text"] for call in provider.calls if call["instructions"].startswith("W4")))
            checkpointer.close()
            persistence.close()

    def test_hitl_hook_resumes_same_run_before_worker_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persistence, file_store, provider, workflow, session, run = build_fixture(root)
            checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")

            def hook(state, spec):
                if spec.key == "w4_draft" and spec.key not in state.get("human_answers", {}):
                    return UserInputRequest(question="Confirm the final writing direction")
                return None

            runtime = CareerWorkflowRuntime(
                workflow=workflow,
                persistence=persistence,
                checkpointer=checkpointer,
                provider=provider,
                file_store=file_store,
                hitl_hook=hook,
            )
            waiting = runtime.start_initial(run, user_request="Need HITL")
            self.assertEqual(waiting.graph.status, RunStatus.WAITING_FOR_USER)
            self.assertEqual(persistence.runs.get(run.id).status, RunStatus.WAITING_FOR_USER)
            resumed = runtime.resume_with_user(run.id, "Proceed")
            self.assertEqual(resumed.graph.status, RunStatus.COMPLETED)
            self.assertEqual(resumed.graph.run_id, run.id)
            self.assertEqual(resumed.graph.thread_id, run.id)
            self.assertEqual(resumed.revision.version, 1)
            checkpointer.close()
            persistence.close()

    def test_followup_stage_normalization_preserves_required_re_review(self) -> None:
        self.assertEqual(
            normalize_followup_stages(["w4_draft"]),
            ("w4_draft", "w5_fact_review", "w6_reader_review"),
        )
        self.assertEqual(normalize_followup_stages(["w5_fact_review"]), ("w5_fact_review",))
        self.assertEqual(
            normalize_followup_stages(["w1_intake"]),
            ("w1_intake", "w3_candidates", "w6_selection_review", "w3_strategy", "w4_draft", "w5_fact_review", "w6_reader_review"),
        )


if __name__ == "__main__":
    unittest.main()
