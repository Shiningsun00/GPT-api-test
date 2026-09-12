from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient

from agent_workflow_studio.api import BackendContext, create_app
from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.graph import SQLiteGraphCheckpointer
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence


class RouterProvider:
    def __init__(self) -> None:
        self.generic_manager_round = 0
        self.calls: list[dict[str, str]] = []

    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        self.calls.append({"model": model, "instructions": instructions, "input_text": input_text})
        if "[GENERIC_HIERARCHICAL_MANAGER]" in input_text:
            self.generic_manager_round += 1
            if self.generic_manager_round == 1:
                return ModelResponse(text=json.dumps({"action": "delegate", "assignments": [
                    {"worker_id": "research-slot", "instruction": "Analyze the request."},
                    {"worker_id": "review-slot", "instruction": "Review the analysis."},
                ]}))
            return ModelResponse(text=json.dumps({"action": "final", "final": "GENERIC FINAL"}))
        if "Route the follow-up only" in input_text:
            return ModelResponse(text='{"stages":["w4_draft"]}')
        if "Act as the final editor and routing manager" in input_text:
            return ModelResponse(text="CAREER FINAL")
        return ModelResponse(text="WORKER OUTPUT")


class R3ApiRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.persistence = SQLitePersistence(root / "domain.sqlite")
        self.checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        self.provider = RouterProvider()
        self.client = TestClient(create_app(BackendContext(
            persistence=self.persistence,
            checkpointer=self.checkpointer,
            file_store=LocalFileStore(root / "files"),
            provider=self.provider,
            owns_resources=False,
        )))

    def tearDown(self) -> None:
        self.client.close()
        self.checkpointer.close()
        self.persistence.close()
        self.tmp.cleanup()

    def test_generic_manager_two_workers_runs_without_w_names(self) -> None:
        for payload in (
            {"id": "manager", "name": "Coordinator", "model": "fake"},
            {"id": "researcher", "name": "Researcher", "model": "fake"},
            {"id": "reviewer", "name": "Reviewer", "model": "fake"},
        ):
            self.assertEqual(self.client.post("/agents", json=payload).status_code, 201)
        workflow = self.client.post("/workflows", json={
            "id": "generic-h",
            "name": "Generic Hierarchy",
            "mode": "hierarchical",
            "hierarchy": {
                "manager_agent_id": "manager",
                "workers": [
                    {"worker_id": "research-slot", "agent_id": "researcher"},
                    {"worker_id": "review-slot", "agent_id": "reviewer"},
                ],
            },
        })
        self.assertEqual(workflow.status_code, 201, workflow.text)
        self.assertIsNone(workflow.json()["policy_id"])
        self.assertEqual(self.client.post("/sessions", json={"id": "generic-session", "workflow_id": "generic-h"}).status_code, 201)
        result = self.client.post("/runs", json={"id": "generic-run", "session_id": "generic-session", "user_request": "Analyze and review this."})
        self.assertEqual(result.status_code, 201, result.text)
        body = result.json()
        self.assertEqual(body["status"], "COMPLETED")
        self.assertEqual(body["revision"]["final_output"], "GENERIC FINAL")
        artifacts = self.client.get("/sessions/generic-session/artifacts").json()
        self.assertEqual({item["metadata"]["worker_id"] for item in artifacts}, {"research-slot", "review-slot"})

    def test_generic_initial_file_route_uses_stored_policy(self) -> None:
        self.assertEqual(self.client.post("/agents", json={"id": "worker", "name": "Plain Worker", "model": "fake"}).status_code, 201)
        workflow = self.client.post("/workflows", json={
            "id": "generic-linear",
            "name": "Generic Linear",
            "mode": "linear",
            "steps": [{"step_id": "step-1", "agent_id": "worker"}],
        })
        self.assertEqual(workflow.status_code, 201, workflow.text)
        self.assertIsNone(workflow.json()["policy_id"])
        self.assertEqual(self.client.post("/sessions", json={"id": "generic-file-session", "workflow_id": "generic-linear"}).status_code, 201)
        result = self.client.post(
            "/runs/with-files",
            data={"session_id": "generic-file-session", "user_request": "Use the uploaded evidence."},
            files={"files": ("evidence.txt", b"GENERIC FILE EVIDENCE", "text/plain")},
        )
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["status"], "COMPLETED")
        self.assertEqual(result.json()["revision"]["final_output"], "WORKER OUTPUT")
        self.assertTrue(any("GENERIC FILE EVIDENCE" in call["input_text"] for call in self.provider.calls))

    def test_career_policy_uses_explicit_slot_roles_not_agent_names(self) -> None:
        self.assertEqual(self.client.post("/agents", json={"id": "cm", "name": "Editor Manager", "model": "fake"}).status_code, 201)
        names = ["Evidence", "Company Analyst", "Strategist", "Writer", "Fact Checker", "Reader"]
        for i, name in enumerate(names, 1):
            self.assertEqual(self.client.post("/agents", json={"id": f"ca{i}", "name": name, "model": "fake", "system_prompt": f"W{i} prompt"}).status_code, 201)
        workflow = self.client.post("/workflows", json={
            "id": "career",
            "name": "Career",
            "mode": "hierarchical",
            "policy_id": "career_cover_letter",
            "policy_config": {"slot_roles": {f"slot-{i}": f"W{i}" for i in range(1, 7)}},
            "hierarchy": {
                "manager_agent_id": "cm",
                "workers": [{"worker_id": f"slot-{i}", "agent_id": f"ca{i}"} for i in range(1, 7)],
            },
        })
        self.assertEqual(workflow.status_code, 201, workflow.text)
        self.assertEqual(self.client.post("/sessions", json={"id": "career-session", "workflow_id": "career"}).status_code, 201)
        result = self.client.post("/runs", json={"id": "career-run", "session_id": "career-session", "user_request": "Write the application."})
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["revision"]["final_output"], "CAREER FINAL")

    def test_client_policy_cannot_override_stored_workflow_policy(self) -> None:
        self.client.post("/agents", json={"id": "a", "name": "A", "model": "fake"})
        self.client.post("/workflows", json={"id": "linear", "name": "Linear", "mode": "linear", "steps": [{"step_id": "s", "agent_id": "a"}]})
        self.client.post("/sessions", json={"id": "s", "workflow_id": "linear"})
        response = self.client.post("/runs", json={"session_id": "s", "user_request": "x", "policy": "career_cover_letter"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("stored=generic", response.text)
        file_response = self.client.post(
            "/runs/with-files",
            data={"session_id": "s", "user_request": "x", "policy": "career_cover_letter"},
        )
        self.assertEqual(file_response.status_code, 409)
        self.assertIn("stored=generic", file_response.text)


if __name__ == "__main__":
    unittest.main()
