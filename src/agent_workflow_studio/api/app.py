from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agent_workflow_studio.core.models import Agent, RunStatus, Workflow, WorkflowMode, utc_now
from agent_workflow_studio.core.workflow import new_initial_run, new_session, validate_workflow
from agent_workflow_studio.graph import GenericWorkflowError, GenericWorkflowRuntime, SQLiteGraphCheckpointer
from agent_workflow_studio.integrations.notion import NotionClient, NotionConfig
from agent_workflow_studio.integrations.notion_workflow import NotionReferenceContextProvider
from agent_workflow_studio.integrations.openai_client import OpenAIModelProvider
from agent_workflow_studio.persistence import (
    LocalFileStore,
    PendingAttachment,
    PersistenceConflictError,
    PersistenceError,
    SQLitePersistence,
)
from agent_workflow_studio.policies.career_runtime import CareerWorkflowError, CareerWorkflowRuntime


class LazyOpenAIProvider:
    """Create the OpenAI client only when a generation call is actually made."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._provider: OpenAIModelProvider | None = None

    def generate(self, *, model: str, instructions: str, input_text: str):
        if self._provider is None:
            self._provider = OpenAIModelProvider(api_key=self.api_key)
        return self._provider.generate(model=model, instructions=instructions, input_text=input_text)


@dataclass(slots=True)
class BackendContext:
    persistence: SQLitePersistence
    checkpointer: SQLiteGraphCheckpointer
    file_store: LocalFileStore
    provider: Any
    reference_context_provider: Any | None = None
    owns_resources: bool = False

    @classmethod
    def local(cls, root: str | Path | None = None, *, provider: Any | None = None) -> "BackendContext":
        root_path = Path(root or os.getenv("AWS2_DATA_DIR", "data")).expanduser().resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        persistence = SQLitePersistence(str(root_path / "domain.sqlite"))
        checkpointer = SQLiteGraphCheckpointer(root_path / "graph.sqlite")
        file_store = LocalFileStore(root_path / "files")

        reference_context_provider = None
        notion_token = os.getenv("NOTION_API_TOKEN") or os.getenv("NOTION_TOKEN")
        if notion_token:
            notion_client = NotionClient(NotionConfig(token=notion_token))
            reference_context_provider = NotionReferenceContextProvider(notion_client)

        return cls(
            persistence=persistence,
            checkpointer=checkpointer,
            file_store=file_store,
            provider=provider or LazyOpenAIProvider(os.getenv("OPENAI_API_KEY")),
            reference_context_provider=reference_context_provider,
            owns_resources=True,
        )

    def close(self) -> None:
        if self.owns_resources:
            self.checkpointer.close()
            self.persistence.close()


class AgentPayload(BaseModel):
    id: str | None = None
    name: str
    model: str
    system_prompt: str = ""
    rag_enabled: bool = False
    rag_top_k: int = 5
    source_ids: list[str] = Field(default_factory=list)
    notion_enabled: bool = False
    notion_sources: list[str] = Field(default_factory=list)


class WorkflowPayload(BaseModel):
    id: str | None = None
    name: str
    mode: str = WorkflowMode.HIERARCHICAL.value
    include_original_prompt: bool = True
    steps: list[dict[str, Any]] = Field(default_factory=list)
    hierarchy: dict[str, Any] | None = None
    policy_id: str | None = None
    policy_config: dict[str, Any] = Field(default_factory=dict)


class SessionPayload(BaseModel):
    id: str | None = None
    workflow_id: str
    title: str = ""


class RunPayload(BaseModel):
    session_id: str
    user_request: str
    id: str | None = None
    policy: str | None = None


class ResumePayload(BaseModel):
    mode: str | None = None
    answer: Any | None = None


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _not_found(kind: str, entity_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} not found: {entity_id}")


def _workflow_policy_label(workflow: Workflow) -> str:
    return workflow.policy_id or "generic"


def _runtime_for_workflow(context: BackendContext, workflow: Workflow):
    try:
        if workflow.policy_id is None:
            return GenericWorkflowRuntime(
                workflow=workflow,
                persistence=context.persistence,
                checkpointer=context.checkpointer,
                provider=context.provider,
                file_store=context.file_store,
                reference_context_provider=context.reference_context_provider,
            )
        if workflow.policy_id == "career_cover_letter":
            return CareerWorkflowRuntime(
                workflow=workflow,
                persistence=context.persistence,
                checkpointer=context.checkpointer,
                provider=context.provider,
                file_store=context.file_store,
                reference_context_provider=context.reference_context_provider,
            )
        raise HTTPException(status_code=422, detail=f"unsupported workflow policy: {workflow.policy_id}")
    except HTTPException:
        raise
    except (GenericWorkflowError, CareerWorkflowError, PersistenceError, PersistenceConflictError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"policy": _workflow_policy_label(workflow), "message": str(exc)},
        ) from exc


def _workflow_for_session(context: BackendContext, session_id: str) -> tuple[Any, Workflow]:
    session = context.persistence.sessions.get(session_id)
    if session is None:
        raise _not_found("session", session_id)
    workflow = context.persistence.workflows.get(session.workflow_id)
    if workflow is None:
        raise _not_found("workflow", session.workflow_id)
    return session, workflow


def _runtime_for_run(context: BackendContext, run_id: str):
    run = context.persistence.runs.get(run_id)
    if run is None:
        raise _not_found("run", run_id)
    workflow = context.persistence.workflows.get(run.workflow_id)
    if workflow is None:
        raise _not_found("workflow", run.workflow_id)
    return _runtime_for_workflow(context, workflow)


def _graph_result_payload(outcome: Any) -> dict[str, Any]:
    graph = outcome.graph
    payload: dict[str, Any] = {
        "run_id": graph.run_id,
        "thread_id": graph.thread_id,
        "status": graph.status.value,
        "state": _serialize(graph.state),
        "interrupts": _serialize(graph.interrupts),
    }
    if graph.error_type:
        payload["error_type"] = graph.error_type
        payload["error_message"] = graph.error_message
    if outcome.revision is not None:
        payload["revision"] = _serialize(outcome.revision)
    return payload


def create_app(context: BackendContext | None = None) -> FastAPI:
    ctx = context or BackendContext.local()
    app = FastAPI(title="Agent Workflow Studio API", version="2.0-r3")
    app.state.backend = ctx

    if ctx.owns_resources:
        @app.on_event("shutdown")
        def _shutdown() -> None:
            ctx.close()

    @app.exception_handler(PersistenceConflictError)
    async def _persistence_conflict(_, exc: PersistenceConflictError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(PersistenceError)
    async def _persistence_error(_, exc: PersistenceError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(CareerWorkflowError)
    async def _career_error(_, exc: CareerWorkflowError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": {"policy": "career_cover_letter", "message": str(exc)}})

    @app.exception_handler(GenericWorkflowError)
    async def _generic_error(_, exc: GenericWorkflowError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": {"policy": "generic", "message": str(exc)}})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "agent-workflow-studio"}

    @app.get("/agents")
    def list_agents() -> list[dict[str, Any]]:
        return [_serialize(item) for item in ctx.persistence.agents.list()]

    @app.post("/agents", status_code=201)
    def create_agent(payload: AgentPayload) -> dict[str, Any]:
        entity_id = payload.id or str(uuid4())
        if ctx.persistence.agents.get(entity_id) is not None:
            raise HTTPException(status_code=409, detail=f"agent already exists: {entity_id}")
        agent = Agent(id=entity_id, **payload.model_dump(exclude={"id"}))
        ctx.persistence.agents.save(agent)
        return _serialize(agent)

    @app.get("/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, Any]:
        agent = ctx.persistence.agents.get(agent_id)
        if agent is None:
            raise _not_found("agent", agent_id)
        return _serialize(agent)

    @app.put("/agents/{agent_id}")
    def update_agent(agent_id: str, payload: AgentPayload) -> dict[str, Any]:
        existing = ctx.persistence.agents.get(agent_id)
        if existing is None:
            raise _not_found("agent", agent_id)
        agent = Agent(
            id=agent_id,
            created_at=existing.created_at,
            updated_at=utc_now(),
            **payload.model_dump(exclude={"id"}),
        )
        ctx.persistence.agents.save(agent)
        return _serialize(agent)

    @app.delete("/agents/{agent_id}", status_code=204)
    def delete_agent(agent_id: str) -> None:
        if ctx.persistence.agents.get(agent_id) is None:
            raise _not_found("agent", agent_id)
        ctx.persistence.agents.delete(agent_id)

    @app.get("/workflows")
    def list_workflows() -> list[dict[str, Any]]:
        return [_serialize(item) for item in ctx.persistence.workflows.list()]

    def _workflow_from_payload(payload: WorkflowPayload, workflow_id: str, existing: Workflow | None = None) -> Workflow:
        data = payload.model_dump(exclude={"id"})
        data["id"] = workflow_id
        data["created_at"] = existing.created_at.isoformat() if existing else utc_now().isoformat()
        data["updated_at"] = utc_now().isoformat()
        workflow = Workflow.from_dict(data)
        return validate_workflow(workflow)

    @app.post("/workflows", status_code=201)
    def create_workflow(payload: WorkflowPayload) -> dict[str, Any]:
        workflow_id = payload.id or str(uuid4())
        if ctx.persistence.workflows.get(workflow_id) is not None:
            raise HTTPException(status_code=409, detail=f"workflow already exists: {workflow_id}")
        workflow = _workflow_from_payload(payload, workflow_id)
        ctx.persistence.workflows.save(workflow)
        return _serialize(workflow)

    @app.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        workflow = ctx.persistence.workflows.get(workflow_id)
        if workflow is None:
            raise _not_found("workflow", workflow_id)
        return _serialize(workflow)

    @app.put("/workflows/{workflow_id}")
    def update_workflow(workflow_id: str, payload: WorkflowPayload) -> dict[str, Any]:
        existing = ctx.persistence.workflows.get(workflow_id)
        if existing is None:
            raise _not_found("workflow", workflow_id)
        workflow = _workflow_from_payload(payload, workflow_id, existing)
        ctx.persistence.workflows.save(workflow)
        return _serialize(workflow)

    @app.delete("/workflows/{workflow_id}", status_code=204)
    def delete_workflow(workflow_id: str) -> None:
        if ctx.persistence.workflows.get(workflow_id) is None:
            raise _not_found("workflow", workflow_id)
        ctx.persistence.workflows.delete(workflow_id)

    @app.get("/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        return [_serialize(item) for item in ctx.persistence.sessions.list()]

    @app.post("/sessions", status_code=201)
    def create_session(payload: SessionPayload) -> dict[str, Any]:
        workflow = ctx.persistence.workflows.get(payload.workflow_id)
        if workflow is None:
            raise _not_found("workflow", payload.workflow_id)
        session = new_session(workflow, session_id=payload.id, title=payload.title)
        if ctx.persistence.sessions.get(session.id) is not None:
            raise HTTPException(status_code=409, detail=f"session already exists: {session.id}")
        ctx.persistence.sessions.save(session)
        return _serialize(session)

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = ctx.persistence.sessions.get(session_id)
        if session is None:
            raise _not_found("session", session_id)
        return _serialize(session)

    @app.get("/sessions/{session_id}/messages")
    def list_session_messages(session_id: str) -> list[dict[str, Any]]:
        if ctx.persistence.sessions.get(session_id) is None:
            raise _not_found("session", session_id)
        return [_serialize(item) for item in ctx.persistence.messages.list(session_id=session_id)]

    @app.get("/sessions/{session_id}/runs")
    def list_session_runs(session_id: str) -> list[dict[str, Any]]:
        if ctx.persistence.sessions.get(session_id) is None:
            raise _not_found("session", session_id)
        return [_serialize(item) for item in ctx.persistence.runs.list(session_id=session_id)]

    @app.get("/sessions/{session_id}/artifacts")
    def list_session_artifacts(session_id: str) -> list[dict[str, Any]]:
        if ctx.persistence.sessions.get(session_id) is None:
            raise _not_found("session", session_id)
        return [_serialize(item) for item in ctx.persistence.artifacts.list() if item.session_id == session_id]

    @app.get("/sessions/{session_id}/revisions")
    def list_session_revisions(session_id: str) -> list[dict[str, Any]]:
        if ctx.persistence.sessions.get(session_id) is None:
            raise _not_found("session", session_id)
        return [_serialize(item) for item in ctx.persistence.revisions.list(session_id=session_id)]

    @app.post("/runs", status_code=201)
    def start_run(payload: RunPayload) -> dict[str, Any]:
        session, workflow = _workflow_for_session(ctx, payload.session_id)
        stored_policy = _workflow_policy_label(workflow)
        if payload.policy is not None and payload.policy != stored_policy:
            raise HTTPException(
                status_code=409,
                detail=f"run policy override does not match stored workflow policy: requested={payload.policy}, stored={stored_policy}",
            )
        if ctx.persistence.runs.list_active():
            raise HTTPException(status_code=409, detail="another active run already exists")
        runtime = _runtime_for_workflow(ctx, workflow)
        run = new_initial_run(session, run_id=payload.id)
        ctx.persistence.runs.save(run)
        try:
            outcome = runtime.start_initial(run, user_request=payload.user_request)
        except Exception:
            latest = ctx.persistence.runs.get(run.id)
            if latest is not None and latest.status == RunStatus.CREATED:
                ctx.persistence.runs.delete(run.id)
            raise
        return _graph_result_payload(outcome)

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = ctx.persistence.runs.get(run_id)
        if run is None:
            raise _not_found("run", run_id)
        runtime = _runtime_for_run(ctx, run_id)
        state = runtime.engine.get_state(run_id)
        return {"run": _serialize(run), "state": _serialize(state), "thread_id": run_id}

    @app.get("/runs/{run_id}/history")
    def get_run_history(run_id: str) -> list[dict[str, Any]]:
        if ctx.persistence.runs.get(run_id) is None:
            raise _not_found("run", run_id)
        runtime = _runtime_for_run(ctx, run_id)
        return [
            {
                "checkpoint_id": item.checkpoint_id,
                "next_nodes": list(item.next_nodes),
                "state": _serialize(item.state),
                "created_at": item.created_at,
            }
            for item in runtime.engine.get_history(run_id)
        ]

    @app.post("/runs/{run_id}/resume")
    def resume_run(run_id: str, payload: ResumePayload) -> dict[str, Any]:
        run = ctx.persistence.runs.get(run_id)
        if run is None:
            raise _not_found("run", run_id)
        runtime = _runtime_for_run(ctx, run_id)
        mode = payload.mode or ("user" if run.status == RunStatus.WAITING_FOR_USER else "error")
        if mode == "user":
            if run.status != RunStatus.WAITING_FOR_USER:
                raise HTTPException(status_code=409, detail="user resume requires WAITING_FOR_USER")
            outcome = runtime.resume_with_user(run_id, payload.answer)
        elif mode == "error":
            if run.status != RunStatus.PAUSED:
                raise HTTPException(status_code=409, detail="error resume requires PAUSED")
            outcome = runtime.resume_after_error(run_id)
        else:
            raise HTTPException(status_code=422, detail="resume mode must be user or error")
        return _graph_result_payload(outcome)

    @app.post("/sessions/{session_id}/messages", status_code=201)
    async def post_followup_message(
        session_id: str,
        previous_run_id: str = Form(...),
        content: str = Form(...),
        files: Sequence[UploadFile] = File(default=()),
    ) -> dict[str, Any]:
        _, workflow = _workflow_for_session(ctx, session_id)
        previous_run = ctx.persistence.runs.get(previous_run_id)
        if previous_run is None:
            raise _not_found("run", previous_run_id)
        if previous_run.workflow_id != workflow.id or previous_run.session_id != session_id:
            raise HTTPException(status_code=409, detail="previous run does not belong to this workflow session")
        uploads: list[PendingAttachment] = []
        for upload in files:
            data = await upload.read()
            uploads.append(PendingAttachment(filename=upload.filename or "attachment", data=data, mime_type=upload.content_type))
        runtime = _runtime_for_workflow(ctx, workflow)
        outcome = runtime.start_followup(
            session_id=session_id,
            previous_run_id=previous_run_id,
            content=content,
            uploads=uploads,
        )
        return _graph_result_payload(outcome)

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> dict[str, Any]:
        artifact = ctx.persistence.artifacts.get(artifact_id)
        if artifact is None:
            raise _not_found("artifact", artifact_id)
        return _serialize(artifact)

    @app.get("/revisions/{revision_id}")
    def get_revision(revision_id: str) -> dict[str, Any]:
        revision = ctx.persistence.revisions.get(revision_id)
        if revision is None:
            raise _not_found("revision", revision_id)
        return _serialize(revision)

    return app


app = create_app()
