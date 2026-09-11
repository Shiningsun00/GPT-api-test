from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient

from agent_workflow_studio.api import BackendContext, create_app
from agent_workflow_studio.core.execution import ModelResponse
from agent_workflow_studio.graph import SQLiteGraphCheckpointer
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence


class FakeProvider:
    def generate(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        if "Route the follow-up only" in input_text:
            return ModelResponse(text='{"stages":["w4_draft"]}')
        if "Act as the final editor and routing manager" in input_text:
            return ModelResponse(text="MANAGER FINAL")
        role = instructions.split()[0] if instructions else model
        return ModelResponse(text=f"{role} OUTPUT")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        persistence = SQLitePersistence(str(root / "domain.sqlite"))
        checkpointer = SQLiteGraphCheckpointer(root / "graph.sqlite")
        context = BackendContext(
            persistence=persistence,
            checkpointer=checkpointer,
            file_store=LocalFileStore(root / "files"),
            provider=FakeProvider(),
            owns_resources=False,
        )
        client = TestClient(create_app(context))
        try:
            print("[1/4] Health + OpenAPI")
            assert client.get("/health").status_code == 200
            assert client.get("/openapi.json").status_code == 200
            print("      PASS")

            print("[2/4] Seed Manager/W1-W6 + workflow/session")
            assert client.post("/agents", json={"id": "manager", "name": "Manager", "model": "fake"}).status_code == 201
            for i in range(1, 7):
                assert client.post("/agents", json={"id": f"agent-w{i}", "name": f"W{i} worker", "model": "fake"}).status_code == 201
            assert client.post(
                "/workflows",
                json={
                    "id": "career",
                    "name": "Career",
                    "mode": "hierarchical",
                    "hierarchy": {
                        "manager_agent_id": "manager",
                        "workers": [{"worker_id": f"slot-w{i}", "agent_id": f"agent-w{i}"} for i in range(1, 7)],
                    },
                },
            ).status_code == 201
            assert client.post("/sessions", json={"id": "session-1", "workflow_id": "career"}).status_code == 201
            print("      PASS")

            print("[3/4] Initial Career Run")
            first = client.post("/runs", json={"id": "run-1", "session_id": "session-1", "user_request": "Write a verified draft."})
            assert first.status_code == 201, first.text
            assert first.json()["status"] == "COMPLETED"
            assert first.json()["revision"]["version"] == 1
            print("      PASS")

            print("[4/4] Follow-up + file -> Continuation Run")
            follow = client.post(
                "/sessions/session-1/messages",
                data={"previous_run_id": "run-1", "content": "Revise with this evidence."},
                files={"files": ("evidence.txt", b"verified smoke evidence", "text/plain")},
            )
            assert follow.status_code == 201, follow.text
            body = follow.json()
            assert body["run_id"] != "run-1"
            assert body["revision"]["version"] == 2
            assert body["state"]["node_history"] == ["w4_draft", "w5_fact_review", "w6_reader_review"]
            print("      PASS")
            print("\nSTEP 5 API SMOKE TEST = PASS")
            return 0
        finally:
            client.close()
            checkpointer.close()
            persistence.close()


if __name__ == "__main__":
    raise SystemExit(main())
