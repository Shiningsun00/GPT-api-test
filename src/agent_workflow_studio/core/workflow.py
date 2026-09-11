from __future__ import annotations

from dataclasses import replace
from typing import Iterable
from uuid import uuid4

from .errors import WorkflowValidationError
from .models import Run, RunKind, RunStatus, Workflow, WorkflowMode, WorkflowSession, utc_now


def new_session(workflow: Workflow, *, session_id: str | None = None, title: str = "") -> WorkflowSession:
    return WorkflowSession(id=session_id or str(uuid4()), workflow_id=workflow.id, title=title)


def new_initial_run(session: WorkflowSession, *, run_id: str | None = None) -> Run:
    return Run(
        id=run_id or str(uuid4()),
        session_id=session.id,
        workflow_id=session.workflow_id,
        kind=RunKind.INITIAL,
        status=RunStatus.CREATED,
    )


def new_continuation_run(
    session: WorkflowSession,
    previous_run: Run,
    *,
    trigger_message_id: str,
    run_id: str | None = None,
) -> Run:
    if previous_run.session_id != session.id:
        raise WorkflowValidationError("previous run belongs to a different session")
    if previous_run.workflow_id != session.workflow_id:
        raise WorkflowValidationError("previous run belongs to a different workflow")
    if previous_run.status != RunStatus.COMPLETED:
        raise WorkflowValidationError("post-result follow-up requires a completed previous run")
    if not trigger_message_id:
        raise WorkflowValidationError("continuation run requires a trigger message")
    return Run(
        id=run_id or str(uuid4()),
        session_id=session.id,
        workflow_id=session.workflow_id,
        kind=RunKind.CONTINUATION,
        status=RunStatus.CREATED,
        parent_run_id=previous_run.id,
        trigger_message_id=trigger_message_id,
    )


def set_run_status(run: Run, status: RunStatus) -> Run:
    now = utc_now()
    updates = {"status": status, "updated_at": now}
    if status == RunStatus.RUNNING and run.started_at is None:
        updates["started_at"] = now
    if status.terminal:
        updates["completed_at"] = now
    return replace(run, **updates)


def ensure_single_active_run(runs: Iterable[Run]) -> None:
    active = [run.id for run in runs if run.status in {RunStatus.CREATED, RunStatus.RUNNING, RunStatus.WAITING_FOR_USER}]
    if len(active) > 1:
        raise WorkflowValidationError(f"only one active run is allowed; found {active}")


def validate_workflow(workflow: Workflow) -> Workflow:
    if not workflow.id.strip() or not workflow.name.strip():
        raise WorkflowValidationError("workflow id and name are required")
    if workflow.mode == WorkflowMode.LINEAR:
        step_ids = [step.step_id for step in workflow.steps]
        if len(step_ids) != len(set(step_ids)):
            raise WorkflowValidationError("linear step ids must be unique")
    if workflow.mode in {WorkflowMode.HIERARCHICAL, WorkflowMode.GRAPH} and workflow.hierarchy is None:
        raise WorkflowValidationError("hierarchical or graph workflow requires hierarchy config")
    if workflow.hierarchy:
        worker_ids = [worker.worker_id for worker in workflow.hierarchy.workers]
        if len(worker_ids) != len(set(worker_ids)):
            raise WorkflowValidationError("worker slot ids must be unique")
    return workflow
