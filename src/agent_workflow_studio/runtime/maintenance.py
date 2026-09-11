from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path, PurePosixPath
from typing import Iterable

from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence

_BACKUP_FORMAT_VERSION = 1
_BACKUP_DB_NAMES = ("domain.sqlite", "graph.sqlite")


def default_data_dir() -> Path:
    """Return the per-user local data directory without reading or storing secrets."""
    override = os.getenv("AWS2_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return (base / "AgentWorkflowStudio").resolve()
    if sys_platform() == "darwin":
        return (Path.home() / "Library" / "Application Support" / "AgentWorkflowStudio").resolve()
    base = Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return (base / "agent-workflow-studio").resolve()


def sys_platform() -> str:
    import sys

    return sys.platform


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RuntimeLockError(RuntimeError):
    pass


class RuntimeLock:
    """Small single-process lock that tolerates stale files after a hard kill."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / ".runtime.lock"
        self.acquired = False

    @classmethod
    def live_pid(cls, root: str | Path) -> int | None:
        path = Path(root).expanduser().resolve() / ".runtime.lock"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
        except Exception:
            return None
        return pid if _pid_alive(pid) else None

    @classmethod
    def is_locked(cls, root: str | Path) -> bool:
        return cls.live_pid(root) is not None

    def acquire(self) -> "RuntimeLock":
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            live = self.live_pid(self.root)
            if live is not None:
                raise RuntimeLockError(f"Agent Workflow Studio is already running (pid={live})")
            self.path.unlink(missing_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RuntimeLockError("Agent Workflow Studio runtime lock is already held") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self.acquired = True
        return self

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            if int(payload.get("pid", 0)) == os.getpid():
                self.path.unlink(missing_ok=True)
        finally:
            self.acquired = False

    def __enter__(self) -> "RuntimeLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RedactingFormatter(logging.Formatter):
    _PATTERNS = (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
        re.compile(r"\bsecret_[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    )

    def __init__(self, fmt: str, *, secret_values: Iterable[str] = ()) -> None:
        super().__init__(fmt)
        self.secret_values = tuple(sorted({value for value in secret_values if value}, key=len, reverse=True))

    def format(self, record: logging.LogRecord) -> str:
        value = super().format(record)
        for secret in self.secret_values:
            value = value.replace(secret, "[REDACTED]")
        for pattern in self._PATTERNS:
            value = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", value)
        return value


def configure_rotating_logging(
    log_dir: str | Path,
    *,
    secret_values: Iterable[str] = (),
    max_bytes: int = 2 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    directory = Path(log_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("agent_workflow_studio")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, "_aws2_managed", False):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(
        directory / "studio.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler._aws2_managed = True  # type: ignore[attr-defined]
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            secret_values=secret_values,
        )
    )
    logger.addHandler(handler)
    return logger


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(str(source), timeout=5.0)
    destination_connection = sqlite3.connect(str(destination), timeout=5.0)
    try:
        source_connection.backup(destination_connection)
        row = destination_connection.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise RuntimeError(f"SQLite quick_check failed for {source.name}: {row}")
    finally:
        destination_connection.close()
        source_connection.close()


def _safe_archive_name(name: str) -> str:
    if "\\" in name:
        raise ValueError(f"unsafe backup entry: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe backup entry: {name}")
    return path.as_posix()


class BackupManager:
    """Creates verified local snapshots without logs, lock files, or credentials."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.backups_dir = self.root / "backups"

    def create(self) -> dict[str, object]:
        domain = self.root / "domain.sqlite"
        graph = self.root / "graph.sqlite"
        if not domain.exists() or not graph.exists():
            raise FileNotFoundError("domain.sqlite and graph.sqlite must exist before backup")
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        destination = self.backups_dir / f"aws2-backup-{_utc_stamp()}.zip"
        with tempfile.TemporaryDirectory(prefix="aws2-backup-") as temp:
            staging = Path(temp)
            _snapshot_sqlite(domain, staging / "domain.sqlite")
            _snapshot_sqlite(graph, staging / "graph.sqlite")
            files_root = self.root / "files"
            if files_root.exists():
                shutil.copytree(files_root, staging / "files")
            entries: dict[str, dict[str, object]] = {}
            for path in sorted(item for item in staging.rglob("*") if item.is_file()):
                arcname = path.relative_to(staging).as_posix()
                entries[arcname] = {"sha256": sha256_file(path), "size": path.stat().st_size}
            manifest = {
                "format": "agent-workflow-studio-backup",
                "format_version": _BACKUP_FORMAT_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "entries": entries,
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(item for item in staging.rglob("*") if item.is_file()):
                    archive.write(path, path.relative_to(staging).as_posix())
        validation = self.validate(destination)
        if not validation["valid"]:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"new backup failed validation: {validation['errors']}")
        return {
            "name": destination.name,
            "path": str(destination),
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "validation": validation,
        }

    def validate(self, archive_path: str | Path) -> dict[str, object]:
        archive_path = Path(archive_path).expanduser().resolve()
        errors: list[str] = []
        manifest: dict[str, object] = {}
        with tempfile.TemporaryDirectory(prefix="aws2-validate-") as temp:
            target = Path(temp)
            try:
                with zipfile.ZipFile(archive_path, "r") as archive:
                    names = [_safe_archive_name(info.filename) for info in archive.infolist() if not info.is_dir()]
                    if "manifest.json" not in names:
                        raise ValueError("backup manifest.json is missing")
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    if manifest.get("format") != "agent-workflow-studio-backup":
                        raise ValueError("unsupported backup format")
                    if int(manifest.get("format_version", 0)) != _BACKUP_FORMAT_VERSION:
                        raise ValueError("unsupported backup version")
                    entries = manifest.get("entries")
                    if not isinstance(entries, dict):
                        raise ValueError("backup manifest entries are invalid")
                    for required in _BACKUP_DB_NAMES:
                        if required not in entries:
                            raise ValueError(f"backup is missing required entry: {required}")
                    for name, metadata in entries.items():
                        safe_name = _safe_archive_name(str(name))
                        if safe_name not in names:
                            errors.append(f"missing archive entry: {safe_name}")
                            continue
                        data = archive.read(safe_name)
                        expected = metadata if isinstance(metadata, dict) else {}
                        if int(expected.get("size", -1)) != len(data):
                            errors.append(f"size mismatch: {safe_name}")
                        if str(expected.get("sha256", "")) != hashlib.sha256(data).hexdigest():
                            errors.append(f"sha256 mismatch: {safe_name}")
                        output = target / safe_name
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(data)
                for database_name in _BACKUP_DB_NAMES:
                    connection = sqlite3.connect(str(target / database_name), timeout=5.0)
                    try:
                        row = connection.execute("PRAGMA quick_check").fetchone()
                        if not row or str(row[0]).lower() != "ok":
                            errors.append(f"SQLite quick_check failed: {database_name}")
                    finally:
                        connection.close()
            except Exception as exc:
                errors.append(str(exc))
        return {
            "valid": not errors,
            "format_version": manifest.get("format_version"),
            "created_at": manifest.get("created_at"),
            "entry_count": len(manifest.get("entries", {})) if isinstance(manifest.get("entries"), dict) else 0,
            "errors": errors,
        }

    def restore(self, archive_path: str | Path, target_root: str | Path, *, overwrite: bool = False) -> dict[str, object]:
        target_root = Path(target_root).expanduser().resolve()
        if RuntimeLock.is_locked(target_root):
            raise RuntimeLockError("restore is offline-only; stop Agent Workflow Studio before restoring")
        validation = self.validate(archive_path)
        if not validation["valid"]:
            raise ValueError(f"backup validation failed: {validation['errors']}")
        occupied = any((target_root / name).exists() for name in (*_BACKUP_DB_NAMES, "files"))
        if occupied and not overwrite:
            raise FileExistsError("restore target already contains Agent Workflow Studio data")
        target_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="aws2-restore-") as temp:
            staging = Path(temp)
            with zipfile.ZipFile(archive_path, "r") as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                for name in manifest["entries"]:
                    safe_name = _safe_archive_name(name)
                    output = staging / safe_name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(archive.read(safe_name))
            if overwrite:
                for name in _BACKUP_DB_NAMES:
                    (target_root / name).unlink(missing_ok=True)
                shutil.rmtree(target_root / "files", ignore_errors=True)
            for name in _BACKUP_DB_NAMES:
                shutil.copy2(staging / name, target_root / name)
            if (staging / "files").exists():
                shutil.copytree(staging / "files", target_root / "files", dirs_exist_ok=True)
        return {"restored": True, "target": str(target_root), "validation": validation}


@dataclass(frozen=True, slots=True)
class CleanupReport:
    apply: bool
    protected_count: int
    candidate_count: int
    deleted_count: int
    candidates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "apply": self.apply,
            "protected_count": self.protected_count,
            "candidate_count": self.candidate_count,
            "deleted_count": self.deleted_count,
            "candidates": list(self.candidates),
        }


def cleanup_local_files(
    persistence: SQLitePersistence,
    file_store: LocalFileStore,
    *,
    apply: bool = False,
) -> CleanupReport:
    protected = {
        str(item.storage_ref)
        for item in persistence.sources.list()
        if item.storage_ref
    }
    protected.update(str(item.storage_ref) for item in persistence.attachments.list() if item.storage_ref)
    protected.update(str(item.storage_ref) for item in persistence.run_files.list() if item.storage_ref)
    existing = {
        path.relative_to(file_store.root).as_posix()
        for path in file_store.root.rglob("*")
        if path.is_file()
    }
    candidates = tuple(sorted(existing - protected))
    deleted = 0
    if apply:
        for storage_ref in candidates:
            file_store.delete(storage_ref)
            deleted += 1
    return CleanupReport(
        apply=apply,
        protected_count=len(protected),
        candidate_count=len(candidates),
        deleted_count=deleted,
        candidates=candidates,
    )
