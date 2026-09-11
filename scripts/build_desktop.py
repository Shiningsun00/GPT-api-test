from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
TAURI = UI / "src-tauri"
BUILD = ROOT / ".desktop-build"


def command_output(command: list[str]) -> str:
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def rust_target() -> str:
    try:
        value = command_output(["rustc", "--print", "host-tuple"])
        if value:
            return value
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    try:
        verbose = command_output(["rustc", "-vV"])
    except FileNotFoundError as exc:
        raise RuntimeError("Rust is required for desktop packaging. Install a current Rust toolchain first.") from exc
    for line in verbose.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine the Rust host target triple")


def build_sidecar() -> Path:
    target = rust_target()
    executable_suffix = ".exe" if os.name == "nt" else ""
    dist = BUILD / "dist"
    work = BUILD / "work"
    spec = BUILD / "spec"
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "aws2-backend",
            "--paths",
            str(ROOT / "src"),
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(spec),
            str(ROOT / "scripts" / "aws2_sidecar_entry.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    built = dist / f"aws2-backend{executable_suffix}"
    if not built.exists():
        raise RuntimeError(f"PyInstaller sidecar not found: {built}")
    binaries = TAURI / "binaries"
    binaries.mkdir(parents=True, exist_ok=True)
    destination = binaries / f"aws2-backend-{target}{executable_suffix}"
    shutil.copy2(built, destination)
    print(f"Sidecar: {destination}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Agent Workflow Studio Tauri desktop package")
    parser.add_argument("--sidecar-only", action="store_true")
    args = parser.parse_args()
    build_sidecar()
    if args.sidecar_only:
        return 0
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "install"], cwd=UI, check=True)
    subprocess.run([npm, "run", "desktop:build"], cwd=UI, check=True)
    print("Desktop bundle build: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
