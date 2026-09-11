from __future__ import annotations

from agent_workflow_studio.runtime.server import main


if __name__ == "__main__":
    raise SystemExit(main(["--no-ui", "--host", "127.0.0.1", "--port", "8765"]))
