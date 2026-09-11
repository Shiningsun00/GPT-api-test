from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.models import Agent, HierarchyConfig, LinearStep, WorkerSlot, Workflow, WorkflowMode
from agent_workflow_studio.core.workflow import new_initial_run, new_session
from agent_workflow_studio.graph import GenericWorkflowRuntime, SQLiteGraphCheckpointer
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence


class Provider:
    def __init__(self) -> None:
        self.manager_calls = 0

    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        if instructions == "manager-system":
            self.manager_calls += 1
            if self.manager_calls == 1:
                return ModelResponse(
                    text=json.dumps(
                        {
                            "action": "delegate",
                            "assignments": [
                                {"worker_id": "research-slot", "instruction": "Research"},
                                {"worker_id": "review-slot", "instruction": "Review"},
                            ],
                        }
                    )
                )
            return ModelResponse(text=json.dumps({"action": "final", "final": "generic hierarchy final"}))
        if instructions == "research-system":
            return ModelResponse(text="research artifact")
        if instructions == "review-system":
            if "research artifact" not in input_text:
                raise AssertionError("review worker did not receive prior artifact")
            return ModelResponse(text="review artifact")
        if instructions == "linear-a-system":
            return ModelResponse(text="linear first")
        if instructions == "linear-b-system":
            if "linear first" not in input_text:
                raise AssertionError("linear second step did not receive prior output")
            return ModelResponse(text="linear final")
        raise AssertionError(f"unexpected agent instructions: {instructions}")


def save_agent(persistence: SQLitePersistence, agent_id: str, name: str, prompt: str) -> None:
    persistence.agents.save(Agent(id=agent_id, name=name, model="test-model", system_prompt=prompt))


def seed_run(persistence: SQLitePersistence, workflow: Workflow, session_id: str, run_id: str):
    persistence.workflows.save(workflow)
    session = new_session(workflow, session_id=session_id)
    persistence.sessions.save(session)
    run = new_initial_run(session, run_id=run_id)
    persistence.runs.save(run)
    return run


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        persistence = SQLitePersistence(str(root / "domain.sqlite"))
        checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        files = LocalFileStore(root / "files")
        provider = Provider()
        try:
            save_agent(persistence, "manager", "Coordinator", "manager-system")
            save_agent(persistence, "research", "Researcher", "research-system")
            save_agent(persistence, "review", "Reviewer", "review-system")
            hierarchy = Workflow(
                id="generic-hierarchy",
                name="Generic hierarchy",
                mode=WorkflowMode.HIERARCHICAL,
                hierarchy=HierarchyConfig(
                    manager_agent_id="manager",
                    workers=[
                        WorkerSlot("research-slot", "research"),
                        WorkerSlot("review-slot", "review"),
                    ],
                ),
            )
            run = seed_run(persistence, hierarchy, "session-h", "run-h")
            outcome = GenericWorkflowRuntime(
                workflow=hierarchy,
                persistence=persistence,
                checkpointer=checkpointer,
                provider=provider,
                file_store=files,
            ).start_initial(run, user_request="generic hierarchy smoke")
            assert outcome.graph.completed
            assert outcome.revision and outcome.revision.final_output == "generic hierarchy final"
            print("[1/2] PASS: Manager + arbitrary Worker 2명 Hierarchical")

            save_agent(persistence, "linear-a", "Collector", "linear-a-system")
            save_agent(persistence, "linear-b", "Editor", "linear-b-system")
            linear = Workflow(
                id="generic-linear",
                name="Generic linear",
                mode=WorkflowMode.LINEAR,
                steps=[
                    LinearStep("collect", "linear-a"),
                    LinearStep("edit", "linear-b"),
                ],
            )
            run2 = seed_run(persistence, linear, "session-l", "run-l")
            outcome2 = GenericWorkflowRuntime(
                workflow=linear,
                persistence=persistence,
                checkpointer=checkpointer,
                provider=provider,
                file_store=files,
            ).start_initial(run2, user_request="generic linear smoke")
            assert outcome2.graph.completed
            assert outcome2.revision and outcome2.revision.final_output == "linear final"
            print("[2/2] PASS: arbitrary Agent 2명 Linear")
            print("\nR2 GENERIC RUNTIME SMOKE TEST = PASS")
        finally:
            checkpointer.close()
            persistence.close()


if __name__ == "__main__":
    main()
