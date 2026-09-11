# Agent Workflow Studio 2.0

Agent Workflow Studio 2.0 is a local-first, single-user multi-agent workflow application. It separates the React UI, FastAPI service boundary, LangGraph durable state machine, domain persistence, retrieval, workflow policy, and external integrations so a workflow can stop, recover, ask for human input, continue, and preserve immutable history without using Streamlit session state as the database.

## Architecture

```text
React / Tauri Desktop
        |
        v
     FastAPI
        |
        v
    LangGraph
     /     \
  Core    SQLite
    |       |
 OpenAI   Local files
            |
      Notion / Discord adapters
```

The generic engine is independent from the Career Cover Letter W1-W6 policy. A `WorkflowSession` can contain multiple Runs. Agent-requested HITL resumes the same Run; a user follow-up after a completed Manager result creates a new Continuation Run in the same Session.

## Final 2.0 capabilities

- Agent CRUD with system prompts and optional retrieval settings.
- Linear and Hierarchical workflow definitions with distinct Worker Slot IDs, including duplicate Agent slots.
- Durable SQLite domain records plus LangGraph SQLite checkpoints.
- Explicit Manual Resume after process restart or worker failure; startup never auto-resumes API/LLM work.
- Initial Run execution-file upload persisted before LLM execution.
- Manager post-result follow-up with turn-scoped attachments and immutable Revision history.
- React Local UI with Run Studio, Agents, Workflows, History, and Settings.
- Discord remote interaction adapter with allowlists and durable channel/session mapping.
- Notion read-only references plus Ready-based Workflow Inbox and idempotent final-result write-back.
- Legacy `agent_workspace.zip` schema v1-v4 import, including RAG file hash validation.
- Verified local backup, offline restore, rotating/redacted logs, and safe unreferenced-file cleanup.
- Tauri v2 desktop shell with a PyInstaller FastAPI backend sidecar packaging path.

## Run locally for development

Python 3.11 is the tested backend version.

```bash
python -m pip install -r requirements.txt
python scripts/run_local_studio.py --data-dir data
```

In another terminal:

```bash
cd ui
npm install
npm run dev
```

The Vite development UI uses `/api` and proxies it to `http://127.0.0.1:8765`. The final local backend listens on loopback by default.

Set credentials only in the backend environment when the related integration is needed:

```text
OPENAI_API_KEY
NOTION_API_TOKEN   # or NOTION_TOKEN
DISCORD_BOT_TOKEN  # Discord runner only
```

Credentials are not entered in the React UI and are not intentionally persisted to the domain DB, graph checkpoints, Workspace import, backup archive, or application log.

## Desktop package

Install the desktop-only Python build dependency, Node dependencies, and a current Rust toolchain, then run:

```bash
python -m pip install -r requirements-desktop.txt
python scripts/build_desktop.py
```

The build script creates a PyInstaller backend sidecar named for the Rust target triple and then invokes the Tauri build. Platform installers/bundles are produced under Tauri's normal `ui/src-tauri/target/release/bundle` directory. See `docs/step9_desktop.md` for prerequisites and lifecycle details.

## Backup and recovery

A running Studio may create a consistent backup from **Settings → Backup & recovery**. The backup contains SQLite snapshots and the local file store, but excludes logs and runtime lock files. Restore is deliberately offline-only:

```bash
python scripts/restore_backup.py /path/to/aws2-backup-....zip --overwrite
```

Stop Agent Workflow Studio before restoring. The restore command verifies entry hashes and SQLite `quick_check` before replacing data.

## Legacy Workspace import

Use **Settings → Legacy Workspace import** or `POST /maintenance/import-workspace` to import legacy schema v1-v4 `agent_workspace.zip` files. Import preserves Agent/Workflow semantics, validates RAG bytes against legacy hashes/sizes, and migrates file bytes to content-addressed local source storage. Legacy Run/Revision history was not contained in the old Workspace format and therefore cannot be reconstructed from the ZIP alone.

## Verification

```bash
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
python scripts/manual_final_acceptance_test.py

cd ui
npm test
npm run build
```

The final acceptance runner composes the credential-free STEP 3/4/5/7/8/9 smoke suites and maps them to the roadmap's 19 acceptance scenarios. Discord and Notion live-workspace credentials are intentionally not required by CI; their adapters are tested with deterministic fake transports.

## Project documentation

- `docs/PRD.md` — approved product definition.
- `docs/migration_spec.md` — legacy baseline and migration contract.
- `docs/Agent_Workflow_Studio_2.0_Roadmap_GCB.md` — staged roadmap and acceptance gate.
- `docs/step7_discord.md` — Discord setup and safety boundary.
- `docs/step8_notion.md` — Notion Inbox/reference setup.
- `docs/step9_desktop.md` — desktop, backup, recovery, cleanup, and final operations.

The root `app.py` remains the frozen legacy Streamlit reference used during migration. Agent Workflow Studio 2.0 runtime code lives under `src/agent_workflow_studio/` and `ui/`.
