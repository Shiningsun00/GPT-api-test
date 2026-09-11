from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.models import Agent
from agent_workflow_studio.integrations.notion import (
    NotionClient,
    NotionConfig,
    build_notion_reference_context,
    read_notion_page_text,
)
from agent_workflow_studio.integrations.notion_workflow import (
    DestructiveApproval,
    NotionInboxAdapter,
    NotionInboxConfig,
    NotionReferenceContextProvider,
    NotionSafetyError,
    NotionSessionLinkStore,
    NotionWritePolicy,
)
from agent_workflow_studio.persistence import SQLitePersistence


PAGE_ID = "01234567-89ab-cdef-0123-456789abcdef"
DATA_SOURCE_ID = "11111111-2222-3333-4444-555555555555"


def text_property(kind: str, text: str):
    if kind in {"title", "rich_text"}:
        return {"type": kind, kind: [{"plain_text": text}]}
    if kind in {"status", "select"}:
        return {"type": kind, kind: {"name": text}}
    raise AssertionError(kind)


class FakeNotion:
    def __init__(self, *, run_status: str = "completed"):
        self.config = SimpleNamespace(token="notion-secret")
        self.run_status = run_status
        self.append_calls = []
        self.update_calls = []
        self.query_calls = 0
        self.blocks = []
        self.page = {
            "object": "page",
            "id": PAGE_ID,
            "properties": {
                "Status": text_property("status", "Ready"),
                "Workflow ID": text_property("rich_text", "workflow-1"),
                "Prompt": text_property("rich_text", "write my cover letter"),
                "Name": text_property("title", "LG application"),
                "Result": text_property("rich_text", ""),
            },
        }
        self.schema = {
            "object": "data_source",
            "id": DATA_SOURCE_ID,
            "properties": {
                "Status": {"type": "status"},
                "Workflow ID": {"type": "rich_text"},
                "Prompt": {"type": "rich_text"},
                "Name": {"type": "title"},
                "Result": {"type": "rich_text"},
                "Error": {"type": "rich_text"},
            },
        }

    def retrieve_data_source(self, data_source_id):
        self.assert_id = data_source_id
        return self.schema

    def iter_data_source(self, data_source_id, *, filter=None, sorts=(), page_size=100):
        self.query_calls += 1
        status = self.page["properties"]["Status"]["status"]["name"]
        if status == "Ready":
            yield dict(self.page)

    def retrieve_page(self, page_id):
        return dict(self.page)

    def iter_block_children(self, page_id, *, page_size=100):
        yield from list(self.blocks)

    def append_block_children(self, page_id, children, *, position=None):
        self.append_calls.append((page_id, list(children), position))
        self.blocks.extend(children)
        return {"results": list(children)}

    def update_page_properties(self, page_id, properties):
        self.update_calls.append((page_id, dict(properties)))
        for name, value in properties.items():
            if "status" in value:
                self.page["properties"][name] = {"type": "status", "status": dict(value["status"])}
            elif "select" in value:
                self.page["properties"][name] = {"type": "select", "select": dict(value["select"])}
            elif "rich_text" in value:
                plain = "".join(item.get("text", {}).get("content", "") for item in value["rich_text"])
                self.page["properties"][name] = text_property("rich_text", plain)
        return dict(self.page)


class FakeApi:
    def __init__(self, *, status="completed"):
        self.status = status
        self.sessions = {}
        self.runs = {}
        self.revisions = {}
        self.create_session_count = 0
        self.start_run_count = 0

    async def create_session(self, *, workflow_id: str, title: str = ""):
        self.create_session_count += 1
        session_id = f"session-{self.create_session_count}"
        self.sessions[session_id] = {"id": session_id, "workflow_id": workflow_id, "title": title}
        self.runs[session_id] = []
        self.revisions[session_id] = []
        return dict(self.sessions[session_id])

    async def start_run(self, *, session_id: str, user_request: str):
        self.start_run_count += 1
        run_id = f"run-{self.start_run_count}"
        run = {
            "id": run_id,
            "session_id": session_id,
            "status": self.status,
            "created_at": f"2026-09-11T00:00:0{self.start_run_count}+00:00",
        }
        self.runs[session_id].append(run)
        if self.status == "completed":
            self.revisions[session_id].append(
                {
                    "id": f"revision-{self.start_run_count}",
                    "session_id": session_id,
                    "run_id": run_id,
                    "version": self.start_run_count,
                    "final_output": "FINAL COVER LETTER",
                    "created_at": f"2026-09-11T00:00:0{self.start_run_count}+00:00",
                }
            )
        return {"run_id": run_id, "status": self.status}

    async def list_session_runs(self, session_id: str):
        return list(self.runs.get(session_id, []))

    async def list_session_revisions(self, session_id: str):
        return list(self.revisions.get(session_id, []))


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class NotionInteractionTests(unittest.IsolatedAsyncioTestCase):
    def test_config_repr_redacts_token(self):
        config = NotionConfig(token="top-secret-token")
        self.assertNotIn("top-secret-token", repr(config))

    def test_client_uses_2026_data_source_query_endpoint(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.method
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse({"results": [], "has_more": False, "next_cursor": None})

        client = NotionClient(NotionConfig(token="secret"), urlopen=fake_urlopen)
        client.query_data_source(DATA_SOURCE_ID, filter={"property": "Status", "status": {"equals": "Ready"}})
        self.assertEqual(captured["method"], "POST")
        self.assertIn(f"/data_sources/{DATA_SOURCE_ID}/query", captured["url"])
        self.assertEqual(captured["body"]["filter"]["status"]["equals"], "Ready")

    def test_read_only_reference_context(self):
        notion = FakeNotion()
        notion.blocks = [
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Portfolio"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Verified robot result"}]}},
        ]
        text = read_notion_page_text(notion, PAGE_ID)
        self.assertIn("Workflow ID: workflow-1", text)
        self.assertIn("Verified robot result", text)
        context = build_notion_reference_context(notion, [PAGE_ID])
        self.assertIn("NOTION_REFERENCE", context)
        provider = NotionReferenceContextProvider(notion)
        agent = Agent(id="a", name="A", model="m", notion_enabled=True, notion_sources=[PAGE_ID])
        self.assertIn("Verified robot result", provider(agent))

    def test_write_policy_blocks_destructive_and_broad_overwrite(self):
        policy = NotionWritePolicy()
        policy.allow_create()
        policy.allow_append()
        policy.allow_designated_property_update()
        with self.assertRaises(NotionSafetyError):
            policy.require("erase_content")
        with self.assertRaises(NotionSafetyError):
            policy.require("property_update", designated=False)
        with self.assertRaises(NotionSafetyError):
            policy.require("overwrite_body", overwrite_chars=50_000)
        policy.require(
            "overwrite_body",
            overwrite_chars=50_000,
            approval=DestructiveApproval(approved=True, reason="user explicitly approved replacement"),
        )

    async def test_ready_task_starts_once_maps_and_writes_final_result(self):
        notion = FakeNotion()
        api = FakeApi(status="completed")
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SQLitePersistence(str(Path(tmp) / "domain.sqlite"))
            links = NotionSessionLinkStore(persistence)
            adapter = NotionInboxAdapter(
                notion,
                api,
                links,
                NotionInboxConfig(data_source_id=DATA_SOURCE_ID),
            )
            first = await adapter.poll_once()
            self.assertEqual(first[0]["action"], "finalized")
            self.assertEqual(api.create_session_count, 1)
            self.assertEqual(api.start_run_count, 1)
            self.assertEqual(len(notion.append_calls), 1)
            self.assertEqual(notion.page["properties"]["Status"]["status"]["name"], "Done")
            self.assertEqual(notion.page["properties"]["Result"]["rich_text"][0]["plain_text"], "FINAL COVER LETTER")
            link = links.get(PAGE_ID)
            self.assertIsNotNone(link)
            self.assertEqual(link.metadata["finalized_revision_id"], "revision-1")

            second = await adapter.poll_once()
            self.assertEqual(second, [])
            self.assertEqual(api.create_session_count, 1)
            self.assertEqual(api.start_run_count, 1)
            self.assertEqual(len(notion.append_calls), 1)
            persistence.close()

    async def test_existing_mapping_prevents_duplicate_run_and_marker_prevents_duplicate_append(self):
        notion = FakeNotion()
        api = FakeApi(status="completed")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "domain.sqlite")
            persistence = SQLitePersistence(db_path)
            links = NotionSessionLinkStore(persistence)
            session = await api.create_session(workflow_id="workflow-1", title="LG application")
            await api.start_run(session_id=session["id"], user_request="write my cover letter")
            links.bind(PAGE_ID, session["id"], metadata={"workflow_id": "workflow-1"})
            notion.blocks.append(
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "AWS2-REVISION:revision-1"}]}}
            )
            adapter = NotionInboxAdapter(notion, api, links, NotionInboxConfig(data_source_id=DATA_SOURCE_ID))
            result = await adapter.poll_once()
            self.assertEqual(result[0]["action"], "finalized")
            self.assertEqual(api.create_session_count, 1)
            self.assertEqual(api.start_run_count, 1)
            self.assertEqual(len(notion.append_calls), 0)
            self.assertEqual(notion.page["properties"]["Status"]["status"]["name"], "Done")
            persistence.close()

    async def test_waiting_run_is_observed_without_done_write(self):
        notion = FakeNotion()
        api = FakeApi(status="waiting_for_user")
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SQLitePersistence(str(Path(tmp) / "domain.sqlite"))
            adapter = NotionInboxAdapter(
                notion,
                api,
                NotionSessionLinkStore(persistence),
                NotionInboxConfig(data_source_id=DATA_SOURCE_ID),
            )
            result = await adapter.poll_once()
            self.assertEqual(result[0]["status"], "waiting_for_user")
            self.assertEqual(len(notion.append_calls), 0)
            self.assertEqual(notion.page["properties"]["Status"]["status"]["name"], "Ready")
            persistence.close()


if __name__ == "__main__":
    unittest.main()
