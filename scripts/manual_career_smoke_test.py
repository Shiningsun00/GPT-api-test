from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.models import Agent, HierarchyConfig, WorkerSlot, Workflow, WorkflowMode
from agent_workflow_studio.core.workflow import new_initial_run, new_session
from agent_workflow_studio.graph import SQLiteGraphCheckpointer
from agent_workflow_studio.persistence import LocalFileStore, PendingAttachment, SQLitePersistence
from agent_workflow_studio.policies.career_runtime import CAREER_STAGE_ORDER, CareerWorkflowRuntime


class DemoProvider:
    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        if "Route the follow-up only" in input_text:
            return ModelResponse(text='{"stages":["w4_draft"]}')
        if "Act as the final editor and routing manager" in input_text:
            return ModelResponse(text="FINAL COVER LETTER")
        role = instructions.split()[0]
        return ModelResponse(text=f"{role} RESULT")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        persistence = SQLitePersistence(root / "domain.sqlite")
        file_store = LocalFileStore(root / "data")
        checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        provider = DemoProvider()

        manager = Agent(id="manager", name="Manager", model="fake", system_prompt="MANAGER prompt")
        workers = [Agent(id=f"w{i}", name=f"W{i} worker", model="fake", system_prompt=f"W{i} prompt") for i in range(1, 7)]
        persistence.agents.save(manager)
        for worker in workers:
            persistence.agents.save(worker)
        workflow = Workflow(
            id="career",
            name="Career workflow",
            mode=WorkflowMode.HIERARCHICAL,
            hierarchy=HierarchyConfig(
                manager_agent_id=manager.id,
                workers=[WorkerSlot(worker_id=f"slot-{worker.id}", agent_id=worker.id) for worker in workers],
            ),
        )
        persistence.workflows.save(workflow)
        session = new_session(workflow, session_id="career-session")
        run = new_initial_run(session, run_id="career-run-1")
        persistence.sessions.save(session)
        persistence.runs.save(run)

        runtime = CareerWorkflowRuntime(
            workflow=workflow,
            persistence=persistence,
            checkpointer=checkpointer,
            provider=provider,
            file_store=file_store,
        )

        print("[1/3] Initial W1-W6 career workflow")
        first = runtime.start_initial(run, user_request="Create a cover letter from verified evidence")
        assert first.graph.completed
        assert tuple(first.graph.state["node_history"]) == CAREER_STAGE_ORDER
        assert first.revision and first.revision.version == 1
        assert len(persistence.artifacts.list(run_id=run.id)) == 8
        print("      PASS: dependency-aware pipeline + immutable artifacts + Revision v1")

        print("[2/3] Manager post-result follow-up + file")
        second = runtime.start_followup(
            session_id=session.id,
            previous_run_id=run.id,
            content="Revise the draft using the attached evidence.",
            uploads=[PendingAttachment(filename="evidence.txt", data=b"verified follow-up evidence")],
        )
        assert second.graph.completed
        assert tuple(second.graph.state["node_history"]) == ("w4_draft", "w5_fact_review", "w6_reader_review")
        assert second.revision and second.revision.version == 2
        assert len(persistence.artifacts.list(run_id=second.graph.run_id)) == 3
        print("      PASS: Continuation Run + minimum required downstream rerun + Revision v2")

        print("[3/3] Historical immutability")
        assert len(persistence.artifacts.list(run_id=run.id)) == 8
        assert len(persistence.revisions.list(session_id=session.id)) == 2
        print("      PASS: Revision v1 and original artifacts preserved")

        checkpointer.close()
        persistence.close()

    print("\nSTEP 4 CAREER WORKFLOW SMOKE TEST = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
