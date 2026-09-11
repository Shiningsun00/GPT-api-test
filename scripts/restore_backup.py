from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.runtime import BackupManager, default_data_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline restore for Agent Workflow Studio 2.0")
    parser.add_argument("backup", help="Path to an aws2-backup-*.zip file")
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manager = BackupManager(Path(args.data_dir))
    result = manager.restore(args.backup, args.data_dir, overwrite=args.overwrite)
    print(f"Restore PASS: {result['target']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
