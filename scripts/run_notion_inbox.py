from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.integrations.notion import NotionClient, NotionConfig, extract_notion_id
from agent_workflow_studio.integrations.notion_workflow import (
    NotionInboxAdapter,
    NotionInboxConfig,
    NotionSessionLinkStore,
    NotionWorkflowApiClient,
)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def build_adapter_from_env() -> tuple[NotionInboxAdapter, NotionSessionLinkStore]:
    token = _env("NOTION_API_TOKEN") or _env("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_API_TOKEN is required")
    raw_source = _env("NOTION_INBOX_DATA_SOURCE_ID")
    if not raw_source:
        raise RuntimeError("NOTION_INBOX_DATA_SOURCE_ID is required")
    data_source_id = extract_notion_id(raw_source)
    data_root = Path(_env("AWS2_DATA_DIR", "data")).expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)

    config = NotionInboxConfig(
        data_source_id=data_source_id,
        status_property=_env("NOTION_STATUS_PROPERTY", "Status"),
        ready_status=_env("NOTION_READY_STATUS", "Ready"),
        done_status=_env("NOTION_DONE_STATUS", "Done"),
        workflow_property=_env("NOTION_WORKFLOW_PROPERTY", "Workflow ID"),
        prompt_property=_env("NOTION_PROMPT_PROPERTY", "Prompt"),
        title_property=_env("NOTION_TITLE_PROPERTY", "Name"),
        result_property=_env("NOTION_RESULT_PROPERTY", "Result"),
        error_property=_env("NOTION_ERROR_PROPERTY"),
        error_status=_env("NOTION_ERROR_STATUS"),
        poll_seconds=float(_env("NOTION_POLL_SECONDS", "30")),
    )
    notion = NotionClient(NotionConfig(token=token))
    api = NotionWorkflowApiClient(_env("AWS2_API_BASE_URL", "http://127.0.0.1:8000"))
    links = NotionSessionLinkStore.from_sqlite(str(data_root / "domain.sqlite"))
    return NotionInboxAdapter(notion, api, links, config), links


async def main() -> None:
    adapter, links = build_adapter_from_env()
    try:
        await adapter.run_forever()
    finally:
        links.close()


if __name__ == "__main__":
    asyncio.run(main())
