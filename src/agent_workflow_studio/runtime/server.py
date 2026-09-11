from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent_workflow_studio.api import BackendContext, create_app as create_api_app

from .maintenance import RuntimeLock, configure_rotating_logging, default_data_dir


def create_product_app(context: BackendContext, *, ui_dist: str | Path | None = None) -> FastAPI:
    product = FastAPI(title="Agent Workflow Studio", version="2.0.0")
    product.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    product.mount("/api", create_api_app(context))

    @product.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "agent-workflow-studio", "version": "2.0.0"}

    if ui_dist is not None:
        static_root = Path(ui_dist).expanduser().resolve()
        if static_root.exists() and (static_root / "index.html").exists():
            product.mount("/", StaticFiles(directory=static_root, html=True), name="studio-ui")
    return product


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Agent Workflow Studio 2.0 local backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--ui-dist", default=None)
    parser.add_argument("--no-ui", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.data_dir).expanduser().resolve() if args.data_dir else default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    secrets = [
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("NOTION_API_TOKEN", ""),
        os.getenv("NOTION_TOKEN", ""),
        os.getenv("DISCORD_BOT_TOKEN", ""),
    ]
    logger = configure_rotating_logging(root / "logs", secret_values=secrets)
    lock = RuntimeLock(root)
    context: BackendContext | None = None
    try:
        lock.acquire()
        context = BackendContext.local(root)
        ui_dist = None if args.no_ui else (args.ui_dist or str(Path.cwd() / "ui" / "dist"))
        application = create_product_app(context, ui_dist=ui_dist)
        logger.info("Local Studio starting host=%s port=%s data_dir=%s", args.host, args.port, root)
        uvicorn.run(application, host=args.host, port=args.port, log_level="info")
        return 0
    finally:
        if context is not None:
            context.close()
        lock.release()
        logger.info("Local Studio stopped")


if __name__ == "__main__":
    raise SystemExit(main())
