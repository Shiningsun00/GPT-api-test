from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import SchemaVersionError
from .schema import CURRENT_SCHEMA_VERSION, MIGRATIONS


class SQLiteDatabase:
    """Single-user SQLite connection with explicit nested transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
        self._transaction_depth = 0
        self._closed = False
        self.initialize()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self._closed:
            raise RuntimeError("database is closed")
        depth = self._transaction_depth
        savepoint = f"aws_sp_{depth}"
        if depth == 0:
            self.connection.execute("BEGIN IMMEDIATE")
        else:
            self.connection.execute(f"SAVEPOINT {savepoint}")
        self._transaction_depth += 1
        try:
            yield self.connection
        except Exception:
            self._transaction_depth -= 1
            if depth == 0:
                self.connection.execute("ROLLBACK")
            else:
                self.connection.execute(f"ROLLBACK TO {savepoint}")
                self.connection.execute(f"RELEASE {savepoint}")
            raise
        else:
            self._transaction_depth -= 1
            if depth == 0:
                self.connection.execute("COMMIT")
            else:
                self.connection.execute(f"RELEASE {savepoint}")

    def initialize(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        row = self.connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        current = int(row["version"] or 0)
        if current > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"database schema version {current} is newer than supported {CURRENT_SCHEMA_VERSION}"
            )
        for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(version)
            if not statements:
                raise SchemaVersionError(f"missing migration for schema version {version}")
            with self.transaction() as conn:
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                    (version,),
                )
                conn.execute(f"PRAGMA user_version = {version}")

    @property
    def schema_version(self) -> int:
        row = self.connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        return int(row["version"] or 0)

    def table_names(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {str(row["name"]) for row in rows}

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
