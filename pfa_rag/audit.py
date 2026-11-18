"""Store retrieval, generation, and source access events locally."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .auth import Principal


class AuditUnavailable(RuntimeError):
    pass


class AccessJournal:
    def __init__(self, database: Path):
        self.database = database

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._write("""
            CREATE TABLE IF NOT EXISTS access_events (
                request_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                operation TEXT NOT NULL,
                subject TEXT NOT NULL,
                roles TEXT NOT NULL,
                question TEXT,
                strategy TEXT,
                context_ids TEXT NOT NULL,
                citation_ids TEXT NOT NULL DEFAULT '[]',
                result TEXT NOT NULL DEFAULT 'processing',
                total_ms REAL,
                model_ms REAL
            )
        """)

    def start(
        self, operation: str, principal: Principal, context_ids: list[str],
        *, question: str | None = None, strategy: str | None = None,
    ) -> str:
        request_id = uuid4().hex
        self._write("""
            INSERT INTO access_events
                (request_id, created_at, operation, subject, roles, question, strategy, context_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (request_id, datetime.now(UTC).isoformat(), operation, principal.subject,
              json.dumps(sorted(principal.roles)), question, strategy, json.dumps(context_ids)))
        return request_id

    def finish(
        self, request_id: str, result: str, citation_ids: list[str],
        total_ms: float, model_ms: float = 0,
    ) -> None:
        self._write("""
            UPDATE access_events SET result=?, citation_ids=?, total_ms=?, model_ms=? WHERE request_id=?
        """, (result, json.dumps(citation_ids), round(total_ms, 3), round(model_ms, 3), request_id))

    def _write(self, query: str, values: tuple = ()) -> None:
        try:
            with closing(sqlite3.connect(self.database, timeout=5)) as connection, connection:
                connection.execute(query, values)
        except (OSError, sqlite3.Error) as error:
            raise AuditUnavailable("The access journal is unavailable") from error
