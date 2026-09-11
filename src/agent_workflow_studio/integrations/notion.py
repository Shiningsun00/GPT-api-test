from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

NOTION_API_VERSION = "2026-03-11"
NOTION_API_BASE = "https://api.notion.com/v1"


class NotionAPIError(Exception):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class NotionConfig:
    token: str
    api_version: str = NOTION_API_VERSION
    api_base: str = NOTION_API_BASE
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise NotionAPIError(None, "Notion integration token is required")


UrlOpen = Callable[..., Any]


class NotionClient:
    """Small stdlib-only Notion client with explicit token/config dependencies."""

    def __init__(self, config: NotionConfig, *, urlopen: UrlOpen = urllib.request.urlopen) -> None:
        self.config = config
        self._urlopen = urlopen

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
        request = urllib.request.Request(f"{self.config.api_base.rstrip('/')}/{path.lstrip('/')}", data=body, method=method.upper(), headers={"Authorization": f"Bearer {self.config.token.strip()}", "Notion-Version": self.config.api_version, "Content-Type": "application/json"})
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


def extract_notion_id(source: str) -> str:
    raw = (source or "").strip()
    if not raw:
        raise ValueError("Notion source is empty")
    match = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", raw)
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


def rich_text_plain_text(items: list[Mapping[str, Any]] | None) -> str:
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
    return ""
