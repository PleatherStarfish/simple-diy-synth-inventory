from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    """Thin SQLite wrapper with shared connection and transaction helpers."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._transaction_depth = 0

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        cursor = self.conn.execute(sql, params)
        self._commit_if_needed(sql)
        return cursor

    def executemany(self, sql: str, seq_of_params: list[tuple] | list[dict]) -> sqlite3.Cursor:
        cursor = self.conn.executemany(sql, seq_of_params)
        self._commit_if_needed(sql)
        return cursor

    def query_all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()) -> object | None:
        row = self.query_one(sql, params)
        if row is None:
            return None
        return row[0]

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        is_outermost = self._transaction_depth == 0
        self._transaction_depth += 1
        try:
            if is_outermost and self.conn.in_transaction:
                self.conn.commit()
            if is_outermost:
                self.conn.execute("BEGIN")
            yield self.conn
            if is_outermost and self.conn.in_transaction:
                self.conn.commit()
        except Exception:
            if is_outermost and self.conn.in_transaction:
                self.conn.rollback()
            raise
        finally:
            self._transaction_depth = max(0, self._transaction_depth - 1)

    @staticmethod
    def dumps_json(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _commit_if_needed(self, sql: str) -> None:
        if self._transaction_depth > 0 or not self.conn.in_transaction:
            return
        keyword = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if keyword in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"}:
            self.conn.commit()
