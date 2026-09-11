from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

import httpx

from agent_workflow_studio.core.models import Agent, utc_now
from agent_workflow_studio.persistence import ExternalThreadLink, SQLitePersistence

from .notion import (
    NotionAPIError,
    NotionClient,
    block_plain_text,
    build_notion_reference_context,
    extract_notion_id,
    notion_property_text,
)


class NotionInteractionError(RuntimeError):
    pass


class NotionSafetyError(NotionInteractionError):
    pass


@dataclass(frozen=True, slots=True)
class DestructiveApproval:
    approved: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class NotionWritePolicy:
    """Safety boundary for Notion writes.

    Creation, append and updates to explicitly designated properties are allowed.
    Destructive actions and broad/large overwrite actions require a positive,
    explicit approval object. STEP 8 never performs those destructive actions.
    """

    large_overwrite_threshold: int = 8_000

    def require(
        self,
        action: str,
        *,
        designated: bool = True,
        overwrite_chars: int = 0,
        approval: DestructiveApproval | None = None,
    ) -> None:
        normalized = action.strip().lower()
        destructive = normalized in {"delete", "trash", "erase_content", "overwrite_body"}
        broad_property_update = normalized == "property_update" and not designated
        large_overwrite = normalized.startswith("overwrite") and overwrite_chars > self.large_overwrite_threshold
        if destructive or broad_property_update or large_overwrite:
            if approval is None or not approval.approved or not approval.reason.strip():
                raise NotionSafetyError(f"explicit destructive approval required for Notion action: {action}")

    def allow_create(self) -> None:
        self.require("create")

    def allow_append(self) -> None:
        self.require("append")

    def allow_designated_property_update(self) -> None:
        self.require("property_update", designated=True)


@dataclass(frozen=True, slots=True)
class NotionInboxConfig:
    data_source_id: str
    status_property: str = "Status"
    ready_status: str = "Ready"
    done_status: str = "Done"
    workflow_property: str = "Workflow ID"
    prompt_property: str = "Prompt"
    title_property: str = "Name"
    result_property: str = "Result"
    error_property: str = ""
    error_status: str = ""
    poll_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.data_source_id.strip():
            raise ValueError("Notion data_source_id is required")
        if not self.status_property.strip():
            raise ValueError("Notion status property is required")
        if not self.workflow_property.strip() or not self.prompt_property.strip():
            raise ValueError("Notion workflow and prompt properties are required")
        if self.poll_seconds < 5:
            raise ValueError("Notion poll_seconds must be at least 5 seconds")


@dataclass(frozen=True, slots=True)
class NotionTask:
    page_id: str
    workflow_id: str
    prompt: str
    title: str
    properties: Mapping[str, Any] = field(default_factory=dict)


class NotionWorkflowApi(Protocol):
    async def create_session(self, *, workflow_id: str, title: str = "") -> Mapping[str, Any]: ...

    async def start_run(self, *, session_id: str, user_request: str) -> Mapping[str, Any]: ...

    async def list_session_runs(self, session_id: str) -> Sequence[Mapping[str, Any]]: ...

    async def list_session_revisions(self, session_id: str) -> Sequence[Mapping[str, Any]]: ...


class NotionWorkflowApiClient:
    """HTTP adapter that keeps Notion orchestration outside the FastAPI service."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", *, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", response.text) if isinstance(payload, Mapping) else response.text
            except Exception:
                detail = response.text
            raise NotionInteractionError(f"API {response.status_code}: {detail}")
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

    async def list_session_revisions(self, session_id: str) -> Sequence[Mapping[str, Any]]:
        return await self._request("GET", f"/sessions/{session_id}/revisions")


class NotionSessionLinkStore:
    """Durable Notion page ↔ WorkflowSession mapping using STEP 2 storage."""

    provider = "notion"

    def __init__(self, persistence: SQLitePersistence, *, owns_persistence: bool = False) -> None:
        self.persistence = persistence
        self.owns_persistence = owns_persistence

    @classmethod
    def from_sqlite(cls, path: str) -> "NotionSessionLinkStore":
        return cls(SQLitePersistence(path), owns_persistence=True)

    def get(self, page_id: str) -> ExternalThreadLink | None:
        return self.persistence.external_thread_links.get_by_external(self.provider, page_id)

    def bind(
        self,
        page_id: str,
        session_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExternalThreadLink:
        existing = self.get(page_id)
        if existing is not None and existing.session_id != session_id:
            raise NotionInteractionError(f"Notion page is already linked to another Session: {page_id}")
        merged = dict(existing.metadata) if existing is not None else {}
        merged.update(dict(metadata or {}))
        link = ExternalThreadLink(
            id=existing.id if existing is not None else str(uuid4()),
            provider=self.provider,
            external_thread_id=page_id,
            session_id=session_id,
            metadata=merged,
            created_at=existing.created_at if existing is not None else utc_now(),
            updated_at=utc_now(),
        )
        self.persistence.external_thread_links.save(link)
        return link

    def update_metadata(self, page_id: str, **updates: Any) -> ExternalThreadLink:
        existing = self.get(page_id)
        if existing is None:
            raise NotionInteractionError(f"Notion page has no Session mapping: {page_id}")
        return self.bind(page_id, existing.session_id, metadata=updates)

    def close(self) -> None:
        if self.owns_persistence:
            self.persistence.close()


class NotionReferenceContextProvider:
    """Callable adapter for CareerWorkflowRuntime's reference-context boundary."""

    def __init__(self, client: NotionClient) -> None:
        self.client = client

    def __call__(self, agent: Agent) -> str:
        if not agent.notion_enabled or not agent.notion_sources:
            return ""
        return build_notion_reference_context(self.client, agent.notion_sources)


def _property(properties: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = properties.get(name)
    if not isinstance(value, Mapping):
        raise NotionInteractionError(f"Notion property is missing: {name}")
    return value


def _status_payload(kind: str, value: str) -> dict[str, Any]:
    if kind not in {"status", "select"}:
        raise NotionInteractionError(f"Status property must be status or select, got: {kind}")
    return {kind: {"name": value}}


def _rich_text_payload(text: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": text}}]}


def _text_block(kind: str, text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": kind,
        kind: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _split_text(text: str, size: int = 1_800) -> list[str]:
    value = str(text or "")
    return [value[index : index + size] for index in range(0, len(value), size)] or [""]


class NotionInboxAdapter:
    RESULT_MARKER_PREFIX = "AWS2-REVISION:"

    def __init__(
        self,
        notion: NotionClient,
        api: NotionWorkflowApi,
        links: NotionSessionLinkStore,
        config: NotionInboxConfig,
        *,
        write_policy: NotionWritePolicy | None = None,
    ) -> None:
        self.notion = notion
        self.api = api
        self.links = links
        self.config = config
        self.write_policy = write_policy or NotionWritePolicy()
        self._data_source_schema: dict[str, Any] | None = None

    def _schema(self) -> Mapping[str, Any]:
        if self._data_source_schema is None:
            self._data_source_schema = self.notion.retrieve_data_source(self.config.data_source_id)
        return self._data_source_schema

    def _property_schema(self, name: str) -> Mapping[str, Any] | None:
        properties = self._schema().get("properties") or {}
        value = properties.get(name) if isinstance(properties, Mapping) else None
        return value if isinstance(value, Mapping) else None

    def _status_kind(self) -> str:
        schema = self._property_schema(self.config.status_property)
        if schema is None:
            raise NotionInteractionError(f"Notion status property is missing: {self.config.status_property}")
        kind = str(schema.get("type") or "")
        if kind not in {"status", "select"}:
            raise NotionInteractionError(f"Notion status property must be status or select, got: {kind}")
        return kind

    def _ready_filter(self) -> Mapping[str, Any]:
        kind = self._status_kind()
        return {"property": self.config.status_property, kind: {"equals": self.config.ready_status}}

    def parse_task(self, page: Mapping[str, Any]) -> NotionTask:
        page_id = str(page.get("id") or "").strip()
        if not page_id:
            raise NotionInteractionError("Notion task page has no id")
        properties = page.get("properties") or {}
        if not isinstance(properties, Mapping):
            raise NotionInteractionError(f"Notion task has invalid properties: {page_id}")
        workflow_id = notion_property_text(_property(properties, self.config.workflow_property)).strip()
        prompt = notion_property_text(_property(properties, self.config.prompt_property)).strip()
        title_value = properties.get(self.config.title_property)
        title = notion_property_text(title_value).strip() if isinstance(title_value, Mapping) else ""
        if not workflow_id:
            raise NotionInteractionError(f"Notion task Workflow ID is empty: {page_id}")
        if not prompt:
            raise NotionInteractionError(f"Notion task Prompt is empty: {page_id}")
        return NotionTask(
            page_id=page_id,
            workflow_id=workflow_id,
            prompt=prompt,
            title=title or f"Notion {page_id[:8]}",
            properties=dict(properties),
        )

    def ready_tasks(self) -> list[NotionTask]:
        tasks: list[NotionTask] = []
        for item in self.notion.iter_data_source(self.config.data_source_id, filter=self._ready_filter()):
            if item.get("object") == "page":
                tasks.append(self.parse_task(item))
        return tasks

    @staticmethod
    def _latest(items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        if not items:
            return None
        return max(
            items,
            key=lambda item: (
                int(item.get("version") or 0),
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
        )

    async def process_task(self, task: NotionTask) -> Mapping[str, Any]:
        link = self.links.get(task.page_id)
        if link is None:
            session = await self.api.create_session(workflow_id=task.workflow_id, title=task.title)
            session_id = str(session.get("id") or "")
            if not session_id:
                raise NotionInteractionError("FastAPI session response has no id")
            self.links.bind(
                task.page_id,
                session_id,
                metadata={"workflow_id": task.workflow_id, "state": "session_created"},
            )
        else:
            session_id = link.session_id

        runs = list(await self.api.list_session_runs(session_id))
        if not runs:
            await self.api.start_run(session_id=session_id, user_request=task.prompt)
            runs = list(await self.api.list_session_runs(session_id))
            if not runs:
                raise NotionInteractionError("Initial Run was not persisted")

        latest_run = self._latest(runs)
        assert latest_run is not None
        status = str(latest_run.get("status") or "")
        run_id = str(latest_run.get("id") or "")
        self.links.update_metadata(task.page_id, last_run_id=run_id, last_status=status)

        if status == "completed":
            return await self._finalize(task, session_id, latest_run)
        return {"page_id": task.page_id, "session_id": session_id, "run_id": run_id, "status": status, "action": "observed"}

    def _page_contains_marker(self, page_id: str, marker: str) -> bool:
        for block in self.notion.iter_block_children(page_id):
            if marker in block_plain_text(block):
                return True
        return False

    def _append_result(self, page_id: str, revision_id: str, final_output: str) -> None:
        marker = f"{self.RESULT_MARKER_PREFIX}{revision_id}"
        if self._page_contains_marker(page_id, marker):
            return
        self.write_policy.allow_append()
        blocks = [_text_block("heading_2", "Agent Workflow Studio Result")]
        blocks.extend(_text_block("paragraph", chunk) for chunk in _split_text(final_output))
        blocks.append(_text_block("paragraph", marker))
        for index in range(0, len(blocks), 100):
            self.notion.append_block_children(page_id, blocks[index : index + 100])

    def _designated_property_updates(self, final_output: str) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        status_kind = self._status_kind()
        properties[self.config.status_property] = _status_payload(status_kind, self.config.done_status)
        result_name = self.config.result_property.strip()
        result_schema = self._property_schema(result_name) if result_name else None
        if result_name and result_schema is not None and result_schema.get("type") == "rich_text" and len(final_output) <= 1_800:
            properties[result_name] = _rich_text_payload(final_output)
        return properties

    async def _finalize(
        self,
        task: NotionTask,
        session_id: str,
        latest_run: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        revisions = list(await self.api.list_session_revisions(session_id))
        revision = self._latest(revisions)
        if revision is None:
            raise NotionInteractionError("Completed Run has no Revision to write to Notion")
        revision_id = str(revision.get("id") or "")
        final_output = str(revision.get("final_output") or "")
        if not revision_id:
            raise NotionInteractionError("Revision has no id")

        self._append_result(task.page_id, revision_id, final_output)
        self.write_policy.allow_designated_property_update()
        properties = self._designated_property_updates(final_output)
        self.notion.update_page_properties(task.page_id, properties)
        self.links.update_metadata(
            task.page_id,
            state="done",
            finalized_revision_id=revision_id,
            last_status="completed",
        )
        return {
            "page_id": task.page_id,
            "session_id": session_id,
            "run_id": str(latest_run.get("id") or ""),
            "revision_id": revision_id,
            "status": "completed",
            "action": "finalized",
        }

    def _mark_error(self, task: NotionTask, exc: Exception) -> None:
        updates: dict[str, Any] = {}
        if self.config.error_status:
            updates[self.config.status_property] = _status_payload(self._status_kind(), self.config.error_status)
        if self.config.error_property:
            schema = self._property_schema(self.config.error_property)
            if schema is not None and schema.get("type") == "rich_text":
                safe_message = str(exc).replace(self.notion.config.token, "[REDACTED]")[:1_800]
                updates[self.config.error_property] = _rich_text_payload(safe_message)
        if updates:
            self.write_policy.allow_designated_property_update()
            self.notion.update_page_properties(task.page_id, updates)

    async def poll_once(self) -> list[Mapping[str, Any]]:
        results: list[Mapping[str, Any]] = []
        for task in self.ready_tasks():
            try:
                results.append(await self.process_task(task))
            except Exception as exc:
                try:
                    self._mark_error(task, exc)
                except Exception:
                    pass
                results.append({"page_id": task.page_id, "status": "error", "error": type(exc).__name__})
        return results

    async def run_forever(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self.config.poll_seconds)
