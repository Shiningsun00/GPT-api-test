# STEP 8 — Notion Interaction Run Guide

STEP 8 adds Notion as a local polling interaction adapter. Notion does not execute Workflow logic directly: a Ready row creates/observes a Workflow Session through the existing FastAPI service, and a completed Revision is written back to the same Notion page.

## 1. Notion integration and permissions

Create a Notion integration, connect it to the target data source/database, and grant the minimum capabilities required by your use case.

For the Inbox + result write-back flow the integration needs to read the data source/page and update/append content. Keep the integration token outside Git and SQLite.

The client uses Notion API version `2026-03-11` and queries a data source through:

```text
POST /v1/data_sources/{data_source_id}/query
```

## 2. Default Workflow Inbox properties

Create a data source with these default properties, or override their names with environment variables.

| Property | Suggested type | Purpose |
| --- | --- | --- |
| `Name` | title | Workflow Session title |
| `Status` | status or select | `Ready` → `Done` |
| `Workflow ID` | rich_text | Workflow ID created in Local UI |
| `Prompt` | rich_text | Initial Run request |
| `Result` | rich_text | Optional short final result mirror |

The full final output is appended to the task page body. If `Result` exists as a rich-text property and the final output is short enough, it is mirrored there as well.

## 3. Environment

```bash
export OPENAI_API_KEY="..."
export NOTION_API_TOKEN="..."
export NOTION_INBOX_DATA_SOURCE_ID="11111111-2222-3333-4444-555555555555"
export AWS2_DATA_DIR="data"
export AWS2_API_BASE_URL="http://127.0.0.1:8000"

# Optional property/status overrides
export NOTION_STATUS_PROPERTY="Status"
export NOTION_READY_STATUS="Ready"
export NOTION_DONE_STATUS="Done"
export NOTION_WORKFLOW_PROPERTY="Workflow ID"
export NOTION_PROMPT_PROPERTY="Prompt"
export NOTION_TITLE_PROPERTY="Name"
export NOTION_RESULT_PROPERTY="Result"
export NOTION_POLL_SECONDS="30"

# Optional error write-back. Leave unset to avoid mutating task state on adapter errors.
# export NOTION_ERROR_PROPERTY="Error"
# export NOTION_ERROR_STATUS="Error"
```

`NOTION_API_TOKEN` and `OPENAI_API_KEY` are environment-only secrets. They are not written to `external_thread_links`, domain SQLite, checkpoints, or repository files.

## 4. Start services

Terminal 1 — backend:

```bash
uvicorn agent_workflow_studio.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Terminal 2 — Notion polling adapter:

```bash
python scripts/run_notion_inbox.py
```

Set a task's `Status` to `Ready`. The adapter will:

```text
Ready Notion page
→ parse Workflow ID / Prompt / Name
→ create WorkflowSession through FastAPI
→ persist Notion page ↔ Session mapping
→ create Initial Run through FastAPI
→ observe durable Run state on later polls
→ when COMPLETED, load latest Revision
→ append final result to the Notion page
→ set Status = Done
```

If the Run is `WAITING_FOR_USER` or `PAUSED`, the adapter does not auto-resume it. Use Local UI or Discord for the explicit HITL/Resume action. This preserves the manual-resume rule.

## 5. Idempotency

The mapping uses the existing `external_thread_links` table with provider `notion`, so repeated polls do not create duplicate Sessions/Runs for the same Notion page.

Before appending a completed Revision, STEP 8 checks for a durable page marker:

```text
AWS2-REVISION:<revision_id>
```

If an external write succeeded but the local metadata update failed, the next poll detects that marker and does not append the same Revision twice.

## 6. Write safety

Allowed by default:

```text
create page
append blocks
update explicitly designated properties (Status / Result / configured Error)
```

Not allowed without a positive `DestructiveApproval` object containing an explicit reason:

```text
delete / trash
erase_content
whole-page/body overwrite
non-designated property overwrite
large overwrite
```

STEP 8's Inbox flow itself never invokes destructive operations. It only appends page blocks and updates designated task properties.

## 7. Notion as Agent reference source

`NotionReferenceContextProvider` converts configured Agent `notion_sources` into read-only reference context using page properties and block text. Reference content is treated as untrusted data by the existing Agent execution boundary.

No Notion read operation modifies the referenced page.

## 8. Credential-free smoke test

```bash
python scripts/manual_notion_smoke_test.py
```

The smoke test verifies without a real Notion token:

```text
Ready task parse
→ Session creation
→ Initial Run
→ durable Notion page ↔ Session mapping
→ completed Revision write-back
→ Done status
→ SQLite close/reopen mapping recovery
```

Actual workspace validation requires the user's Notion integration token and a test data source. Perform that validation after merging STEP 8 or before merge if you want to test against a disposable Notion Inbox.
