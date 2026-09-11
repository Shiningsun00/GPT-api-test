from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol, Sequence
from uuid import uuid4

import httpx

from agent_workflow_studio.persistence import ExternalThreadLink, SQLitePersistence


class DiscordAdapterError(RuntimeError):
    pass


class DiscordPermissionError(DiscordAdapterError):
    pass


class DiscordSessionNotLinkedError(DiscordAdapterError):
    pass


@dataclass(frozen=True, slots=True)
class DiscordAttachmentPayload:
    filename: str
    data: bytes
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class DiscordAllowlist:
    guild_ids: frozenset[int] = frozenset()
    user_ids: frozenset[int] = frozenset()
    channel_ids: frozenset[int] = frozenset()

    def check(self, *, guild_id: int | None, user_id: int, channel_id: int) -> None:
        if self.guild_ids and (guild_id is None or guild_id not in self.guild_ids):
            raise DiscordPermissionError("guild is not allowed")
        if self.user_ids and user_id not in self.user_ids:
            raise DiscordPermissionError("user is not allowed")
        if self.channel_ids and channel_id not in self.channel_ids:
            raise DiscordPermissionError("channel is not allowed")


@dataclass(frozen=True, slots=True)
class DiscordContext:
    external_thread_id: str
    guild_id: int | None
    channel_id: int
    user_id: int

    @property
    def metadata(self) -> Mapping[str, Any]:
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
        }


@dataclass(frozen=True, slots=True)
class RenderedDiscordResult:
    messages: tuple[str, ...]
    filename: str | None = None
    file_bytes: bytes | None = None


class WorkflowApi(Protocol):
    async def create_session(self, *, workflow_id: str, title: str = "") -> Mapping[str, Any]: ...

    async def start_run(self, *, session_id: str, user_request: str) -> Mapping[str, Any]: ...

    async def list_session_runs(self, session_id: str) -> Sequence[Mapping[str, Any]]: ...

    async def get_run(self, run_id: str) -> Mapping[str, Any]: ...

    async def resume_run(self, run_id: str, *, mode: str, answer: Any | None = None) -> Mapping[str, Any]: ...

    async def follow_up(
        self,
        *,
        session_id: str,
        previous_run_id: str,
        content: str,
        attachments: Sequence[DiscordAttachmentPayload],
    ) -> Mapping[str, Any]: ...


class DiscordWorkflowApiClient:
    """Async HTTP client for the STEP 5 FastAPI service boundary."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", *, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise DiscordAdapterError(f"API {response.status_code}: {detail}")
        if response.status_code == 204:
            return None
        return response.json()

    async def create_session(self, *, workflow_id: str, title: str = "") -> Mapping[str, Any]:
        return await self._request("POST", "/sessions", json={"workflow_id": workflow_id, "title": title})

    async def start_run(self, *, session_id: str, user_request: str) -> Mapping[str, Any]:
        return await self._request(
            "POST",
            "/runs",
            json={"session_id": session_id, "user_request": user_request, "policy": "career_cover_letter"},
        )

    async def list_session_runs(self, session_id: str) -> Sequence[Mapping[str, Any]]:
        return await self._request("GET", f"/sessions/{session_id}/runs")

    async def get_run(self, run_id: str) -> Mapping[str, Any]:
        return await self._request("GET", f"/runs/{run_id}")

    async def resume_run(self, run_id: str, *, mode: str, answer: Any | None = None) -> Mapping[str, Any]:
        payload: dict[str, Any] = {"mode": mode}
        if answer is not None:
            payload["answer"] = answer
        return await self._request("POST", f"/runs/{run_id}/resume", json=payload)

    async def follow_up(
        self,
        *,
        session_id: str,
        previous_run_id: str,
        content: str,
        attachments: Sequence[DiscordAttachmentPayload],
    ) -> Mapping[str, Any]:
        files = [
            ("files", (item.filename, item.data, item.content_type or "application/octet-stream"))
            for item in attachments
        ]
        data = {"previous_run_id": previous_run_id, "content": content}
        return await self._request("POST", f"/sessions/{session_id}/messages", data=data, files=files)


class DiscordSessionLinkStore:
    """Durable Discord channel/thread to WorkflowSession mapping.

    Only adapter metadata lives here. Workflow state mutations still go through FastAPI.
    """

    def __init__(self, persistence: SQLitePersistence, *, owns_persistence: bool = False) -> None:
        self.persistence = persistence
        self.owns_persistence = owns_persistence

    @classmethod
    def from_sqlite(cls, path: str) -> "DiscordSessionLinkStore":
        return cls(SQLitePersistence(path), owns_persistence=True)

    def bind(self, external_thread_id: str, session_id: str, metadata: Mapping[str, Any] | None = None) -> ExternalThreadLink:
        existing = self.persistence.external_thread_links.get_by_external("discord", external_thread_id)
        now = datetime.now(timezone.utc)
        link = ExternalThreadLink(
            id=existing.id if existing else str(uuid4()),
            provider="discord",
            external_thread_id=external_thread_id,
            session_id=session_id,
            metadata=dict(metadata or {}),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.persistence.external_thread_links.save(link)
        return link

    def resolve(self, external_thread_id: str) -> ExternalThreadLink | None:
        return self.persistence.external_thread_links.get_by_external("discord", external_thread_id)

    def close(self) -> None:
        if self.owns_persistence:
            self.persistence.close()


class DiscordController:
    """Command-level adapter. It never contains workflow orchestration logic."""

    def __init__(
        self,
        api: WorkflowApi,
        links: DiscordSessionLinkStore,
        *,
        allowlist: DiscordAllowlist | None = None,
    ) -> None:
        self.api = api
        self.links = links
        self.allowlist = allowlist or DiscordAllowlist()

    def authorize(self, context: DiscordContext) -> None:
        self.allowlist.check(guild_id=context.guild_id, user_id=context.user_id, channel_id=context.channel_id)

    async def start(self, context: DiscordContext, *, workflow_id: str, prompt: str, title: str = "") -> Mapping[str, Any]:
        self.authorize(context)
        session = await self.api.create_session(workflow_id=workflow_id, title=title or "Discord session")
        session_id = str(session["id"])
        self.links.bind(context.external_thread_id, session_id, context.metadata)
        return await self.api.start_run(session_id=session_id, user_request=prompt)

    async def status(self, context: DiscordContext) -> Mapping[str, Any]:
        self.authorize(context)
        session_id = self._session_id(context)
        run = await self._latest_run(session_id)
        detail = await self.api.get_run(str(run["id"]))
        return {"session_id": session_id, "run": run, "detail": detail}

    async def reply(self, context: DiscordContext, *, answer: str) -> Mapping[str, Any]:
        self.authorize(context)
        session_id = self._session_id(context)
        run = await self._latest_run(session_id)
        if str(run.get("status")) != "WAITING_FOR_USER":
            raise DiscordAdapterError("latest run is not WAITING_FOR_USER")
        return await self.api.resume_run(str(run["id"]), mode="user", answer=answer)

    async def resume(self, context: DiscordContext) -> Mapping[str, Any]:
        self.authorize(context)
        session_id = self._session_id(context)
        run = await self._latest_run(session_id)
        if str(run.get("status")) != "PAUSED":
            raise DiscordAdapterError("latest run is not PAUSED")
        return await self.api.resume_run(str(run["id"]), mode="error")

    async def follow_up(
        self,
        context: DiscordContext,
        *,
        content: str,
        attachments: Sequence[DiscordAttachmentPayload] = (),
    ) -> Mapping[str, Any]:
        self.authorize(context)
        session_id = self._session_id(context)
        run = await self._latest_run(session_id)
        if str(run.get("status")) != "COMPLETED":
            raise DiscordAdapterError("follow-up requires a COMPLETED latest run")
        return await self.api.follow_up(
            session_id=session_id,
            previous_run_id=str(run["id"]),
            content=content,
            attachments=attachments,
        )

    def _session_id(self, context: DiscordContext) -> str:
        link = self.links.resolve(context.external_thread_id)
        if link is None:
            raise DiscordSessionNotLinkedError("this Discord channel/thread is not linked to a WorkflowSession")
        return link.session_id

    async def _latest_run(self, session_id: str) -> Mapping[str, Any]:
        runs = list(await self.api.list_session_runs(session_id))
        if not runs:
            raise DiscordAdapterError("linked session has no runs")
        runs.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))))
        return runs[-1]


def render_outcome_for_discord(outcome: Mapping[str, Any], *, max_message_chars: int = 1800) -> RenderedDiscordResult:
    status = str(outcome.get("status") or outcome.get("run", {}).get("status") or "UNKNOWN")
    revision = outcome.get("revision") or {}
    final_output = str(revision.get("final_output") or "")
    interrupts = outcome.get("interrupts") or []

    if status == "WAITING_FOR_USER":
        question = _interrupt_text(interrupts) or "Agent가 추가 입력을 기다리고 있습니다. `/aws_reply`로 답변해 주세요."
        return RenderedDiscordResult(messages=(f"상태: WAITING_FOR_USER\n{question}",))

    if status == "PAUSED":
        error_message = str(outcome.get("error_message") or "실행이 일시 중지되었습니다.")
        return RenderedDiscordResult(messages=(f"상태: PAUSED\n{error_message}\n`/aws_resume`으로 수동 재개할 수 있습니다.",))

    if status == "COMPLETED" and final_output:
        prefix = "상태: COMPLETED\n\n"
        if len(prefix) + len(final_output) <= max_message_chars:
            return RenderedDiscordResult(messages=(prefix + final_output,))
        preview = final_output[: min(900, max_message_chars - 120)].rstrip()
        return RenderedDiscordResult(
            messages=(f"상태: COMPLETED\n\n{preview}\n\n전체 결과는 첨부 파일을 확인해 주세요.",),
            filename="agent-workflow-result.md",
            file_bytes=final_output.encode("utf-8"),
        )

    if status == "COMPLETED":
        return RenderedDiscordResult(messages=("상태: COMPLETED",))

    return RenderedDiscordResult(messages=(f"상태: {status}",))


def render_status_for_discord(payload: Mapping[str, Any]) -> RenderedDiscordResult:
    run = payload.get("run") or {}
    detail = payload.get("detail") or {}
    state = detail.get("state") or {}
    run_id = str(run.get("id") or detail.get("run", {}).get("id") or "-")
    status = str(run.get("status") or detail.get("run", {}).get("status") or "UNKNOWN")
    current_stage = str(state.get("current_stage") or state.get("stage") or "-")
    return RenderedDiscordResult(
        messages=(
            f"Session: {payload.get('session_id', '-')}\n"
            f"Run: {run_id}\n"
            f"Status: {status}\n"
            f"Stage: {current_stage}",
        )
    )


def _interrupt_text(interrupts: Iterable[Any]) -> str:
    for item in interrupts:
        if isinstance(item, Mapping):
            value = item.get("value", item)
            if isinstance(value, Mapping):
                for key in ("question", "message", "prompt"):
                    if value.get(key):
                        return str(value[key])
            if value:
                return str(value)
        elif item:
            return str(item)
    return ""
