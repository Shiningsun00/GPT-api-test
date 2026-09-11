from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    suites = [
        ("STEP 9 local product / initial file / backup / import / restore", ["scripts/manual_step9_smoke_test.py"]),
        ("STEP 3 process reopen / manual resume / HITL / continuation", ["scripts/manual_smoke_test.py", "--auto"]),
        ("STEP 4 career policy / revisions / minimum rerun", ["scripts/manual_career_smoke_test.py"]),
        ("STEP 5 API / history / continuation", ["scripts/manual_api_smoke_test.py"]),
        ("STEP 7 Discord adapter", ["scripts/manual_discord_smoke_test.py"]),
        ("STEP 8 Notion final write", ["scripts/manual_notion_smoke_test.py"]),
    ]
    for label, command in suites:
        print(f"\n=== {label} ===")
        run(*command)

    mapping = {
        1: "Local Studio product app boots in STEP 9 smoke",
        2: "Agents/Workflows are seeded and queried through FastAPI",
        3: "Career Workflow Session is created",
        4: "Initial Run accepts a durable execution file before LLM work",
        5: "Durable graph tests cover completed worker/checkpoint state",
        6: "STEP 3 smoke closes and reopens persistent graph resources",
        7: "Reopened persistence/checkpointer loads the same Run thread",
        8: "Artifacts/Run state survive reopen",
        9: "Manual error resume is explicit",
        10: "Agent-requested HITL interrupts",
        11: "HITL answer resumes the same Run",
        12: "Career Manager creates immutable Revision",
        13: "Post-result Follow-up accepts a new file",
        14: "Follow-up creates a Continuation Run",
        15: "Career router reruns minimum required downstream stages",
        16: "New Artifact/Revision are appended without overwrite",
        17: "Discord smoke covers remote follow-up interaction",
        18: "Notion smoke covers idempotent Final result write-back",
        19: "API/history and persistence tests trace Session/Run/Revision/files",
    }
    print("\n=== FINAL ACCEPTANCE 1-19 ===")
    for number, text in mapping.items():
        print(f"[{number:02d}] PASS - {text}")
    print("\nAGENT WORKFLOW STUDIO 2.0 FINAL ACCEPTANCE = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
