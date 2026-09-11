from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_workflow_studio.core.dependency import stabilize_plan_dependencies, validate_plan
from agent_workflow_studio.core.errors import WorkflowValidationError
from agent_workflow_studio.core.models import Artifact
from agent_workflow_studio.policies.career_cover_letter import build_career_plan_policy


def artifact(artifact_id: str, kind: str, sequence: int) -> Artifact:
    return Artifact(id=artifact_id, session_id="s1", run_id="r1", kind=kind, producer="worker", body=kind, sequence=sequence)


class DependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = [{"worker_key": "worker_1", "name": "W1 Evidence"}, {"worker_key": "worker_2", "name": "W2 Analysis"}, {"worker_key": "worker_3", "name": "W3 Strategy"}, {"worker_key": "worker_4", "name": "W4 Writer"}, {"worker_key": "worker_5", "name": "W5 Fact Review"}, {"worker_key": "worker_6", "name": "W6 Reader Review"}]
        self.policy = build_career_plan_policy(self.registry)
        self.artifacts = {"intake-1": artifact("intake-1", "intake", 1), "analysis-1": artifact("analysis-1", "analysis", 1), "candidates-1": artifact("candidates-1", "candidates", 1), "candidates-2": artifact("candidates-2", "candidates", 2), "draft-1": artifact("draft-1", "draft", 1), "draft-2": artifact("draft-2", "draft", 2)}

    def test_stabilizes_candidates_dependencies(self) -> None:
        plan = {"action": "delegate", "assignments": [{"worker_key": "worker_3", "kind": "candidates", "task": "normalize", "depends_on": []}]}
        repaired, notes = stabilize_plan_dependencies(plan, self.artifacts, self.policy)
        deps = repaired["assignments"][0]["depends_on"]
        self.assertIn("intake-1", deps)
        self.assertIn("analysis-1", deps)
        self.assertTrue(notes)
        validate_plan(repaired, self.registry, self.artifacts, self.policy)

    def test_selection_review_uses_only_newest_candidates(self) -> None:
        plan = {"action": "delegate", "assignments": [{"worker_key": "worker_6", "kind": "selection_review", "task": "review candidates", "depends_on": ["intake-1", "candidates-1"]}]}
        repaired, _ = stabilize_plan_dependencies(plan, self.artifacts, self.policy)
        self.assertEqual(repaired["assignments"][0]["depends_on"], ["candidates-2"])
        validate_plan(repaired, self.registry, self.artifacts, self.policy)

    def test_review_uses_only_newest_draft(self) -> None:
        plan = {"action": "delegate", "assignments": [{"worker_key": "worker_5", "kind": "review", "task": "review draft", "depends_on": ["draft-1"]}]}
        repaired, _ = stabilize_plan_dependencies(plan, self.artifacts, self.policy)
        self.assertEqual(repaired["assignments"][0]["depends_on"], ["draft-2"])
        validate_plan(repaired, self.registry, self.artifacts, self.policy)

    def test_worker_role_violation_fails(self) -> None:
        plan = {"action": "delegate", "assignments": [{"worker_key": "worker_4", "kind": "intake", "task": "wrong", "depends_on": []}]}
        with self.assertRaises(WorkflowValidationError):
            validate_plan(plan, self.registry, self.artifacts, self.policy)


if __name__ == "__main__":
    unittest.main()
