from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.core.models import Workflow, WorkflowSession
from agent_workflow_studio.integrations.notion_workflow import (
    NotionInboxAdapter,
    NotionInboxConfig,
    NotionSessionLinkStore,
)
from agent_workflow_studio.persistence import SQLitePersistence

PAGE_ID = "01234567-89ab-cdef-0123-456789abcdef"
DATA_SOURCE_ID = "11111111-2222-3333-4444-555555555555"


def prop(kind: str, text: str):
    if kind in {"title", "rich_text"}:
        return {"type": kind, kind: [{"plain_text": text}]}
    return {"type": kind, kind: {"name": text}}


class FakeNotion:
    def __init__(self):
        self.config = SimpleNamespace(token="fake-secret")
        self.blocks = []
        self.append_count = 0
        self.page = {
            "object": "page",
            "id": PAGE_ID,
            "properties": {
                "Status": prop("status", "Ready"),
                "Workflow ID": prop("rich_text", "workflow-1"),
                "Prompt": prop("rich_text", "Create a test cover letter"),
                "Name": prop("title", "Smoke Test"),
                "Result": prop("rich_text", ""),
            },
        }

    def retrieve_data_source(self, data_source_id):
        return {
            "id": data_source_id,
            "properties": {
                "Status": {"type": "status"},
                "Workflow ID": {"type": "rich_text"},
                "Prompt": {"type": "rich_text"},
                "Name": {"type": "title"},
                "Result": {"type": "rich_text"},
            },
        }

    def iter_data_source(self, data_source_id, *, filter=None, sorts=(), page_size=100):
        if self.page["properties"]["Status"]["status"]["name"] == "Ready":
            yield dict(self.page)

    def iter_block_children(self, page_id, *, page_size=100):
        yield from self.blocks

    def append_block_children(self, page_id, children, *, position=None):
        self.append_count += 1
        self.blocks.extend(children)
        return {"results": list(children)}

    def update_page_properties(self, page_id, properties):
        for name, value in properties.items():
            if "status" in value:
                self.page["properties"][name] = {"type": "status", "status": dict(value["status"])}
            elif "rich_text" in value:
                plain = "".join(item.get("text", {}).get("content", "") for item in value["rich_text"])
                self.page["properties"][name] = prop("rich_text", plain)
        return dict(self.page)


class FakeApi:
    def __init__(self, persistence: SQLitePersistence):
        self.persistence = persistence
        self.start_count = 0
        self.sessions = {}

    async def create_session(self, *, workflow_id: str, title: str = ""):
        if self.persistence.workflows.get(workflow_id) is None:
            self.persistence.workflows.save(Workflow(id=workflow_id, name="Notion Smoke Workflow"))
        session = {"id": "session-1", "workflow_id": workflow_id, "title": title}
        self.persistence.sessions.save(WorkflowSession(id=session["id"], workflow_id=workflow_id, title=title))
        self.sessions[session["id"]] = {"runs": [], "revisions": []}
        return session

    async def start_run(self, *, session_id: str, user_request: str):
        self.start_count += 1
        run = {"id": "run-1", "status": "completed", "created_at": "2026-09-11T00:00:00+00:00"}
        self.sessions[session_id]["runs"].append(run)
        self.sessions[session_id]["revisions"].append(
            {
                "id": "revision-1",
                "run_id": "run-1",
                "version": 1,
                "final_output": "SMOKE FINAL",
                "created_at": "2026-09-11T00:00:00+00:00",
            }
        )
        return {"run_id": "run-1", "status": "completed"}

    async def list_session_runs(self, session_id: str):
        return list(self.sessions[session_id]["runs"])

    async def list_session_revisions(self, session_id: str):
        return list(self.sessions[session_id]["revisions"])


async def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "domain.sqlite")
        persistence = SQLitePersistence(db_path)
        notion = FakeNotion()
        api = FakeApi(persistence)
        links = NotionSessionLinkStore(persistence)
        adapter = NotionInboxAdapter(notion, api, links, NotionInboxConfig(data_source_id=DATA_SOURCE_ID))

        first = await adapter.poll_once()
        assert first and first[0]["action"] == "finalized"
        assert api.start_count == 1
        assert notion.append_count == 1
        assert notion.page["properties"]["Status"]["status"]["name"] == "Done"
        assert links.get(PAGE_ID) is not None
        persistence.close()

        reopened = SQLitePersistence(db_path)
        reopened_links = NotionSessionLinkStore(reopened)
        link = reopened_links.get(PAGE_ID)
        assert link is not None and link.session_id == "session-1"
        assert link.metadata.get("finalized_revision_id") == "revision-1"
        reopened.close()

    print("STEP 8 Notion smoke: PASS")


if __name__ == "__main__":
    asyncio.run(run())
