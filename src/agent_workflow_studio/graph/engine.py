from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent_workflow_studio.core.models import RunStatus
from agent_workflow_studio.core.workflow import set_run_status
from agent_workflow_studio.persistence.records import ExecutionEvent
from agent_workflow_studio.persistence.services import PersistedFollowUp
from agent_workflow_studio.persistence.sqlite import SQLitePersistence

from .checkpoint import SQLiteGraphCheckpointer
from .errors import GraphLifecycleError, GraphStateValidationError, UnknownStageError
from .handlers import StageHandler
from .state import WorkflowGraphState, assert_checkpoint_safe, build_graph_state


Finalizer = Callable[[WorkflowGraphState], str]


@dataclass(frozen=True, slots=True)
class GraphCheckpointView:
    checkpoint_id: str | None
    next_nodes: tuple[str, ...]
    state: Mapping[str, Any]
    created_at: str | None


@dataclass(frozen=True, slots=True)
class GraphRunResult:
    run_id: str
    thread_id: str
    status: RunStatus
    state: Mapping[str, Any]
    interrupts: tuple[Any, ...] = ()
    error_type: str | None = None
    error_message: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == RunStatus.COMPLETED


class DurableGraphEngine:
    """Generic LangGraph execution boundary for STEP 3.

    The engine intentionally knows nothing about W1-W6 or cover-letter policy. A Run
    maps 1:1 to one LangGraph thread. Agent-requested HITL resumes the same thread;
    post-result follow-up starts a new Continuation Run and therefore a new thread.
    """

    def __init__(
        self,
        handlers: Mapping[str, StageHandler],
        checkpointer: SQLiteGraphCheckpointer,
        *,
        persistence: SQLitePersistence | None = None,
        finalizer: Finalizer | None = None,
    ) -> None:
        self.handlers = dict(handlers)
        self.checkpointer = checkpointer
        self.persistence = persistence
        self.finalizer = finalizer
        self.graph = self._compile_graph()

    @staticmethod
    def thread_id_for_run(run_id: str) -> str:
        if not run_id.strip():
            raise GraphStateValidationError("run_id is required for graph thread mapping")
        return run_id

    def _config(self, run_id: str, *, stage_count: int = 0) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": self.thread_id_for_run(run_id)},
            "recursion_limit": max(100, stage_count * 6 + 20),
        }

    def _compile_graph(self):
        builder = StateGraph(WorkflowGraphState)
        builder.add_node("select_stage", self._select_stage)
        builder.add_node("prepare_human_gate", self._prepare_human_gate)
        builder.add_node("human_interrupt", self._human_interrupt)
        builder.add_node("execute_stage", self._execute_stage)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "select_stage")
        builder.add_conditional_edges(
            "select_stage",
            self._route_after_select,
            {"gate": "prepare_human_gate", "finish": "finalize"},
        )
        builder.add_conditional_edges(
            "prepare_human_gate",
            self._route_after_gate,
            {"interrupt": "human_interrupt", "execute": "execute_stage"},
        )
        builder.add_edge("human_interrupt", "execute_stage")
        builder.add_edge("execute_stage", "select_stage")
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=self.checkpointer.saver)

    def _handler(self, stage: str) -> StageHandler:
        try:
            return self.handlers[stage]
        except KeyError as exc:
            raise UnknownStageError(f"no handler registered for stage: {stage}") from exc

    def _select_stage(self, state: WorkflowGraphState) -> dict[str, Any]:
        completed = set(state.get("completed_stages", []))
        pending = [stage for stage in state.get("pending_stages", []) if stage not in completed]
        current = pending[0] if pending else ""
        return {
            "pending_stages": pending,
            "current_stage": current,
            "waiting_for_user": False,
            "interrupt_question": "",
            "interrupt_payload": {},
        }

    @staticmethod
    def _route_after_select(state: WorkflowGraphState) -> str:
        return "gate" if state.get("current_stage") else "finish"

    def _prepare_human_gate(self, state: WorkflowGraphState) -> dict[str, Any]:
        stage = state["current_stage"]
        request = self._handler(stage).request_input(state, stage)
        if request is None:
            return {
                "waiting_for_user": False,
                "interrupt_question": "",
                "interrupt_payload": {},
            }
        payload = {
            "kind": "agent_requested_hitl",
            "session_id": state["session_id"],
            "run_id": state["run_id"],
            "stage": stage,
            "question": request.question,
            "payload": dict(request.payload),
        }
        assert_checkpoint_safe(payload, "interrupt_payload")
        return {
            "waiting_for_user": True,
            "interrupt_question": request.question,
            "interrupt_payload": payload,
        }

    @staticmethod
    def _route_after_gate(state: WorkflowGraphState) -> str:
        return "interrupt" if state.get("waiting_for_user") else "execute"

    def _human_interrupt(self, state: WorkflowGraphState) -> dict[str, Any]:
        stage = state["current_stage"]
        answer = interrupt(dict(state["interrupt_payload"]))
        assert_checkpoint_safe(answer, f"human_answer.{stage}")
        answers = dict(state.get("human_answers", {}))
        answers[stage] = answer
        messages = list(state.get("messages", []))
        messages.append({"role": "user", "content": str(answer), "stage": stage})
        return {
            "human_answers": answers,
            "messages": messages,
            "waiting_for_user": False,
            "interrupt_question": "",
            "interrupt_payload": {},
        }

    def _execute_stage(self, state: WorkflowGraphState) -> dict[str, Any]:
        stage = state["current_stage"]
        completed = list(state.get("completed_stages", []))
        pending = list(state.get("pending_stages", []))
        outputs = dict(state.get("stage_outputs", {}))
        artifacts = dict(state.get("artifacts", {}))

        # Defensive idempotency guard. LangGraph pending writes already avoid replaying
        # successful nodes; this additionally prevents duplicate state outputs if a
        # stage is accidentally routed twice.
        if stage in completed or stage in outputs:
            pending = [item for item in pending if item != stage]
            if stage not in completed:
                completed.append(stage)
            return {
                "pending_stages": pending,
                "completed_stages": completed,
            }

        human_input = state.get("human_answers", {}).get(stage)
        result = self._handler(stage).execute(state, stage, human_input)
        assert_checkpoint_safe(result.output, f"stage_result.{stage}.output")
        assert_checkpoint_safe(dict(result.metadata), f"stage_result.{stage}.metadata")

        outputs[stage] = result.output
        if result.artifact_ref:
            artifacts[stage] = {
                "ref": result.artifact_ref,
                "metadata": dict(result.metadata),
            }
        completed.append(stage)
        pending = [item for item in pending if item != stage]
        messages = list(state.get("messages", []))
        messages.append({"role": "agent", "content": result.output, "stage": stage})
        history = list(state.get("node_history", []))
        history.append(stage)

        update = {
            "pending_stages": pending,
            "completed_stages": completed,
            "stage_outputs": outputs,
            "artifacts": artifacts,
            "messages": messages,
            "node_history": history,
        }
        assert_checkpoint_safe(update, f"stage_update.{stage}")
        return update

    def _finalize(self, state: WorkflowGraphState) -> dict[str, Any]:
        if self.finalizer is not None:
            final_output = self.finalizer(state)
        else:
            completed = state.get("completed_stages", [])
            outputs = state.get("stage_outputs", {})
            final_output = outputs.get(completed[-1], "") if completed else ""
        if not isinstance(final_output, str):
            raise GraphStateValidationError("finalizer must return a string")
        assert_checkpoint_safe(final_output, "final_output")
        return {
            "current_stage": "",
            "waiting_for_user": False,
            "interrupt_question": "",
            "interrupt_payload": {},
            "final_output": final_output,
        }

    def _domain_run(self, run_id: str):
        if self.persistence is None:
            return None
        run = self.persistence.runs.get(run_id)
        if run is None:
            raise GraphLifecycleError(f"domain Run not found: {run_id}")
        return run

    def _require_status(self, run_id: str, allowed: set[RunStatus]) -> None:
        run = self._domain_run(run_id)
        if run is not None and run.status not in allowed:
            expected = ", ".join(sorted(status.value for status in allowed))
            raise GraphLifecycleError(
                f"Run {run_id} is {run.status.value}; expected one of: {expected}"
            )

    def _set_domain_status(self, run_id: str, status: RunStatus) -> None:
        run = self._domain_run(run_id)
        if run is None:
            return
        self.persistence.runs.save(set_run_status(run, status))

    def _record_event(
        self,
        run_id: str,
        event_type: str,
        *,
        state: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        run = self._domain_run(run_id)
        if run is None:
            return
        stage = str((state or {}).get("current_stage", ""))
        safe_data = dict(data or {})
        assert_checkpoint_safe(safe_data, "execution_event.data")
        self.persistence.events.save(
            ExecutionEvent(
                id=str(uuid4()),
                session_id=run.session_id,
                run_id=run.id,
                event_type=event_type,
                stage=stage,
                data=safe_data,
            )
        )

    @staticmethod
    def _extract_interrupts(output: Any, snapshot: Any) -> tuple[Any, ...]:
        values: list[Any] = []
        if isinstance(output, Mapping):
            for item in output.get("__interrupt__", ()) or ():
                values.append(getattr(item, "value", item))
        if not values and snapshot is not None:
            for task in getattr(snapshot, "tasks", ()) or ():
                for item in getattr(task, "interrupts", ()) or ():
                    values.append(getattr(item, "value", item))
        return tuple(values)

    def _snapshot_state(self, run_id: str) -> dict[str, Any]:
        snapshot = self.graph.get_state(self._config(run_id))
        values = getattr(snapshot, "values", None) or {}
        return dict(values)

    def _invoke(self, run_id: str, graph_input: Any) -> GraphRunResult:
        config = self._config(run_id)
        try:
            output = self.graph.invoke(graph_input, config=config)
        except Exception as exc:
            state = self._snapshot_state(run_id)
            self._set_domain_status(run_id, RunStatus.PAUSED)
            self._record_event(
                run_id,
                "graph_paused_error",
                state=state,
                data={"error_type": type(exc).__name__},
            )
            return GraphRunResult(
                run_id=run_id,
                thread_id=self.thread_id_for_run(run_id),
                status=RunStatus.PAUSED,
                state=state,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        snapshot = self.graph.get_state(config)
        state = dict(getattr(snapshot, "values", None) or {})
        interrupts = self._extract_interrupts(output, snapshot)
        if interrupts:
            self._set_domain_status(run_id, RunStatus.WAITING_FOR_USER)
            self._record_event(run_id, "graph_waiting_for_user", state=state)
            return GraphRunResult(
                run_id=run_id,
                thread_id=self.thread_id_for_run(run_id),
                status=RunStatus.WAITING_FOR_USER,
                state=state,
                interrupts=interrupts,
            )

        next_nodes = tuple(getattr(snapshot, "next", ()) or ())
        if next_nodes:
            # A normal invoke should only return early for an interrupt. Treat any
            # other suspended state as paused and require an explicit Resume.
            self._set_domain_status(run_id, RunStatus.PAUSED)
            self._record_event(run_id, "graph_paused", state=state, data={"next_nodes": list(next_nodes)})
            return GraphRunResult(
                run_id=run_id,
                thread_id=self.thread_id_for_run(run_id),
                status=RunStatus.PAUSED,
                state=state,
            )

        self._set_domain_status(run_id, RunStatus.COMPLETED)
        self._record_event(run_id, "graph_completed", state=state)
        return GraphRunResult(
            run_id=run_id,
            thread_id=self.thread_id_for_run(run_id),
            status=RunStatus.COMPLETED,
            state=state,
        )

    def start(self, state: WorkflowGraphState) -> GraphRunResult:
        assert_checkpoint_safe(state)
        run_id = state["run_id"]
        if state["run_id"] != self.thread_id_for_run(run_id):
            raise GraphStateValidationError("Run/thread mapping is invalid")
        existing = self._snapshot_state(run_id)
        if existing:
            raise GraphLifecycleError(
                f"graph thread already exists for Run {run_id}; use a Resume operation instead"
            )
        self._require_status(run_id, {RunStatus.CREATED})
        self._set_domain_status(run_id, RunStatus.RUNNING)
        self._record_event(run_id, "graph_started", state=state)
        return self._invoke(run_id, state)

    def start_followup(
        self,
        followup: PersistedFollowUp,
        *,
        stages: list[str] | tuple[str, ...],
        draft_version: int = 0,
        review_status: str = "",
    ) -> GraphRunResult:
        if followup.previous_run.status != RunStatus.COMPLETED:
            raise GraphLifecycleError("follow-up graph requires a completed previous Run")
        state = build_graph_state(
            session_id=followup.session.id,
            run_id=followup.run.id,
            stages=stages,
            follow_up_message=followup.message.content,
            follow_up_attachment_refs=[item.storage_ref for item in followup.attachments],
            draft_version=draft_version,
            review_status=review_status,
        )
        return self.start(state)

    def resume_after_error(self, run_id: str) -> GraphRunResult:
        self._require_status(run_id, {RunStatus.PAUSED})
        state = self._snapshot_state(run_id)
        if not state:
            raise GraphLifecycleError(f"no checkpoint state exists for Run {run_id}")
        self._set_domain_status(run_id, RunStatus.RUNNING)
        self._record_event(run_id, "graph_manual_resume", state=state, data={"reason": "error_or_pause"})
        return self._invoke(run_id, None)

    def resume_with_user(self, run_id: str, answer: Any) -> GraphRunResult:
        assert_checkpoint_safe(answer, "resume_answer")
        self._require_status(run_id, {RunStatus.WAITING_FOR_USER})
        state = self._snapshot_state(run_id)
        if not state or not state.get("waiting_for_user"):
            raise GraphLifecycleError(f"Run {run_id} is not checkpointed at a human interrupt")
        self._set_domain_status(run_id, RunStatus.RUNNING)
        self._record_event(run_id, "graph_human_resume", state=state)
        return self._invoke(run_id, Command(resume=answer))

    def get_state(self, run_id: str) -> dict[str, Any]:
        return self._snapshot_state(run_id)

    def get_history(self, run_id: str) -> list[GraphCheckpointView]:
        history: list[GraphCheckpointView] = []
        for snapshot in self.graph.get_state_history(self._config(run_id)):
            configurable = dict((snapshot.config or {}).get("configurable", {}))
            history.append(
                GraphCheckpointView(
                    checkpoint_id=configurable.get("checkpoint_id"),
                    next_nodes=tuple(getattr(snapshot, "next", ()) or ()),
                    state=dict(getattr(snapshot, "values", None) or {}),
                    created_at=getattr(snapshot, "created_at", None),
                )
            )
        return history
