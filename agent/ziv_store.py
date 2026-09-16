"""agent/ziv_store.py — the wearer's own memory, persistent across restarts.

Relay v0 kept everything in process memory: a message that arrived while no
phone was attached vanished, and the wearer's playback-pace preference reset
on every restart. Relay v1 gives the wearer two durable things:

* ``WearerMemory`` — per-wearer key/value memory (profile facts, preferences),
  atomic JSON, never crashes on a corrupt file: a corrupt file is discarded
  and reported through ``take_corrupt_files()``, not silently swallowed.
* ``MessageInbox`` — a capped, persistent message inbox: what the queue gate
  is for a turn, the inbox is for days. An inbound message with no band
  attached is *stored*, not dropped — and offered on the next attach, under
  the wearer's control, like the queue.

One JSON file per key under ``agent/ziv_data/`` (gitignored — it is the
wearer's data, not repo state).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "ziv_data"

# Inbox discipline (plan §9: bounded memory everywhere; the inbox is capped).
INBOX_CAP = 20


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Atomic JSON write: temp file + os.replace, the same discipline as
    agent/pipeline_store.py — a crash mid-write never corrupts the file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path) -> tuple[Any | None, bool]:
    """Load one JSON file; returns ``(payload, corrupt)``. A missing file is
    not corrupt — that is just a fresh wearer."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), False
    except FileNotFoundError:
        return None, False
    except Exception:
        return None, True


class WearerMemory:
    """Per-wearer key/value memory (profile facts, preferences).

    Each key is one JSON file; every write is atomic; every read tolerates a
    corrupt file by returning the caller's default and remembering the key
    in ``take_corrupt_files()`` so the relay's health can surface it.
    """

    #: The playback-pace preference key (value: ms inside the spec's
    #: cell-gap envelope — the server clamps, the spec owns the envelope).
    PREF_CELL_GAP = "cell_gap_ms"

    def __init__(self, wearer_id: str = "wearer") -> None:
        self.wearer_id = wearer_id
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._corrupt_keys: list[str] = []

    def _path(self, key: str) -> Path:
        # Keys are slugs the relay controls; keep them file-safe anyway.
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
        return DATA_DIR / f"{self.wearer_id}.{safe}.json"

    def get(self, key: str, default: Any = None) -> Any:
        payload, corrupt = _load_json(self._path(key))
        if corrupt:
            with self._lock:
                self._corrupt_keys.append(key)
            return default
        return default if payload is None else payload

    def set(self, key: str, value: Any) -> None:
        _atomic_write_json(self._path(key), value)

    def take_corrupt_files(self) -> list[str]:
        """Report (and forget) keys whose files failed to parse, for health."""
        with self._lock:
            out, self._corrupt_keys = self._corrupt_keys, []
        return out


class MessageInbox:
    """Capped, persistent message inbox with gated delivery.

    Storage: one JSON list under ``<wearer>.inbox.json`` — dicts of
    ``{"text", "at", "source", "delivered"}``, oldest first, capped at
    ``INBOX_CAP`` (oldest dropped when full). ``offer()`` stores; ``take()``
    hands the wearer control of delivery, like the queue gate does for a
    single turn.
    """

    def __init__(self, wearer_id: str = "wearer") -> None:
        self.wearer_id = wearer_id
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # RLock: public methods hold it while calling _load/_save, which
        # re-acquire — reentrant makes the nesting harmless.
        self._lock = threading.RLock()
        self._corrupt_keys: list[str] = []
        self._path = DATA_DIR / f"{self.wearer_id}.inbox.json"

    def _load(self) -> list[dict[str, Any]]:
        payload, corrupt = _load_json(self._path)
        if corrupt or (payload is not None and not isinstance(payload, list)):
            with self._lock:
                if "inbox" not in self._corrupt_keys:
                    self._corrupt_keys.append("inbox")
            return []
        return [e for e in (payload or []) if isinstance(e, dict)]

    def _save(self, entries: list[dict[str, Any]]) -> None:
        _atomic_write_json(self._path, entries)

    def take_corrupt_files(self) -> list[str]:
        """Report (and forget) corrupt-file keys, for health."""
        with self._lock:
            out, self._corrupt_keys = self._corrupt_keys, []
        return out

    def offer(self, text: str, *, source: str = "message") -> dict[str, Any]:
        """Store one inbound message (oldest dropped when the cap is hit)."""
        entry = {"text": text, "at": _now_iso(), "source": source,
                 "delivered": False}
        with self._lock:
            entries = self._load()
            entries.append(entry)
            if len(entries) > INBOX_CAP:
                entries = entries[-INBOX_CAP:]
            self._save(entries)
        return entry

    def take(self) -> list[dict[str, Any]]:
        """All undelivered messages, oldest first — and mark them delivered.

        Marking happens at take time so a crash between take and playback
        cannot silently drop a message: a redelivery is the failure mode,
        not a loss (the wrist says everything twice, never nothing).
        """
        with self._lock:
            entries = self._load()
            out = [e for e in entries if not e.get("delivered")]
            for e in out:
                e["delivered"] = True
            if out:
                self._save(entries)
            return out

    def count(self) -> int:
        """Undelivered count — what the server shows as pending."""
        with self._lock:
            return sum(1 for e in self._load() if not e.get("delivered"))

    def pending(self) -> list[dict[str, Any]]:
        """Undelivered entries without marking them (health/preview)."""
        with self._lock:
            return [e for e in self._load() if not e.get("delivered")]

    def peek_one(self) -> dict[str, Any] | None:
        """The oldest undelivered entry, without marking it.

        The delivery loop peeks, plays, and *then* marks (``mark_delivered``)
        — so a band vanishing mid-delivery leaves the message pending:
        redelivery is the failure mode, never a silent loss.
        """
        with self._lock:
            for e in self._load():
                if not e.get("delivered"):
                    return e
            return None

    def mark_delivered(self, entry: dict[str, Any]) -> None:
        """Mark one offered entry delivered (matched by text + timestamp)."""
        with self._lock:
            entries = self._load()
            for i, e in enumerate(entries):
                if (e.get("text") == entry.get("text")
                        and e.get("at") == entry.get("at")
                        and not e.get("delivered")):
                    entries[i] = {**e, "delivered": True}
                    self._save(entries)
                    return

    def clear(self) -> int:
        """The wearer discards everything pending; returns how many."""
        with self._lock:
            entries = self._load()
            n = sum(1 for e in entries if not e.get("delivered"))
            if n:
                self._save([{**e, "delivered": True} for e in entries])
            return n
