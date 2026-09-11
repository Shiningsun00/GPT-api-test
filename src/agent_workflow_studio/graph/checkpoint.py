from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver


class SQLiteGraphCheckpointer:
    """Persistent, strict-serialization LangGraph checkpointer for local-first runs."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
        self.serializer = JsonPlusSerializer(
            pickle_fallback=False,
            allowed_msgpack_modules=None,
        )
        self.saver = SqliteSaver(self.connection, serde=self.serializer)
        self.strict = True
        self._closed = False

    def table_names(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {str(row[0]) for row in rows}

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteGraphCheckpointer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
