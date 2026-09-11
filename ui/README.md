# Agent Workflow Studio 2.0 — Local UI

STEP 6 adds a React + Vite local client on top of the STEP 5 FastAPI service.

## Run locally

Terminal 1 — backend:

```bash
uvicorn agent_workflow_studio.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Terminal 2 — UI:

```bash
cd ui
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

The default UI API base is `/api`. Vite proxies `/api/*` to `http://127.0.0.1:8000/*`, so no browser CORS configuration is required for the standard local setup. Set `AWS2_API_TARGET` before starting Vite if the backend uses another local address.

## Product boundaries

- Form/List editor first; no visual node editor in STEP 6.
- OpenAI API keys stay in backend environment variables and are never stored by the browser UI.
- A WAITING_FOR_USER run resumes the same Run/thread.
- A completed result follow-up creates a new Continuation Run under the same Session.
- Follow-up attachments are turn-scoped by default and are not promoted to permanent RAG sources.
- Restarting the UI does not automatically resume or trigger API work.

## Validation

```bash
npm test
npm run build
```
