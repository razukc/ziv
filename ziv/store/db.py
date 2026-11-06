"""ziv.store.db — the SQLite file, its migrations, transactions and retention."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import repos

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class StoreError(Exception):
    pass


class StoreBusy(StoreError):
    """Another connection holds the write lock past the busy timeout."""


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """How long each table keeps rows, in seconds. Terminal utterances and
    delivered replies go first; events are the operator's view and stay longer."""

    utterances_s: float
    replies_s: float
    events_s: float

    @classmethod
    def from_days(cls, days: float) -> "RetentionPolicy":
        day = 86_400.0
        return cls(utterances_s=days * day, replies_s=days * day, events_s=4 * days * day)


class Store:
    """One connection to one SQLite file (or ``:memory:``). Repositories hang
    off it; ``tx()`` is the one way to write."""

    def __init__(self, path: str | os.PathLike[str], *, busy_timeout_ms: int = 5000) -> None:
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._conn: sqlite3.Connection | None = None
        self.wearers = repos.WearerRepo(self)
        self.devices = repos.DeviceRepo(self)
        self.senders = repos.SenderRepo(self)
        self.outbox = repos.OutboxRepo(self)
        self.schedule = repos.ScheduleRepo(self)
        self.prefs = repos.PrefsRepo(self)
        self.replies = repos.ReplyRepo(self)
        self.events = repos.EventRepo(self)
        self.enroll_codes = repos.EnrollCodeRepo(self)

    # --- connection ---------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self.path,
                timeout=self.busy_timeout_ms / 1000.0,
                isolation_level=None,        # explicit BEGIN/COMMIT in tx()
                check_same_thread=False,     # one loop thread, plus the test runner
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
            self._conn = conn
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def tx(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """One transaction. Nested use joins the outer one. ``immediate`` takes
        the write lock up front (claims and assignments)."""
        conn = self.connect()
        if conn.in_transaction:
            yield conn
            return
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                raise StoreBusy(str(exc)) from exc
            raise
        try:
            yield conn
        except BaseException:
            self._rollback(conn)
            raise
        else:
            try:
                conn.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                self._rollback(conn)
                if "locked" in str(exc) or "busy" in str(exc):
                    raise StoreBusy(str(exc)) from exc
                raise

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass

    # --- migrations ---------------------------------------------------------

    @staticmethod
    def migration_files() -> list[tuple[int, Path]]:
        found: list[tuple[int, Path]] = []
        for p in sorted(MIGRATIONS_DIR.iterdir()):
            m = _MIGRATION_NAME.match(p.name)
            if m:
                found.append((int(m.group(1)), p))
        return found

    def applied_versions(self) -> list[int]:
        conn = self.connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        return [int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]

    def migrate(self, now: float = 0.0) -> list[int]:
        """Apply every numbered migration not yet recorded; idempotent."""
        done = set(self.applied_versions())
        applied: list[int] = []
        conn = self.connect()
        for version, path in self.migration_files():
            if version in done:
                continue
            script = path.read_text(encoding="utf-8")
            conn.executescript(
                "BEGIN;\n" + script + "\n"
                f"INSERT INTO schema_migrations(version, applied_at) VALUES ({version}, {float(now)!r});\n"
                "COMMIT;"
            )
            applied.append(version)
        return applied

    # --- health -------------------------------------------------------------

    def integrity_check(self, now: float) -> bool:
        """``PRAGMA integrity_check`` recorded into events, never raised."""
        try:
            rows = [str(r[0]) for r in self.connect().execute("PRAGMA integrity_check")]
        except sqlite3.DatabaseError as exc:
            rows = [f"error: {type(exc).__name__}"]
        ok = rows == ["ok"]
        self.events.append(now, "integrity_check", counts={"ok": int(ok), "findings": 0 if ok else len(rows)},
                           detail=None if ok else rows[0][:200])
        return ok

    def prune(self, now: float, policy: RetentionPolicy) -> dict[str, int]:
        """Retention, with a counter per table and one event when anything went."""
        with self.tx(immediate=True):
            counts = {
                "utterances": self.outbox.prune(now - policy.utterances_s),
                "replies": self.replies.prune(now - policy.replies_s),
                "events": self.events.prune(now - policy.events_s),
                "enroll_codes": self.enroll_codes.prune(now),
            }
            if any(counts.values()):
                self.events.append(now, "prune", counts=counts)
        return counts

    # --- meta ---------------------------------------------------------------

    def meta_get(self, key: str) -> str | None:
        r = self.connect().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(r[0]) if r else None

    def meta_set(self, key: str, value: str) -> None:
        self.connect().execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))

    def checkpoint(self) -> None:
        self.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")


def dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)
