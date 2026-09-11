from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.api import BackendContext
from agent_workflow_studio.integrations.notion import NotionClient, NotionConfig
from agent_workflow_studio.integrations.notion_workflow import NotionReferenceContextProvider


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class NotionBackendWiringTests(unittest.TestCase):
    def test_local_backend_enables_notion_reference_provider_without_persisting_token(self):
        secret = "step8-notion-secret-that-must-not-be-persisted"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"NOTION_API_TOKEN": secret}, clear=False):
                context = BackendContext.local(tmp, provider=object())
                self.assertIsInstance(context.reference_context_provider, NotionReferenceContextProvider)
                self.assertNotIn(secret, repr(context.reference_context_provider))
                context.close()

            for name in ("domain.sqlite", "graph.sqlite"):
                path = Path(tmp) / name
                if path.exists():
                    self.assertNotIn(secret.encode("utf-8"), path.read_bytes())

    def test_notion_client_exposes_non_destructive_write_primitives(self):
        captured = []

        def fake_urlopen(request, timeout):
            captured.append(
                {
                    "url": request.full_url,
                    "method": request.method,
                    "body": json.loads(request.data.decode("utf-8")) if request.data else None,
                }
            )
            return FakeHTTPResponse({"object": "ok"})

        client = NotionClient(NotionConfig(token="secret"), urlopen=fake_urlopen)
        client.create_page(
            parent={"data_source_id": "ds"},
            properties={"Name": {"title": []}},
        )
        client.append_block_children(
            "page-1",
            [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}],
        )
        client.update_page_properties("page-1", {"Status": {"status": {"name": "Done"}}})

        self.assertEqual([item["method"] for item in captured], ["POST", "PATCH", "PATCH"])
        self.assertTrue(captured[0]["url"].endswith("/v1/pages"))
        self.assertTrue(captured[1]["url"].endswith("/v1/blocks/page-1/children"))
        self.assertTrue(captured[2]["url"].endswith("/v1/pages/page-1"))
        self.assertNotIn("secret", json.dumps(captured))


if __name__ == "__main__":
    unittest.main()
