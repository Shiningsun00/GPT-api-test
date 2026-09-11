from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_component(value: str, fallback: str) -> str:
    value = Path(value or "").name.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value or fallback


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_ref: str
    sha256: str
    size: int
    created: bool


class LocalFileStore:
    """Stores source and run files outside SQLite; DB keeps references and hashes."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def store_source(self, data: bytes) -> StoredFile:
        digest = sha256_bytes(data)
        relative = Path("sources") / digest
        return self._write(relative, data)

    def store_run_file(self, run_id: str, filename: str, data: bytes) -> StoredFile:
        safe_run = _safe_component(run_id, "run")
        safe_name = _safe_component(filename, "file")
        digest = sha256_bytes(data)
        relative = Path("runs") / safe_run / f"{digest}_{safe_name}"
        return self._write(relative, data)

    def _write(self, relative: Path, data: bytes) -> StoredFile:
        destination = (self.root / relative).resolve()
        destination.relative_to(self.root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return StoredFile(relative.as_posix(), sha256_bytes(data), len(data), False)
        handle = tempfile.NamedTemporaryFile(prefix=".upload-", dir=destination.parent, delete=False)
        temp_path = Path(handle.name)
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, destination)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return StoredFile(relative.as_posix(), sha256_bytes(data), len(data), True)

    def resolve(self, storage_ref: str) -> Path:
        path = (self.root / storage_ref).resolve()
        path.relative_to(self.root)
        return path

    def read(self, storage_ref: str) -> bytes:
        return self.resolve(storage_ref).read_bytes()

    def delete(self, storage_ref: str) -> None:
        path = self.resolve(storage_ref)
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
