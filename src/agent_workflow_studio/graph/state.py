from __future__ import annotations

from typing import Any, Mapping, TypedDict

from .errors import GraphStateValidationError


class GraphMessage(TypedDict):
    role: str
    content: str
    stage: str


class GraphArtifact(TypedDict):
    ref: str
    metadata: dict[str, Any]


class WorkflowGraphState(TypedDict):
    session_id: str
    run_id: str
    user_request: str
    follow_up_message: str
    follow_up_attachment_refs: list[str]
    current_stage: str
    pending_stages: list[str]
    completed_stages: list[str]
    stage_outputs: dict[str, str]
    artifacts: dict[str, GraphArtifact]
    messages: list[GraphMessage]
    human_answers: dict[str, Any]
    draft_version: int
    review_status: str
    waiting_for_user: bool
    interrupt_question: str
    interrupt_payload: dict[str, Any]
    final_output: str
    node_history: list[str]


_FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "apikey",
    "openai_api_key",
    "openai_token",
    "notion_api_key",
    "notion_token",
    "discord_token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "client_secret",
}


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def assert_checkpoint_safe(value: Any, path: str = "state") -> None:
    """Reject values that must never enter LangGraph checkpoint storage.

    The graph state intentionally stays JSON-like. File bytes and credentials must be
    persisted elsewhere and represented here only by durable references.
    """

    if isinstance(value, (bytes, bytearray, memoryview)):
        raise GraphStateValidationError(f"binary value is not allowed in checkpoint state: {path}")
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in _FORBIDDEN_SECRET_KEYS:
                raise GraphStateValidationError(f"secret-like key is not allowed in checkpoint state: {path}.{key}")
            assert_checkpoint_safe(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_checkpoint_safe(item, f"{path}[{index}]")
        return
    raise GraphStateValidationError(
        f"checkpoint state must use JSON-safe primitives, mappings, and sequences: {path} ({type(value).__name__})"
    )


def build_graph_state(
    *,
    session_id: str,
    run_id: str,
    stages: list[str] | tuple[str, ...],
    user_request: str = "",
    follow_up_message: str = "",
    follow_up_attachment_refs: list[str] | tuple[str, ...] = (),
    draft_version: int = 0,
    review_status: str = "",
) -> WorkflowGraphState:
    clean_stages = [str(stage).strip() for stage in stages]
    if not session_id.strip():
        raise GraphStateValidationError("session_id is required")
    if not run_id.strip():
        raise GraphStateValidationError("run_id is required")
    if any(not stage for stage in clean_stages):
        raise GraphStateValidationError("stage names cannot be empty")
    if len(clean_stages) != len(set(clean_stages)):
        raise GraphStateValidationError("stage names must be unique within one Run")
    refs = [str(ref).strip() for ref in follow_up_attachment_refs]
    if any(not ref for ref in refs):
        raise GraphStateValidationError("attachment references cannot be empty")
    if draft_version < 0:
        raise GraphStateValidationError("draft_version cannot be negative")

    messages: list[GraphMessage] = []
    if user_request:
        messages.append({"role": "user", "content": user_request, "stage": ""})
    if follow_up_message:
        messages.append({"role": "user", "content": follow_up_message, "stage": "follow_up"})

    state: WorkflowGraphState = {
        "session_id": session_id,
        "run_id": run_id,
        "user_request": user_request,
        "follow_up_message": follow_up_message,
        "follow_up_attachment_refs": refs,
        "current_stage": "",
        "pending_stages": clean_stages,
        "completed_stages": [],
        "stage_outputs": {},
        "artifacts": {},
        "messages": messages,
        "human_answers": {},
        "draft_version": draft_version,
        "review_status": review_status,
        "waiting_for_user": False,
        "interrupt_question": "",
        "interrupt_payload": {},
        "final_output": "",
        "node_history": [],
    }
    assert_checkpoint_safe(state)
    return state
