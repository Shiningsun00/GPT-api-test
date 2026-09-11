from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.core.models import Workflow, WorkflowSession
from agent_workflow_studio.integrations.discord_adapter import (
    DiscordAttachmentPayload,
    DiscordContext,
    DiscordController,
    DiscordSessionLinkStore,
    render_outcome_for_discord,
)
from agent_workflow_studio.persistence import SQLitePersistence


class SmokeApi:
    def __init__(self) -> None:
        self.runs = {"session-1": []}
        self.next_run = 1

    async def create_session(self, *, workflow_id: str, title: str = ""):
        return {"id": "session-1", "workflow_id": workflow_id, "title": title}

    async def start_run(self, *, session_id: str, user_request: str):
        run = {"id": "run-1", "session_id": session_id, "status": "WAITING_FOR_USER", "created_at": "2026-01-01T00:00:01Z"}
        self.runs[session_id].append(run)
        return {"run_id": "run-1", "thread_id": "run-1", "status": "WAITING_FOR_USER", "interrupts": [{"value": {"question": "추가 근거를 알려주세요."}}]}

    async def list_session_runs(self, session_id: str):
        return list(self.runs[session_id])

    async def get_run(self, run_id: str):
        run = next(item for item in self.runs["session-1"] if item["id"] == run_id)
        return {"run": dict(run), "state": {"current_stage": "needs_input"}, "thread_id": run_id}

    async def resume_run(self, run_id: str, *, mode: str, answer=None):
        run = next(item for item in self.runs["session-1"] if item["id"] == run_id)
        run["status"] = "COMPLETED"
        return {"run_id": run_id, "thread_id": run_id, "status": "COMPLETED", "revision": {"final_output": "초기 최종본"}}

    async def follow_up(self, *, session_id: str, previous_run_id: str, content: str, attachments):
        assert previous_run_id == "run-1"
        assert content == "첨부 근거를 반영해 수정"
        assert attachments[0].filename == "evidence.txt"
        assert attachments[0].data == b"evidence"
        run = {"id": "run-2", "session_id": session_id, "status": "COMPLETED", "kind": "CONTINUATION", "parent_run_id": previous_run_id, "created_at": "2026-01-01T00:00:02Z"}
        self.runs[session_id].append(run)
        return {"run_id": "run-2", "thread_id": "run-2", "status": "COMPLETED", "revision": {"final_output": "수정된 최종본"}}


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "domain.sqlite")
        persistence = SQLitePersistence(db_path)
        persistence.workflows.save(Workflow(id="wf", name="Career"))
        persistence.sessions.save(WorkflowSession(id="session-1", workflow_id="wf"))
        links = DiscordSessionLinkStore(persistence)
        controller = DiscordController(SmokeApi(), links)
        ctx = DiscordContext(external_thread_id="123456789", guild_id=1, channel_id=123456789, user_id=2)

        waiting = await controller.start(ctx, workflow_id="wf", prompt="자기소개서 작성")
        assert waiting["status"] == "WAITING_FOR_USER"
        assert "추가 근거" in render_outcome_for_discord(waiting).messages[0]
        assert links.resolve("123456789").session_id == "session-1"

        resumed = await controller.reply(ctx, answer="GOAT 프로젝트 근거")
        assert resumed["thread_id"] == "run-1"
        assert resumed["status"] == "COMPLETED"

        followup = await controller.follow_up(
            ctx,
            content="첨부 근거를 반영해 수정",
            attachments=[DiscordAttachmentPayload("evidence.txt", b"evidence", "text/plain")],
        )
        assert followup["run_id"] == "run-2"
        assert followup["thread_id"] == "run-2"
        assert links.resolve("123456789").session_id == "session-1"

        persistence.close()
        reopened = SQLitePersistence(db_path)
        restored = DiscordSessionLinkStore(reopened).resolve("123456789")
        assert restored is not None and restored.session_id == "session-1"
        reopened.close()

    print("STEP 7 Discord adapter smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
