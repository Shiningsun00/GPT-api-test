from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.models import Agent, Artifact, AttachmentScope, HierarchyConfig, Message, MessageAttachment, MessageRole, ReferenceSource, ReferenceSourceKind, Revision, RunStatus, WorkerSlot, Workflow, WorkflowMode
from agent_workflow_studio.core.workflow import new_continuation_run, new_initial_run, new_session, set_run_status


class ModelTests(unittest.TestCase):
    def test_agent_round_trip(self) -> None:
        agent = Agent(id="a1", name="Writer", model="gpt-5.6-luna", system_prompt="Write carefully", rag_enabled=True, source_ids=["file:abc"], notion_enabled=True, notion_sources=["https://notion.so/0123456789abcdef0123456789abcdef"])
        restored = Agent.from_dict(agent.to_dict())
        self.assertEqual(restored.id, agent.id)
        self.assertEqual(restored.source_ids, ["file:abc"])
        self.assertTrue(restored.notion_enabled)

    def test_worker_slot_identity_is_distinct_from_agent_identity(self) -> None:
        hierarchy = HierarchyConfig(manager_agent_id="manager", workers=[WorkerSlot(worker_id="slot-1", agent_id="agent-1"), WorkerSlot(worker_id="slot-2", agent_id="agent-1")])
        workflow = Workflow(id="w1", name="H", mode=WorkflowMode.HIERARCHICAL, hierarchy=hierarchy)
        restored = Workflow.from_dict(workflow.to_dict())
        self.assertEqual(restored.hierarchy.workers[0].agent_id, restored.hierarchy.workers[1].agent_id)
        self.assertNotEqual(restored.hierarchy.workers[0].worker_id, restored.hierarchy.workers[1].worker_id)

    def test_session_initial_and_continuation_runs(self) -> None:
        workflow = Workflow(id="w1", name="Linear")
        session = new_session(workflow, session_id="s1")
        initial = set_run_status(new_initial_run(session, run_id="r1"), RunStatus.COMPLETED)
        continuation = new_continuation_run(session, initial, trigger_message_id="m2", run_id="r2")
        self.assertEqual(continuation.session_id, initial.session_id)
        self.assertEqual(continuation.parent_run_id, "r1")
        self.assertEqual(continuation.trigger_message_id, "m2")

    def test_attachment_is_separate_from_permanent_reference_source(self) -> None:
        source = ReferenceSource(id="src1", kind=ReferenceSourceKind.FILE, label="permanent.pdf", storage_ref="data/sources/hash")
        attachment = MessageAttachment(id="att1", message_id="m1", filename="followup.xlsx", sha256="a" * 64, size=10, storage_ref="data/runs/r1/followup.xlsx", scope=AttachmentScope.TURN)
        self.assertEqual(attachment.scope, AttachmentScope.TURN)
        self.assertNotIn("message_id", source.to_dict())

    def test_message_artifact_revision_are_serializable(self) -> None:
        message = Message(id="m1", session_id="s1", run_id="r1", role=MessageRole.USER, content="revise")
        artifact = Artifact(id="a1", session_id="s1", run_id="r1", kind="draft", producer="worker-4", body="draft body", dependencies=("strategy-1",), sequence=2)
        revision = Revision(id="rev2", session_id="s1", run_id="r1", version=2, final_output="final", artifact_ids=("a1",), attachment_ids=("att1",))
        self.assertEqual(Message.from_dict(message.to_dict()).content, "revise")
        self.assertEqual(Artifact.from_dict(artifact.to_dict()).dependencies, ("strategy-1",))
        self.assertEqual(Revision.from_dict(revision.to_dict()).version, 2)


if __name__ == "__main__":
    unittest.main()
