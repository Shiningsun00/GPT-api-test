from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Step9DesktopScaffoldTests(unittest.TestCase):
    def test_tauri_config_declares_backend_sidecar_and_local_frontend(self) -> None:
        config = json.loads((ROOT / "ui" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(config["productName"], "Agent Workflow Studio")
        self.assertEqual(config["version"], "2.0.0")
        self.assertIn("binaries/aws2-backend", config["bundle"]["externalBin"])
        self.assertEqual(config["build"]["frontendDist"], "../dist")

    def test_desktop_shell_spawns_and_kills_backend_sidecar(self) -> None:
        source = (ROOT / "ui" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('sidecar("aws2-backend")', source)
        self.assertIn("--no-ui", source)
        self.assertIn("child.kill()", source)

    def test_packaging_script_uses_target_triple_suffix(self) -> None:
        source = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")
        self.assertIn("host-tuple", source)
        self.assertIn("aws2-backend-{target}", source)
        self.assertIn("PyInstaller", source)


if __name__ == "__main__":
    unittest.main()
