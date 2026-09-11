from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, Sequence

NOTION_API_VERSION = "2026-03-11"
NOTION_API_BASE = "https://api.notion.com/v1"


class NotionAPIError(Exception):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class NotionConfig:
    token: str = field(repr=False)
    api_version: str = NOTION_API_VERSION
    api_base: str = NOTION_API_BASE
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise NotionAPIError(None, "Notion integration token is required")


UrlOpen = Callable[..., Any]


class NotionClient:
    """Small stdlib-only Notion API client with explicit credential dependencies.

    The class exposes only the non-destructive primitives needed by Agent Workflow
    Studio. Destructive operations are deliberately kept out of this low-level
    surface and are guarded by the STEP 8 write policy in ``notion_workflow``.
    """

    def __init__(self, config: NotionConfig, *, urlopen: UrlOpen = urllib.request.urlopen) -> None:
        self.config = config
        self._urlopen = urlopen

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.api_base.rstrip('/')}/{path.lstrip('/')}",
            data=body,
            method=method.upper(),
            headers={
                "Authorization": f"Bearer {self.config.token.strip()}",
                "Notion-Version": self.config.api_version,
                "Content-Type": "application/json",
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout) as response:
                data = response.read()
                return json.loads(data.decode("utf-8")) if data else {}
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                message = parsed.get("message") or raw
            except Exception:
                message = str(exc)
            raise NotionAPIError(getattr(exc, "code", None), str(message)) from exc
        except urllib.error.URLError as exc:
            raise NotionAPIError(None, f"Could not connect to Notion API: {exc.reason}") from exc

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return self.request("GET", f"/pages/{page_id}")

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self.request("GET", f"/data_sources/{data_source_id}")

    def query_data_source(
        self,
        data_source_id: str,
        *,
        filter: Mapping[str, Any] | None = None,
        sorts: Sequence[Mapping[str, Any]] = (),
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"page_size": max(1, min(int(page_size), 100))}
        if filter is not None:
            payload["filter"] = dict(filter)
        if sorts:
            payload["sorts"] = [dict(item) for item in sorts]
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self.request("POST", f"/data_sources/{data_source_id}/query", payload)

    def iter_data_source(
        self,
        data_source_id: str,
        *,
        filter: Mapping[str, Any] | None = None,
        sorts: Sequence[Mapping[str, Any]] = (),
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            payload = self.query_data_source(
                data_source_id,
                filter=filter,
                sorts=sorts,
                start_cursor=cursor,
                page_size=page_size,
            )
            for item in payload.get("results", []):
                if isinstance(item, Mapping):
                    yield dict(item)
            if not payload.get("has_more"):
                return
            cursor = payload.get("next_cursor")
            if not cursor:
                return

    def retrieve_block_children(
        self,
        block_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        query = f"page_size={max(1, min(int(page_size), 100))}"
        if start_cursor:
            query += f"&start_cursor={urllib.parse.quote(start_cursor)}"
        return self.request("GET", f"/blocks/{block_id}/children?{query}")

    def iter_block_children(self, block_id: str, *, page_size: int = 100) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            payload = self.retrieve_block_children(block_id, start_cursor=cursor, page_size=page_size)
            for item in payload.get("results", []):
                if isinstance(item, Mapping):
                    yield dict(item)
            if not payload.get("has_more"):
                return
            cursor = payload.get("next_cursor")
            if not cursor:
                return

    def create_page(
        self,
        *,
        parent: Mapping[str, Any],
        properties: Mapping[str, Any],
        children: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"parent": dict(parent), "properties": dict(properties)}
        if children:
            payload["children"] = [dict(item) for item in children]
        return self.request("POST", "/pages", payload)

    def update_page_properties(self, page_id: str, properties: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", f"/pages/{page_id}", {"properties": dict(properties)})

    def append_block_children(
        self,
        block_id: str,
        children: Sequence[Mapping[str, Any]],
        *,
        position: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"children": [dict(item) for item in children]}
        if position is not None:
            payload["position"] = dict(position)
        return self.request("PATCH", f"/blocks/{block_id}/children", payload)


def extract_notion_id(source: str) -> str:
    raw = (source or "").strip()
    if not raw:
        raise ValueError("Notion source is empty")
    match = re.search(
        r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        raw,
    )
    if not match:
        raise ValueError(f"Could not find a Notion id in: {raw}")
    compact = match.group(1).replace("-", "")
    try:
        return str(uuid.UUID(hex=compact))
    except ValueError as exc:
        raise ValueError(f"Invalid Notion id: {raw}") from exc


def parse_notion_source_lines(value: str) -> list[str]:
    sources: list[str] = []
    seen_ids: set[str] = set()
    for line in (value or "").splitlines():
        source = line.strip()
        if not source:
            continue
        source_id = extract_notion_id(source)
        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        sources.append(source)
    return sources


def rich_text_plain_text(items: Sequence[Mapping[str, Any]] | None) -> str:
    return "".join(str(item.get("plain_text", "")) for item in (items or []))


def notion_property_text(value: Mapping[str, Any]) -> str:
    kind = value.get("type")
    if kind == "title":
        return rich_text_plain_text(value.get("title"))
    if kind == "rich_text":
        return rich_text_plain_text(value.get("rich_text"))
    if kind == "number":
        number = value.get("number")
        return "" if number is None else str(number)
    if kind == "select":
        return str((value.get("select") or {}).get("name", ""))
    if kind == "multi_select":
        return ", ".join(str(item.get("name", "")) for item in value.get("multi_select", []))
    if kind == "status":
        return str((value.get("status") or {}).get("name", ""))
    if kind == "checkbox":
        return "true" if value.get("checkbox") else "false"
    if kind == "url":
        return str(value.get("url") or "")
    if kind == "email":
        return str(value.get("email") or "")
    if kind == "phone_number":
        return str(value.get("phone_number") or "")
    if kind == "date":
        date = value.get("date") or {}
        start = str(date.get("start") or "")
        end = str(date.get("end") or "")
        return f"{start} -> {end}" if end else start
    if kind == "people":
        return ", ".join(str(person.get("name") or person.get("id") or "") for person in (value.get("people") or []))
    if kind == "formula":
        formula = value.get("formula") or {}
        formula_type = formula.get("type")
        return "" if formula_type is None else str(formula.get(formula_type, ""))
    return ""


def block_plain_text(block: Mapping[str, Any]) -> str:
    kind = str(block.get("type") or "")
    payload = block.get(kind)
    if not isinstance(payload, Mapping):
        return ""
    if kind == "child_page":
        return str(payload.get("title") or "")
    if kind == "bookmark":
        caption = rich_text_plain_text(payload.get("caption"))
        url = str(payload.get("url") or "")
        return " ".join(part for part in (caption, url) if part)
    rich = payload.get("rich_text")
    if isinstance(rich, Sequence):
        return rich_text_plain_text(rich)
    return ""


def read_notion_page_text(client: NotionClient, source: str, *, max_blocks: int = 300) -> str:
    """Read a Notion page as untrusted reference text without mutating it."""
    page_id = extract_notion_id(source)
    page = client.retrieve_page(page_id)
    sections: list[str] = []
    properties = page.get("properties") or {}
    if isinstance(properties, Mapping):
        property_lines = []
        for name, value in properties.items():
            if isinstance(value, Mapping):
                text = notion_property_text(value).strip()
                if text:
                    property_lines.append(f"{name}: {text}")
        if property_lines:
            sections.append("[NOTION_PROPERTIES]\n" + "\n".join(property_lines))
    block_lines: list[str] = []
    for index, block in enumerate(client.iter_block_children(page_id)):
        if index >= max_blocks:
            block_lines.append("[truncated]")
            break
        text = block_plain_text(block).strip()
        if text:
            block_lines.append(text)
    if block_lines:
        sections.append("[NOTION_PAGE_CONTENT]\n" + "\n".join(block_lines))
    return "\n\n".join(sections)


def build_notion_reference_context(client: NotionClient, sources: Sequence[str]) -> str:
    sections: list[str] = []
    for source in sources:
        source_id = extract_notion_id(source)
        text = read_notion_page_text(client, source)
        sections.append(f"[NOTION_REFERENCE {source_id}]\n{text}")
    return "\n\n".join(sections)
