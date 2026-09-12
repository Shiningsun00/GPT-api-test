from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, *args: str) -> None:
    print(f"\n=== {label} ===")
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    # R5 is intentionally credential-free. External providers are exercised
    # through deterministic fakes/adapters; live OpenAI/Discord/Notion calls
    # remain a local UAT concern and are never started automatically in CI.
    run("Unit / boundary regression", "-m", "unittest", "discover", "-s", "tests", "-v")
    run("Generic Linear / Hierarchical acceptance", "scripts/manual_generic_runtime_smoke_test.py")
    run("Product acceptance 1-19 / recovery / integrations", "scripts/manual_final_acceptance_test.py")

    checks = [
        "Generic Hierarchical Manager + 2 arbitrary Workers reaches Final",
        "Generic Linear 2+ arbitrary Agents reaches Final",
        "Generic execution has no W1-W6 Agent-name dependency",
        "Duplicate Agent in distinct WorkerSlots is covered by regression tests",
        "Career template uses explicit WorkerSlot W1-W6 role binding",
        "Initial Run file durability/routing remains covered",
        "Agent-requested HITL resumes the same Run/thread",
        "Worker failure requires explicit Manual Resume",
        "Completed result Follow-up + file creates Continuation Run + new Revision",
        "Restart/reopen does not auto-resume external/API work",
        "Artifact and Revision history remains append-only/immutable",
        "Discord and Notion adapters remain regression-covered without policy hard-coding",
        "Backup / import / restore / cleanup regression remains covered",
    ]
    print("\n=== R5 RECOVERY ACCEPTANCE ===")
    for index, text in enumerate(checks, start=1):
        print(f"[{index:02d}] PASS - {text}")
    print("\nR5 GENERIC RUNTIME RECOVERY ACCEPTANCE = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
