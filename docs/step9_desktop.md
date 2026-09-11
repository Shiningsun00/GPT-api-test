# STEP 9 — Desktop / Migration / Final QA

## Product runtime

The final product runtime is `agent_workflow_studio.runtime.server`. It binds to loopback (`127.0.0.1`) by default, mounts the final FastAPI service under `/api`, and never resumes a persisted Run merely because the process has restarted.

Default local data directories:

- Windows: `%LOCALAPPDATA%\AgentWorkflowStudio`
- macOS: `~/Library/Application Support/AgentWorkflowStudio`
- Linux: `$XDG_DATA_HOME/agent-workflow-studio` or `~/.local/share/agent-workflow-studio`

`AWS2_DATA_DIR` overrides the default. The runtime creates a `.runtime.lock` containing only PID/start time. A stale lock from a hard kill is discarded when its PID is no longer alive.

## Local browser development

```bash
python -m pip install -r requirements.txt
python scripts/run_local_studio.py --data-dir data

cd ui
npm install
npm run dev
```

Vite proxies `/api` to `127.0.0.1:8765`. The React UI does not provide secret fields.

## Tauri desktop packaging

The desktop shell is under `ui/src-tauri/`. Tauri owns the window lifecycle and starts the packaged backend as the `aws2-backend` sidecar. On app exit it kills the child process. The backend itself closes the LangGraph SQLite checkpointer and domain SQLite persistence in its `finally` path and releases the runtime lock.

Install platform prerequisites before packaging:

1. Python 3.11 and `requirements-desktop.txt`.
2. Node.js/npm for the React build.
3. A current Rust toolchain and the normal Tauri v2 OS prerequisites for the target platform.

Then run:

```bash
python -m pip install -r requirements-desktop.txt
python scripts/build_desktop.py
```

The script asks Rust for the host target triple, builds `scripts/aws2_sidecar_entry.py` with PyInstaller, writes `ui/src-tauri/binaries/aws2-backend-<target-triple>[.exe]`, then runs `npm run desktop:build`.

The generated sidecar and Tauri `target/` directory are ignored by Git. CI validates the desktop configuration and packaging contract but does not publish a cross-platform installer artifact from the Linux unit-test job.

## Secrets

Supported credentials remain environment-only:

```text
OPENAI_API_KEY
NOTION_API_TOKEN / NOTION_TOKEN
DISCORD_BOT_TOKEN
```

The rotating application log is written to `<data-dir>/logs/studio.log`, with 2 MiB rotation and three backups by default. Known credential values plus bearer/OpenAI-style token shapes are redacted by the log formatter. Logs are excluded from backup archives.

## Backup

A live backup is safe because both SQLite databases are copied with SQLite's backup API rather than by copying their active files directly. The archive contains:

```text
manifest.json
domain.sqlite
graph.sqlite
files/...
```

`manifest.json` contains only format metadata, timestamps, entry sizes, and SHA-256 hashes. It contains no environment values or log content.

Create a backup from Settings or the API:

```text
POST /maintenance/backups
```

Every newly created archive is immediately revalidated. Validation checks safe ZIP paths, manifest hashes/sizes, both required SQLite snapshots, and SQLite `PRAGMA quick_check`.

## Offline restore

Restore is intentionally not exposed as a live FastAPI mutation. Stop the Studio and run:

```bash
python scripts/restore_backup.py /path/to/aws2-backup-....zip --overwrite
```

Restore refuses to operate when the target data directory has a live runtime lock. The archive is fully validated before any existing data is replaced.

## Cleanup

`POST /maintenance/cleanup` defaults to dry-run. Candidates are local file-store entries that are not referenced by any of these durable records:

- permanent `ReferenceSource.storage_ref`
- `MessageAttachment.storage_ref`
- `ExecutionFile.storage_ref`

Only `{"apply": true}` deletes the candidates. Referenced durable files are never cleanup candidates.

## Legacy `agent_workspace.zip` import

`POST /maintenance/import-workspace` and Settings support schemas 1–4. The import-only bridge:

- rejects ZIP path traversal and oversized archives;
- validates the declared schema version;
- strips secret-like manifest fields instead of persisting them;
- preserves Agent model/system prompt/RAG settings and Notion source references;
- finds legacy `rag_files/<agent>/...` bytes, validates SHA-256/size when declared, and stores the bytes through the content-addressed LocalFileStore;
- preserves Linear step order;
- preserves Hierarchical Manager/Worker Slot structure, including two different Worker Slot IDs pointing to the same Agent;
- uses deterministic workflow IDs derived from the Workspace archive digest;
- supports `fail` or `skip` conflict policy and never silently replaces an existing Agent/Workflow.

Legacy Workspace ZIPs did not contain durable 2.0 Session/Run/Artifact/Revision/checkpoint history, so that history is not fabricated during import.

## Initial Run files

Final QA found that the JSON-only STEP 5 `/runs` route did not allow the roadmap's “Initial Run + file” acceptance scenario. STEP 9 therefore adds `POST /runs/with-files`. Uploaded files are stored as durable `ExecutionFile` records before the workflow runtime starts. If no target IDs are supplied, the file is available to all workflow stages; otherwise only matching stage/role/Agent targets receive it.

The original JSON `/runs` endpoint remains available for Runs without files.

## Recovery invariant

On startup the product only opens persisted state. It does not call OpenAI, Discord, or Notion to resume an unfinished Run. A `WAITING_FOR_USER` Run requires an explicit HITL answer; a `PAUSED` Run requires explicit Manual Resume. A completed Manager result never re-enters RUNNING: later user feedback creates a Continuation Run in the same WorkflowSession.

## Final acceptance

Run:

```bash
python scripts/manual_final_acceptance_test.py
```

This credential-free suite composes STEP 3, STEP 4, STEP 5, STEP 7, STEP 8, and STEP 9 smoke scenarios and maps them to the roadmap acceptance steps 1–19. It covers process reopen/manual resume, HITL same-Run resume, immutable revision history, initial/follow-up files, Continuation Run routing, Discord interaction semantics, Notion idempotent final write-back, backup/import/restore, and history traceability.

Live external-service credentials are deliberately excluded from CI. Before production use of Discord or Notion, perform the corresponding documented live setup test with a disposable/test channel or Data Source.
