from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient

from agent_workflow_studio.api import BackendContext, create_app
from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.core.models import RunStatus
from agent_workflow_studio.core.workflow import new_initial_run
from agent_workflow_studio.graph import SQLiteGraphCheckpointer, UserInputRequest
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence
from agent_workflow_studio.policies.career_runtime import CareerWorkflowRuntime


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


class FastAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.persistence = SQLitePersistence(str(root / "domain.sqlite"))
        self.checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        self.file_store = LocalFileStore(root / "files")
        self.provider = FakeProvider()
        self.context = BackendContext(
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            file_store=self.file_store,
            provider=self.provider,
            owns_resources=False,
        )
        self.client = TestClient(create_app(self.context))

    def tearDown(self) -> None:
        self.client.close()
        self.checkpointer.close()
        self.persistence.close()
        self.tmp.cleanup()

    def _seed_career(self) -> tuple[str, str]:
        manager = self.client.post(
            "/agents",
            json={"id": "manager", "name": "Manager", "model": "fake", "system_prompt": "MANAGER prompt"},
        )
        self.assertEqual(manager.status_code, 201)
        for i in range(1, 7):
            response = self.client.post(
                "/agents",
                json={"id": f"agent-w{i}", "name": f"W{i} worker", "model": "fake", "system_prompt": f"W{i} prompt"},
            )
            self.assertEqual(response.status_code, 201)
        workflow = self.client.post(
            "/workflows",
            json={
                "id": "career-workflow",
                "name": "Career Cover Letter",
                "mode": "hierarchical",
                "hierarchy": {
                    "manager_agent_id": "manager",
                    "workers": [
                        {"worker_id": f"slot-w{i}", "agent_id": f"agent-w{i}"}
                        for i in range(1, 7)
                    ],
                },
            },
        )
        self.assertEqual(workflow.status_code, 201, workflow.text)
        session = self.client.post(
            "/sessions",
            json={"id": "session-1", "workflow_id": "career-workflow", "title": "Career API test"},
        )
        self.assertEqual(session.status_code, 201, session.text)
        return "career-workflow", "session-1"

    def test_health_openapi_and_agent_workflow_crud(self) -> None:
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        schema = self.client.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertIn("/runs", schema.json()["paths"])

        created = self.client.post("/agents", json={"id": "a1", "name": "A1", "model": "fake"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client.get("/agents/a1").json()["name"], "A1")
        updated = self.client.put("/agents/a1", json={"name": "A1 updated", "model": "fake"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "A1 updated")

        workflow = self.client.post(
            "/workflows",
            json={"id": "linear-1", "name": "Linear", "mode": "linear", "steps": []},
        )
        self.assertEqual(workflow.status_code, 201)
        self.assertEqual(self.client.get("/workflows/linear-1").status_code, 200)
        self.assertEqual(self.client.delete("/workflows/linear-1").status_code, 204)
        self.assertEqual(self.client.delete("/agents/a1").status_code, 204)

    def test_career_run_followup_history_and_immutable_revisions(self) -> None:
        _, session_id = self._seed_career()
        first = self.client.post(
            "/runs",
            json={"id": "run-1", "session_id": session_id, "user_request": "Write from verified evidence."},
        )
        self.assertEqual(first.status_code, 201, first.text)
        first_body = first.json()
        self.assertEqual(first_body["status"], "COMPLETED")
        self.assertEqual(first_body["thread_id"], "run-1")
        self.assertEqual(first_body["revision"]["version"], 1)
        self.assertEqual(len(self.client.get(f"/sessions/{session_id}/artifacts").json()), 8)
        self.assertGreater(len(self.client.get("/runs/run-1/history").json()), 0)

        follow = self.client.post(
            f"/sessions/{session_id}/messages",
            data={"previous_run_id": "run-1", "content": "Revise using the attached verified result."},
            files={"files": ("evidence.txt", b"verified API evidence", "text/plain")},
        )
        self.assertEqual(follow.status_code, 201, follow.text)
        follow_body = follow.json()
        self.assertEqual(follow_body["status"], "COMPLETED")
        self.assertNotEqual(follow_body["run_id"], "run-1")
        self.assertEqual(follow_body["revision"]["version"], 2)
        self.assertEqual(
            follow_body["state"]["node_history"],
            ["w4_draft", "w5_fact_review", "w6_reader_review"],
        )
        revisions = self.client.get(f"/sessions/{session_id}/revisions").json()
        self.assertEqual([item["version"] for item in revisions], [1, 2])
        messages = self.client.get(f"/sessions/{session_id}/messages").json()
        self.assertEqual(len(messages), 1)
        self.assertEqual(len(messages[0]["attachment_ids"]), 1)
        self.assertTrue(any("verified API evidence" in call["input_text"] for call in self.provider.calls))

    def test_hitl_resume_endpoint_keeps_same_run_and_thread(self) -> None:
        workflow_id, session_id = self._seed_career()
        workflow = self.persistence.workflows.get(workflow_id)
        session = self.persistence.sessions.get(session_id)
        self.assertIsNotNone(workflow)
        self.assertIsNotNone(session)
        run = new_initial_run(session, run_id="run-hitl")
        self.persistence.runs.save(run)

        def hook(state, spec):
            if spec.key == "w4_draft" and spec.key not in state.get("human_answers", {}):
                return UserInputRequest(question="Confirm writing direction")
            return None

        runtime = CareerWorkflowRuntime(
            workflow=workflow,
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            provider=self.provider,
            file_store=self.file_store,
            hitl_hook=hook,
        )
        waiting = runtime.start_initial(run, user_request="Need confirmation before draft")
        self.assertEqual(waiting.graph.status, RunStatus.WAITING_FOR_USER)

        resumed = self.client.post(
            "/runs/run-hitl/resume",
            json={"mode": "user", "answer": "Proceed"},
        )
        self.assertEqual(resumed.status_code, 200, resumed.text)
        body = resumed.json()
        self.assertEqual(body["status"], "COMPLETED")
        self.assertEqual(body["run_id"], "run-hitl")
        self.assertEqual(body["thread_id"], "run-hitl")
        self.assertEqual(body["revision"]["version"], 1)

    def test_run_errors_are_normalized(self) -> None:
        missing = self.client.get("/runs/does-not-exist")
        self.assertEqual(missing.status_code, 404)
        unsupported = self.client.post(
            "/runs",
            json={"session_id": "missing", "user_request": "x", "policy": "other"},
        )
        self.assertEqual(unsupported.status_code, 422)


if __name__ == "__main__":
    unittest.main()
