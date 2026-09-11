from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSISTENCE = ROOT / "src" / "agent_workflow_studio" / "persistence"
sys.path.insert(0, str(ROOT / "src"))


class Step2BoundaryTests(unittest.TestCase):
    def test_persistence_does_not_import_future_frameworks(self) -> None:
        forbidden = {"streamlit", "langgraph", "fastapi"}
        offenders = []
        for path in PERSISTENCE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".", 1)[0] in forbidden:
                            offenders.append(f"{path}:{alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".", 1)[0] in forbidden:
                        offenders.append(f"{path}:{node.module}")
        self.assertEqual(offenders, [])

    def test_step2_schema_does_not_define_graph_checkpoint_table(self) -> None:
        from agent_workflow_studio.persistence.schema import REQUIRED_TABLES

        self.assertNotIn("checkpoints", REQUIRED_TABLES)
        self.assertNotIn("graph_checkpoints", REQUIRED_TABLES)


if __name__ == "__main__":
    unittest.main()
