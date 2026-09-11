from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agent_workflow_studio"
sys.path.insert(0, str(ROOT / "src"))


class Step3BoundaryTests(unittest.TestCase):
    def test_graph_package_does_not_import_future_ui_or_api_frameworks(self) -> None:
        graph_root = SRC / "graph"
        banned = {"streamlit", "fastapi", "flask", "django"}
        offenders = []
        for path in graph_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if any(name == item or name.startswith(item + ".") for item in banned):
                        offenders.append(f"{path}:{name}")
        self.assertEqual(offenders, [])

    def test_generic_graph_does_not_import_career_policy(self) -> None:
        offenders = []
        for path in (SRC / "graph").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if name == "agent_workflow_studio.policies" or name.startswith("agent_workflow_studio.policies."):
                        offenders.append(f"{path}:{name}")
        self.assertEqual(offenders, [])

    def test_checkpoint_uses_strict_non_pickle_serializer(self) -> None:
        text = (SRC / "graph" / "checkpoint.py").read_text(encoding="utf-8")
        self.assertIn("pickle_fallback=False", text)
        self.assertIn("allowed_msgpack_modules=None", text)

    def test_step3_uses_langgraph_not_custom_checkpoint_schema(self) -> None:
        checkpoint_text = (SRC / "graph" / "checkpoint.py").read_text(encoding="utf-8")
        self.assertIn("SqliteSaver", checkpoint_text)
        domain_schema = (SRC / "persistence" / "schema.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("create table checkpoints", domain_schema)
        self.assertNotIn("create table checkpoint_writes", domain_schema)


if __name__ == "__main__":
    unittest.main()
