from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from agent_workflow_studio.core.models import AttachmentScope, Message, MessageAttachment, MessageRole, Run, WorkflowSession, utc_now
from agent_workflow_studio.core.workflow import new_continuation_run

from .errors import PersistenceConflictError, PersistenceError
from .files import LocalFileStore, StoredFile
from .sqlite import SQLitePersistence


@dataclass(frozen=True, slots=True)
class PendingAttachment:
    filename: str
    data: bytes
    mime_type: str | None = None
    scope: AttachmentScope = AttachmentScope.TURN


@dataclass(frozen=True, slots=True)
class PersistedFollowUp:
    session: WorkflowSession
    previous_run: Run
    run: Run
    message: Message
    attachments: tuple[MessageAttachment, ...]


class DurableWorkflowService:
    """Durable user-turn operations that must commit before any LLM call starts."""

    def __init__(self, persistence: SQLitePersistence, file_store: LocalFileStore) -> None:
        self.persistence = persistence
        self.file_store = file_store

    def persist_followup(
        self,
        *,
        session_id: str,
        previous_run_id: str,
        content: str,
        uploads: list[PendingAttachment] | tuple[PendingAttachment, ...] = (),
        message_id: str | None = None,
        run_id: str | None = None,
    ) -> PersistedFollowUp:
        session = self.persistence.sessions.get(session_id)
        if session is None:
            raise PersistenceError(f"workflow session not found: {session_id}")
        previous_run = self.persistence.runs.get(previous_run_id)
        if previous_run is None:
            raise PersistenceError(f"previous run not found: {previous_run_id}")
        if previous_run.session_id != session.id:
            raise PersistenceConflictError("previous run belongs to a different workflow session")

        message_id = message_id or str(uuid4())
        run_id = run_id or str(uuid4())
        continuation = new_continuation_run(
            session,
            previous_run,
            trigger_message_id=message_id,
            run_id=run_id,
        )

        if self.persistence.runs.list_active():
            raise PersistenceConflictError("another active run already exists; pause or finish it before follow-up")

        stored_files: list[StoredFile] = []
        attachments: list[MessageAttachment] = []
        try:
            for upload in uploads:
                stored = self.file_store.store_run_file(continuation.id, upload.filename, upload.data)
                stored_files.append(stored)
                attachments.append(
                    MessageAttachment(
                        id=str(uuid4()),
                        message_id=message_id,
                        filename=upload.filename,
                        sha256=stored.sha256,
                        size=stored.size,
                        storage_ref=stored.storage_ref,
                        scope=upload.scope,
                        mime_type=upload.mime_type,
                    )
                )

            message = Message(
                id=message_id,
                session_id=session.id,
                run_id=continuation.id,
                role=MessageRole.USER,
                content=content,
                attachment_ids=[item.id for item in attachments],
            )
            updated_session = replace(session, updated_at=utc_now())

            with self.persistence.db.transaction():
                self.persistence.runs.save(continuation)
                self.persistence.messages.save(message)
                for attachment in attachments:
                    self.persistence.attachments.save(attachment)
                self.persistence.sessions.save(updated_session)
        except Exception:
            for stored in stored_files:
                if stored.created:
                    self.file_store.delete(stored.storage_ref)
            raise

        return PersistedFollowUp(
            session=updated_session,
            previous_run=previous_run,
            run=continuation,
            message=message,
            attachments=tuple(attachments),
        )
