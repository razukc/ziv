"""ziv.store.repos — one repository per aggregate.

A repository loads a slice for the core, and writes what the core returns.
It never decides anything. All methods run on the store's connection inside
whatever transaction the caller opened (``Store.tx``); the few that need their
own lock say so.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from ziv.core.credentials import secret_matches
from ziv.core.model import (
    SCOPES,
    TERMINAL_STATES,
    Device,
    OutboxEntry,
    ScheduleEntry,
    Sender,
    Wearer,
    WearerPrefs,
)
from ziv.wire import Advance, Kind, Late, Profile, Reason, State, Utterance

if TYPE_CHECKING:
    from .db import Store


def _dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


class _Repo:
    def __init__(self, store: "Store") -> None:
        self._store = store

    @property
    def conn(self):
        return self._store.connect()


# --- wearers ----------------------------------------------------------------


class WearerRepo(_Repo):
    def ensure(self, id: str, name: str, now: float) -> Wearer:
        self.conn.execute("INSERT OR IGNORE INTO wearers(id, name, created) VALUES (?, ?, ?)", (id, name, now))
        return self.get(id)  # type: ignore[return-value]

    def get(self, id: str) -> Wearer | None:
        r = self.conn.execute("SELECT id, name, created FROM wearers WHERE id = ?", (id,)).fetchone()
        return Wearer(r["id"], r["name"], r["created"]) if r else None

    def list(self) -> list[Wearer]:
        return [Wearer(r["id"], r["name"], r["created"])
                for r in self.conn.execute("SELECT id, name, created FROM wearers ORDER BY created")]


# --- devices ----------------------------------------------------------------


def _device(r) -> Device:
    return Device(id=r["id"], wearer=r["wearer"], name=r["name"], profile=Profile(r["profile"]),
                  primary=bool(r["is_primary"]), order=int(r["ord"]), key_hash=r["key_hash"],
                  created=r["created"], last_seen=r["last_seen"])


class DeviceRepo(_Repo):
    _COLS = "id, wearer, name, profile, key_hash, is_primary, ord, created, last_seen"

    def insert(self, d: Device) -> None:
        self.conn.execute(
            f"INSERT INTO devices({self._COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (d.id, d.wearer, d.name, str(d.profile), d.key_hash, int(d.primary), d.order, d.created, d.last_seen),
        )

    def get(self, id: str) -> Device | None:
        r = self.conn.execute(f"SELECT {self._COLS} FROM devices WHERE id = ?", (id,)).fetchone()
        return _device(r) if r else None

    def list(self, wearer: str) -> list[Device]:
        return [_device(r) for r in self.conn.execute(
            f"SELECT {self._COLS} FROM devices WHERE wearer = ? ORDER BY is_primary DESC, ord, id", (wearer,))]

    def all(self) -> list[Device]:
        return [_device(r) for r in self.conn.execute(f"SELECT {self._COLS} FROM devices ORDER BY wearer, ord")]

    def count(self, wearer: str) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM devices WHERE wearer = ?", (wearer,)).fetchone()[0])

    def touch(self, id: str, now: float) -> None:
        self.conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now, id))

    def set_primary(self, wearer: str, id: str) -> None:
        self.conn.execute("UPDATE devices SET is_primary = 0 WHERE wearer = ?", (wearer,))
        self.conn.execute("UPDATE devices SET is_primary = 1 WHERE id = ? AND wearer = ?", (id, wearer))

    def find_by_key(self, key: str) -> Device | None:
        """Constant-time comparison against every stored hash; the table is small."""
        found: Device | None = None
        for d in self.all():
            if secret_matches(key, d.key_hash):
                found = d
        return found


# --- senders ----------------------------------------------------------------


def _sender(r) -> Sender:
    scopes = frozenset(s for s in r["scopes"].split(",") if s in SCOPES)
    return Sender(id=r["id"], wearer=r["wearer"], label=r["label"], token_hash=r["token_hash"],
                  scopes=scopes, rate_per_min=int(r["rate_per_min"]), created=r["created"])


class SenderRepo(_Repo):
    _COLS = "id, wearer, label, token_hash, scopes, rate_per_min, created"

    def insert(self, s: Sender) -> None:
        self.conn.execute(
            f"INSERT INTO senders({self._COLS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (s.id, s.wearer, s.label, s.token_hash, ",".join(sorted(s.scopes)), s.rate_per_min, s.created),
        )

    def get(self, id: str) -> Sender | None:
        r = self.conn.execute(f"SELECT {self._COLS} FROM senders WHERE id = ?", (id,)).fetchone()
        return _sender(r) if r else None

    def list(self, wearer: str) -> list[Sender]:
        return [_sender(r) for r in self.conn.execute(
            f"SELECT {self._COLS} FROM senders WHERE wearer = ? ORDER BY created", (wearer,))]

    def all(self) -> list[Sender]:
        return [_sender(r) for r in self.conn.execute(f"SELECT {self._COLS} FROM senders ORDER BY created")]

    def delete(self, id: str) -> bool:
        return self.conn.execute("DELETE FROM senders WHERE id = ?", (id,)).rowcount > 0

    def find_by_token(self, token: str) -> Sender | None:
        found: Sender | None = None
        for s in self.all():
            if secret_matches(token, s.token_hash):
                found = s
        return found


# --- the outbox -------------------------------------------------------------


def encode_entry(e: OutboxEntry) -> str:
    return _dumps({
        "utterance": e.utterance.model_dump(mode="json", by_alias=True),
        "state": str(e.state),
        "device": e.device,
        "reason": str(e.reason) if e.reason else None,
        "created": e.created,
        "updated": e.updated,
        "sent_at": e.sent_at,
        "played_at": e.played_at,
        "played_ms": e.played_ms,
        "duration_ms": e.duration_ms,
        "budget_ms": e.budget_ms,
        "tried": sorted(e.tried),
        "late": e.late,
        "lossy": e.lossy,
    })


def decode_entry(body: str) -> OutboxEntry:
    d = json.loads(body)
    return OutboxEntry(
        utterance=Utterance.model_validate(d["utterance"]),
        state=State(d["state"]),
        created=float(d["created"]),
        updated=float(d["updated"]),
        duration_ms=int(d["duration_ms"]),
        budget_ms=int(d["budget_ms"]),
        device=d.get("device"),
        reason=Reason(d["reason"]) if d.get("reason") else None,
        sent_at=d.get("sent_at"),
        played_at=d.get("played_at"),
        played_ms=d.get("played_ms"),
        tried=frozenset(d.get("tried", ())),
        late=bool(d.get("late", False)),
        lossy=bool(d.get("lossy", False)),
    )


class OutboxRepo(_Repo):
    def insert(self, e: OutboxEntry) -> None:
        self.conn.execute(
            "INSERT INTO utterances(id, wearer, state, device, created, updated, expires, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (e.id, e.wearer, str(e.state), e.device, e.created, e.updated, e.expires_at(), encode_entry(e)),
        )

    def save(self, e: OutboxEntry) -> None:
        self.conn.execute(
            "UPDATE utterances SET state = ?, device = ?, updated = ?, expires = ?, body = ? WHERE id = ?",
            (str(e.state), e.device, e.updated, e.expires_at(), encode_entry(e), e.id),
        )

    def save_changed(self, before: Sequence[OutboxEntry], after: Sequence[OutboxEntry]) -> int:
        """Write only the entries the core changed."""
        old = {e.id: e for e in before}
        n = 0
        for e in after:
            if old.get(e.id) is not e and old.get(e.id) != e:
                self.save(e)
                n += 1
        return n

    def get(self, id: str) -> OutboxEntry | None:
        r = self.conn.execute("SELECT body FROM utterances WHERE id = ?", (id,)).fetchone()
        return decode_entry(r["body"]) if r else None

    def _rows(self, sql: str, params: tuple = ()) -> list[OutboxEntry]:
        return [decode_entry(r["body"]) for r in self.conn.execute(sql, params)]

    def active(self, wearer: str) -> list[OutboxEntry]:
        return self._rows(
            "SELECT body FROM utterances WHERE wearer = ? AND state IN ('pending','sent','playing') "
            "ORDER BY created, rowid", (wearer,))

    def active_all(self) -> list[OutboxEntry]:
        return self._rows(
            "SELECT body FROM utterances WHERE state IN ('pending','sent','playing') ORDER BY wearer, created, rowid")

    def by_device(self, device: str) -> list[OutboxEntry]:
        return self._rows(
            "SELECT body FROM utterances WHERE device = ? AND state IN ('sent','playing') ORDER BY created, rowid",
            (device,))

    def list(self, wearer: str, state: State | None = None, limit: int = 200) -> list[OutboxEntry]:
        if state is None:
            return self._rows(
                "SELECT body FROM utterances WHERE wearer = ? ORDER BY created DESC, rowid DESC LIMIT ?",
                (wearer, limit))
        return self._rows(
            "SELECT body FROM utterances WHERE wearer = ? AND state = ? ORDER BY created DESC, rowid DESC LIMIT ?",
            (wearer, str(state), limit))

    def wearers_with_active(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT wearer FROM utterances WHERE state IN ('pending','sent','playing')")]

    def counts(self, wearer: str | None = None) -> dict[str, int]:
        out = {str(s): 0 for s in State}
        if wearer is None:
            rows = self.conn.execute("SELECT state, COUNT(*) FROM utterances GROUP BY state")
        else:
            rows = self.conn.execute("SELECT state, COUNT(*) FROM utterances WHERE wearer = ? GROUP BY state", (wearer,))
        for state, n in rows:
            out[state] = int(n)
        return out

    def prune(self, cutoff: float) -> int:
        states = tuple(str(s) for s in TERMINAL_STATES)
        marks = ",".join("?" * len(states))
        return self.conn.execute(
            f"DELETE FROM utterances WHERE state IN ({marks}) AND updated < ?", (*states, cutoff)).rowcount


# --- schedule ---------------------------------------------------------------


def _schedule(r) -> ScheduleEntry:
    return ScheduleEntry(id=int(r["id"]), wearer=r["wearer"], fire_at=r["fire_at"], kind=Kind(r["kind"]),
                         text=r["text"], intent=r["intent"], expires_after_s=int(r["expires_after_s"]),
                         created=r["created"], label=r["label"], lease_until=r["lease_until"])


class ScheduleRepo(_Repo):
    _COLS = "id, wearer, fire_at, kind, text, intent, expires_after_s, label, created, lease_until"

    def insert(self, e: ScheduleEntry) -> ScheduleEntry:
        cur = self.conn.execute(
            "INSERT INTO schedule(wearer, fire_at, kind, text, intent, expires_after_s, label, created, lease_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.wearer, e.fire_at, str(e.kind), e.text, e.intent, e.expires_after_s, e.label, e.created, e.lease_until),
        )
        return e.with_(id=int(cur.lastrowid))

    def get(self, id: int) -> ScheduleEntry | None:
        r = self.conn.execute(f"SELECT {self._COLS} FROM schedule WHERE id = ?", (id,)).fetchone()
        return _schedule(r) if r else None

    def list(self, wearer: str) -> list[ScheduleEntry]:
        return [_schedule(r) for r in self.conn.execute(
            f"SELECT {self._COLS} FROM schedule WHERE wearer = ? ORDER BY fire_at, id", (wearer,))]

    def count(self, wearer: str | None = None) -> int:
        if wearer is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM schedule WHERE wearer = ?", (wearer,)).fetchone()[0])

    def delete(self, id: int, wearer: str | None = None) -> bool:
        if wearer is None:
            cur = self.conn.execute("DELETE FROM schedule WHERE id = ?", (id,))
        else:
            cur = self.conn.execute("DELETE FROM schedule WHERE id = ? AND wearer = ?", (id, wearer))
        return cur.rowcount > 0

    def claim_due(self, now: float, window_s: float, limit: int = 32) -> list[ScheduleEntry]:
        """Lease every due, unleased row in one ``BEGIN IMMEDIATE`` transaction.
        Two connections cannot both claim a row: the second waits for the lock
        and then sees the lease."""
        with self._store.tx(immediate=True) as conn:
            rows = conn.execute(
                f"SELECT {self._COLS} FROM schedule WHERE fire_at <= ? AND (lease_until IS NULL OR lease_until <= ?) "
                "ORDER BY fire_at, id LIMIT ?", (now, now, limit)).fetchall()
            claimed: list[ScheduleEntry] = []
            for r in rows:
                conn.execute("UPDATE schedule SET lease_until = ? WHERE id = ?", (now + window_s, r["id"]))
                claimed.append(_schedule(r).with_(lease_until=now + window_s))
            return claimed

    def release(self, id: int, lease_until: float | None = None) -> None:
        self.conn.execute("UPDATE schedule SET lease_until = ? WHERE id = ?", (lease_until, id))

    def fire(self, id: int, entry: OutboxEntry) -> bool:
        """Delete the schedule row and insert the outbox row in one transaction.
        Returns False when the row was already gone (fired by someone else)."""
        with self._store.tx(immediate=True) as conn:
            if conn.execute("DELETE FROM schedule WHERE id = ?", (id,)).rowcount != 1:
                return False
            self._store.outbox.insert(entry)
            return True


# --- prefs ------------------------------------------------------------------


class PrefsRepo(_Repo):
    def get(self, wearer: str) -> WearerPrefs:
        r = self.conn.execute("SELECT pace_ms, advance, late, history FROM prefs WHERE wearer = ?", (wearer,)).fetchone()
        if not r:
            return WearerPrefs.defaults()
        return WearerPrefs(pace_ms=int(r["pace_ms"]), advance=Advance(r["advance"]), late=Late(r["late"]),
                           history=bool(r["history"]))

    def set(self, wearer: str, p: WearerPrefs, now: float) -> None:
        self.conn.execute(
            "INSERT INTO prefs(wearer, pace_ms, advance, late, history, updated) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(wearer) DO UPDATE SET pace_ms = excluded.pace_ms, advance = excluded.advance, "
            "late = excluded.late, history = excluded.history, updated = excluded.updated",
            (wearer, p.pace_ms, str(p.advance), str(p.late), int(p.history), now),
        )


# --- replies ----------------------------------------------------------------


class ReplyRepo(_Repo):
    def insert(self, wearer: str, device: str | None, in_reply_to: str | None, words: Sequence[str], now: float) -> int:
        cur = self.conn.execute(
            "INSERT INTO replies(wearer, device, in_reply_to, words, created) VALUES (?, ?, ?, ?, ?)",
            (wearer, device, in_reply_to, _dumps(list(words)), now))
        return int(cur.lastrowid)

    def list(self, wearer: str, *, undelivered_only: bool = False, limit: int = 100) -> list[dict]:
        sql = "SELECT id, in_reply_to, words, created, delivered FROM replies WHERE wearer = ?"
        if undelivered_only:
            sql += " AND delivered IS NULL"
        sql += " ORDER BY created DESC, id DESC LIMIT ?"
        return [{"id": int(r["id"]), "in_reply_to": r["in_reply_to"], "words": json.loads(r["words"]),
                 "created": r["created"], "delivered": r["delivered"]}
                for r in self.conn.execute(sql, (wearer, limit))]

    def mark_delivered(self, ids: Iterable[int], now: float) -> int:
        n = 0
        for i in ids:
            n += self.conn.execute("UPDATE replies SET delivered = ? WHERE id = ? AND delivered IS NULL", (now, i)).rowcount
        return n

    def count(self, wearer: str | None = None) -> int:
        if wearer is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM replies").fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM replies WHERE wearer = ?", (wearer,)).fetchone()[0])

    def prune(self, cutoff: float) -> int:
        return self.conn.execute("DELETE FROM replies WHERE created < ?", (cutoff,)).rowcount


# --- events -----------------------------------------------------------------


class EventRepo(_Repo):
    """Append-only and content-free. ``counts`` holds numbers; ``detail`` holds
    a short code (an action name, a pragma result), never words a wearer felt."""

    def append(self, now: float, kind: str, *, wearer: str | None = None, reason: Reason | str | None = None,
               counts: dict[str, int] | None = None, detail: str | None = None) -> None:
        clean = {k: int(v) for k, v in (counts or {}).items() if isinstance(v, (int, float, bool))}
        self.conn.execute(
            "INSERT INTO events(time, wearer, kind, reason, counts, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (now, wearer, kind, str(reason) if reason else None, _dumps(clean), detail[:200] if detail else None))

    def tail(self, n: int = 50, kind: str | None = None) -> list[dict]:
        if kind is None:
            rows = self.conn.execute(
                "SELECT id, time, wearer, kind, reason, counts, detail FROM events ORDER BY id DESC LIMIT ?", (n,))
        else:
            rows = self.conn.execute(
                "SELECT id, time, wearer, kind, reason, counts, detail FROM events WHERE kind = ? ORDER BY id DESC LIMIT ?",
                (kind, n))
        out = [{"id": int(r["id"]), "time": r["time"], "wearer": r["wearer"], "kind": r["kind"],
                "reason": r["reason"], "counts": json.loads(r["counts"]), "detail": r["detail"]} for r in rows]
        out.reverse()
        return out

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM events WHERE kind = ?", (kind,)).fetchone()[0])

    def prune(self, cutoff: float) -> int:
        return self.conn.execute("DELETE FROM events WHERE time < ?", (cutoff,)).rowcount


# --- enrollment codes -------------------------------------------------------


class EnrollCodeRepo(_Repo):
    def insert(self, code_hash: str, wearer: str, expires_at: float, now: float) -> None:
        self.conn.execute(
            "INSERT INTO enroll_codes(code_hash, wearer, expires_at, created) VALUES (?, ?, ?, ?)",
            (code_hash, wearer, expires_at, now))

    def consume(self, code: str, now: float) -> str | None:
        """The wearer the code was minted for, marking it used — or None."""
        rows = self.conn.execute(
            "SELECT code_hash, wearer FROM enroll_codes WHERE used IS NULL AND expires_at > ?", (now,)).fetchall()
        match: tuple[str, str] | None = None
        for r in rows:
            if secret_matches(code, r["code_hash"]):
                match = (r["code_hash"], r["wearer"])
        if match is None:
            return None
        self.conn.execute("UPDATE enroll_codes SET used = ? WHERE code_hash = ?", (now, match[0]))
        return match[1]

    def prune(self, now: float) -> int:
        return self.conn.execute("DELETE FROM enroll_codes WHERE expires_at <= ? OR used IS NOT NULL", (now,)).rowcount
