from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_workflow_studio.core.models import Workflow, WorkflowSession
from agent_workflow_studio.integrations.discord_adapter import (
    DiscordAdapterError,
    DiscordAllowlist,
    DiscordAttachmentPayload,
    DiscordContext,
    DiscordController,
    DiscordPermissionError,
    DiscordSessionLinkStore,
    DiscordSessionNotLinkedError,
    render_outcome_for_discord,
    render_status_for_discord,
)
from agent_workflow_studio.persistence import SQLitePersistence


class FakeLink:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


class FakeLinks:
    def __init__(self) -> None:
        self.links = {}

    def bind(self, external_thread_id, session_id, metadata=None):
        link = FakeLink(session_id)
        self.links[external_thread_id] = link
        return link

    def resolve(self, external_thread_id):
        return self.links.get(external_thread_id)


class FakeApi:
    def __init__(self) -> None:
        self.sessions = []
        self.runs = {}
        self.resume_calls = []
        self.followups = []
        self._next = 1

    async def create_session(self, *, workflow_id: str, title: str = ""):
        session = {"id": f"s{self._next}", "workflow_id": workflow_id, "title": title}
        self._next += 1
        self.sessions.append(session)
        self.runs[session["id"]] = []
        return session

    async def start_run(self, *, session_id: str, user_request: str):
        run = {"id": f"r{self._next}", "session_id": session_id, "status": "COMPLETED", "created_at": f"2026-01-01T00:00:{self._next:02d}Z"}
        self._next += 1
        self.runs[session_id].append(run)
        return {"run_id": run["id"], "thread_id": run["id"], "status": run["status"], "revision": {"final_output": "initial result"}}

    async def list_session_runs(self, session_id: str):
        return list(self.runs.get(session_id, []))

    async def get_run(self, run_id: str):
        for runs in self.runs.values():
            for run in runs:
                if run["id"] == run_id:
                    return {"run": dict(run), "state": {"current_stage": "manager"}, "thread_id": run_id}
        raise AssertionError("run not found")

    async def resume_run(self, run_id: str, *, mode: str, answer=None):
        self.resume_calls.append((run_id, mode, answer))
        for runs in self.runs.values():
            for run in runs:
                if run["id"] == run_id:
                    run["status"] = "COMPLETED"
        return {"run_id": run_id, "thread_id": run_id, "status": "COMPLETED", "revision": {"final_output": "resumed result"}}

    async def follow_up(self, *, session_id: str, previous_run_id: str, content: str, attachments):
        self.followups.append((session_id, previous_run_id, content, list(attachments)))
        run = {"id": f"r{self._next}", "session_id": session_id, "status": "COMPLETED", "created_at": f"2026-01-01T00:00:{self._next:02d}Z", "kind": "CONTINUATION", "parent_run_id": previous_run_id}
        self._next += 1
        self.runs[session_id].append(run)
        return {"run_id": run["id"], "thread_id": run["id"], "status": "COMPLETED", "revision": {"final_output": "follow-up result"}}


class DiscordControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.links = FakeLinks()
        self.ctx = DiscordContext(external_thread_id="123", guild_id=10, channel_id=123, user_id=20)
        self.controller = DiscordController(self.api, self.links)

    async def test_start_creates_session_run_and_mapping(self):
        result = await self.controller.start(self.ctx, workflow_id="wf", prompt="hello", title="Discord")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(self.links.resolve("123").session_id, "s1")
        self.assertEqual(self.api.sessions[0]["workflow_id"], "wf")

    async def test_status_uses_latest_mapped_run(self):
        await self.controller.start(self.ctx, workflow_id="wf", prompt="hello")
        status = await self.controller.status(self.ctx)
        self.assertEqual(status["run"]["status"], "COMPLETED")
        self.assertEqual(status["detail"]["state"]["current_stage"], "manager")

    async def test_reply_resumes_same_waiting_run(self):
        await self.controller.start(self.ctx, workflow_id="wf", prompt="hello")
        session_id = self.links.resolve("123").session_id
        self.api.runs[session_id][-1]["status"] = "WAITING_FOR_USER"
        run_id = self.api.runs[session_id][-1]["id"]
        result = await self.controller.reply(self.ctx, answer="answer")
        self.assertEqual(result["thread_id"], run_id)
        self.assertEqual(self.api.resume_calls[-1], (run_id, "user", "answer"))

    async def test_resume_requires_paused_and_uses_same_run(self):
        await self.controller.start(self.ctx, workflow_id="wf", prompt="hello")
        session_id = self.links.resolve("123").session_id
        self.api.runs[session_id][-1]["status"] = "PAUSED"
        run_id = self.api.runs[session_id][-1]["id"]
        result = await self.controller.resume(self.ctx)
        self.assertEqual(result["thread_id"], run_id)
        self.assertEqual(self.api.resume_calls[-1], (run_id, "error", None))

    async def test_followup_creates_continuation_and_preserves_attachment_bytes(self):
        await self.controller.start(self.ctx, workflow_id="wf", prompt="hello")
        session_id = self.links.resolve("123").session_id
        parent_id = self.api.runs[session_id][-1]["id"]
        attachment = DiscordAttachmentPayload("evidence.txt", b"evidence", "text/plain")
        result = await self.controller.follow_up(self.ctx, content="revise", attachments=[attachment])
        self.assertNotEqual(result["run_id"], parent_id)
        self.assertEqual(self.api.followups[-1][1], parent_id)
        self.assertEqual(self.api.followups[-1][3][0].data, b"evidence")
        self.assertEqual(self.api.runs[session_id][0]["status"], "COMPLETED")

    async def test_unlinked_channel_is_rejected(self):
        with self.assertRaises(DiscordSessionNotLinkedError):
            await self.controller.status(self.ctx)

    async def test_allowlist_denies_unlisted_user(self):
        controller = DiscordController(
            self.api,
            self.links,
            allowlist=DiscordAllowlist(guild_ids=frozenset({10}), user_ids=frozenset({99}), channel_ids=frozenset({123})),
        )
        with self.assertRaises(DiscordPermissionError):
            await controller.start(self.ctx, workflow_id="wf", prompt="x")

    async def test_wrong_state_commands_are_rejected(self):
        await self.controller.start(self.ctx, workflow_id="wf", prompt="hello")
        with self.assertRaises(DiscordAdapterError):
            await self.controller.reply(self.ctx, answer="x")
        with self.assertRaises(DiscordAdapterError):
            await self.controller.resume(self.ctx)


class DiscordDurableLinkTests(unittest.TestCase):
    def test_channel_session_mapping_survives_reopen_and_contains_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "domain.sqlite")
            persistence = SQLitePersistence(db_path)
            persistence.workflows.save(Workflow(id="wf", name="Workflow"))
            persistence.sessions.save(WorkflowSession(id="session-1", workflow_id="wf"))
            store = DiscordSessionLinkStore(persistence)
            store.bind("987654", "session-1", {"guild_id": 1, "channel_id": 987654})
            persistence.close()

            reopened = SQLitePersistence(db_path)
            restored = DiscordSessionLinkStore(reopened).resolve("987654")
            self.assertIsNotNone(restored)
            self.assertEqual(restored.session_id, "session-1")
            serialized = str(restored.to_dict()).lower()
            self.assertNotIn("token", serialized)
            self.assertNotIn("api_key", serialized)
            reopened.close()


class DiscordRenderingTests(unittest.TestCase):
    def test_long_final_result_becomes_preview_plus_file(self):
        output = "x" * 5000
        rendered = render_outcome_for_discord({"status": "COMPLETED", "revision": {"final_output": output}})
        self.assertEqual(rendered.filename, "agent-workflow-result.md")
        self.assertEqual(rendered.file_bytes, output.encode("utf-8"))
        self.assertLessEqual(len(rendered.messages[0]), 1800)

    def test_waiting_result_surfaces_question(self):
        rendered = render_outcome_for_discord({"status": "WAITING_FOR_USER", "interrupts": [{"value": {"question": "Need evidence?"}}]})
        self.assertIn("Need evidence?", rendered.messages[0])

    def test_status_renderer_includes_run_and_stage(self):
        rendered = render_status_for_discord({"session_id": "s1", "run": {"id": "r1", "status": "RUNNING"}, "detail": {"state": {"current_stage": "W4"}}})
        self.assertIn("r1", rendered.messages[0])
        self.assertIn("W4", rendered.messages[0])


if __name__ == "__main__":
    unittest.main()
