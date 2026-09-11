from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agent_workflow_studio"
sys.path.insert(0, str(ROOT / "src"))


class StaticBoundaryTests(unittest.TestCase):
    def test_no_streamlit_imports_in_new_package(self) -> None:
        offenders = []
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(alias.name == "streamlit" or alias.name.startswith("streamlit.") for alias in node.names):
                    offenders.append(str(path))
                if isinstance(node, ast.ImportFrom) and node.module and (node.module == "streamlit" or node.module.startswith("streamlit.")):
                    offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_core_does_not_import_policy_module(self) -> None:
        offenders = []
        for path in (SRC / "core").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "career_cover_letter" in text or "policies." in text:
                offenders.append(str(path))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
