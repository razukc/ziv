"""Tests for agent/ziv_store.py — the wearer's durable state (relay v1).

Hermetic: every test points ``DATA_DIR`` at a fresh temp dir, so the real
wearer files under ``agent/ziv_data/`` are never touched. What is proven:

* ``WearerMemory`` round-trips across instances (persistence), tolerates a
  corrupt file (default returned, problem reported, store keeps working);
* ``MessageInbox`` offers/takes/pends/clears FIFO, marks delivered only when
  told (peek/mark split — redelivery, never loss), enforces the cap by
  dropping the oldest, and recovers from a corrupt file;
* the atomic-write discipline leaves no temp files behind.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import ziv_store as zs


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "ziv_data"
    d.mkdir()
    monkeypatch.setattr(zs, "DATA_DIR", d)
    return d


# ---------------------------------------------------------------------------
# WearerMemory
# ---------------------------------------------------------------------------

def test_memory_roundtrip_and_missing_default(data_dir):
    m = zs.WearerMemory("t1")
    assert m.get("anything") is None
    m.set("cell_gap_ms", 300)
    m.set("profile", {"name": "t1", "tags": [1, 2]})
    # A *new* instance reads the same files — persistence across restarts.
    m2 = zs.WearerMemory("t1")
    assert m2.get("cell_gap_ms") == 300
    assert m2.get("profile") == {"name": "t1", "tags": [1, 2]}
    assert m2.get("missing", 42) == 42


def test_memory_corrupt_file_returns_default_and_reports(data_dir):
    m = zs.WearerMemory("t1")
    m.set("good", 1)
    (zs.DATA_DIR / "t1.bad.json").write_text("{not json", encoding="utf-8")
    assert m.get("bad", "fallback") == "fallback"
    assert m.take_corrupt_files() == ["bad"]
    assert m.take_corrupt_files() == []  # reported once
    # The store still works after a corrupt file.
    assert m.get("good") == 1


# ---------------------------------------------------------------------------
# MessageInbox
# ---------------------------------------------------------------------------

def test_inbox_offer_take_fifo_and_mark(data_dir):
    ib = zs.MessageInbox("t1")
    assert ib.count() == 0
    assert ib.peek_one() is None
    ib.offer("first")
    ib.offer("second", source="audio")
    assert ib.count() == 2
    # pending() does not consume; peek_one() does not mark.
    assert ib.pending()[0]["text"] == "first"
    assert ib.count() == 2
    entry = ib.peek_one()
    assert entry["text"] == "first" and entry["delivered"] is False
    assert ib.count() == 2
    # take() marks everything delivered (legacy all-at-once path).
    taken = ib.take()
    assert [e["text"] for e in taken] == ["first", "second"]
    assert ib.count() == 0
    # Files persist; a new instance sees the (delivered) history.
    ib2 = zs.MessageInbox("t1")
    assert ib2.count() == 0
    assert len(json.loads((zs.DATA_DIR / "t1.inbox.json").read_text(encoding="utf-8"))) == 2


def test_inbox_peek_mark_split_survives_vanished_band(data_dir):
    ib = zs.MessageInbox("t1")
    ib.offer("hello")
    entry = ib.peek_one()
    # The band vanishes mid-delivery: no mark_delivered call happens.
    assert ib.count() == 1
    # Next attach peeks the same message again — redelivery, never loss.
    assert ib.peek_one()["text"] == "hello"
    ib.mark_delivered(entry)
    assert ib.count() == 0


def test_inbox_mark_delivered_is_selective(data_dir):
    ib = zs.MessageInbox("t1")
    a = ib.offer("a")
    ib.offer("b")
    ib.mark_delivered(a)
    left = ib.pending()
    assert [e["text"] for e in left] == ["b"]


def test_inbox_cap_drops_oldest(data_dir, monkeypatch):
    monkeypatch.setattr(zs, "INBOX_CAP", 3)
    ib = zs.MessageInbox("t1")
    for t in ("m1", "m2", "m3", "m4", "m5"):
        ib.offer(t)
    assert ib.count() == 3
    texts = [e["text"] for e in ib.pending()]
    assert texts == ["m3", "m4", "m5"]  # oldest dropped


def test_inbox_clear_and_corrupt_recovery(data_dir):
    ib = zs.MessageInbox("t1")
    ib.offer("x")
    assert ib.clear() == 1
    assert ib.count() == 0
    # Corrupt file: reads return empty, the problem is reported, and the
    # next write rebuilds a working file.
    (zs.DATA_DIR / "t1.inbox.json").write_text("[{broken", encoding="utf-8")
    assert ib.take() == []
    assert ib.take_corrupt_files() == ["inbox"]
    ib.offer("after")
    assert ib.count() == 1


def test_atomic_write_leaves_no_temp_files(data_dir):
    m = zs.WearerMemory("t1")
    m.set("k", {"v": 1})
    ib = zs.MessageInbox("t1")
    ib.offer("x")
    sched = zs.ScheduledReminders("t1")
    sched.add(1.0, "x")
    assert not list(zs.DATA_DIR.glob("*.tmp"))


# ---------------------------------------------------------------------------
# ScheduledReminders — durable like the inbox
# ---------------------------------------------------------------------------


def test_schedule_roundtrip_across_instances(data_dir):
    """The point of durability: a reminder promised for tomorrow survives a
    restart tonight. Add on one instance, read and take on a fresh one."""
    s1 = zs.ScheduledReminders("w1")
    s1.add(1234.5, "pills")
    s1.add(2345.0, "call back", source="scheduled")
    # A fresh instance is a restarted relay: same pending reminders.
    s2 = zs.ScheduledReminders("w1")
    pending = s2.list_all()
    assert [r["text"] for r in pending] == ["pills", "call back"]  # soonest first
    assert pending[0]["fire_at"] == 1234.5
    assert pending[1]["source"] == "scheduled"
    assert all(r["fired"] is False for r in pending)
    # Ids never repeat across restarts: they continue from the file.
    third = s2.add(3456.0, "third")
    assert third["id"] == max(r["id"] for r in pending) + 1


def test_schedule_take_due_claims_then_releases(data_dir):
    """take_due removes BEFORE handing out (the inbox's rule): a crash
    between take and playback means a fire again, never a double state."""
    s = zs.ScheduledReminders("w2")
    s.add(time.time() - 5, "already due")
    s.add(time.time() + 500, "later")
    due = s.take_due()
    assert [r["text"] for r in due] == ["already due"]
    # Claimed = removed: a second take (or a fresh instance) sees only "later".
    assert s.take_due() == []
    assert [r["text"] for r in zs.ScheduledReminders("w2").list_all()] == ["later"]


def test_schedule_take_due_uses_one_now(data_dir, monkeypatch):
    """The clock is read once per take: a reminder whose fire_at passes
    between two reads must not be both fired AND kept."""
    s = zs.ScheduledReminders("w3")
    s.add(1000.0, "at 1000")
    clock = {"t": 999.0}
    monkeypatch.setattr(zs.time, "time", lambda: clock["t"])
    clock["t"] = 1000.0  # fire_at == now: boundary is due
    due = s.take_due()
    assert [r["text"] for r in due] == ["at 1000"]
    assert s.list_all() == []  # not kept by a second, later clock read


def test_schedule_clear_and_corrupt_recovery(data_dir):
    s = zs.ScheduledReminders("w4")
    s.add(1.0, "x")
    assert s.clear() == 1
    assert s.list_all() == []
    # Corrupt file: reads return empty, the problem is reported, and the
    # next write rebuilds a working file — the inbox's exact recovery shape.
    (zs.DATA_DIR / "w4.schedule.json").write_text("[{broken", encoding="utf-8")
    assert s.list_all() == []
    assert s.take_corrupt_files() == ["schedule"]
    s.add(2.0, "after")
    assert [r["text"] for r in s.list_all()] == ["after"]


def test_schedule_malformed_rows_are_dropped_not_crashing(data_dir):
    """A hand-edited or truncated file cannot crash the fire loop: rows
    missing id/fire_at/text (or with wrong types) are dropped at load."""
    s = zs.ScheduledReminders("w5")
    (zs.DATA_DIR / "w5.schedule.json").write_text(
        json.dumps([
            {"id": 1, "fire_at": 10.0, "text": "good"},
            {"id": "two", "fire_at": 20.0, "text": "bad id"},
            {"id": 3, "fire_at": "thirty", "text": "bad fire_at"},
            {"id": 4, "fire_at": 40.0},
            "not even a dict",
            {"id": 6, "fire_at": 60.0, "text": "also good", "extra": 1},
        ]),
        encoding="utf-8",
    )
    assert [r["text"] for r in s.list_all()] == ["good", "also good"]
    # take_due claims exactly the well-formed rows (10.0/60.0 are long past
    # epoch) and never chokes on the malformed ones it dropped.
    due = s.take_due()
    assert [r["text"] for r in due] == ["good", "also good"]
    assert s.take_due() == []
    # Ids continue past the max seen in the file.
    assert s.add(70.0, "next")["id"] == 7


def test_schedule_cap_drops_oldest(data_dir, monkeypatch):
    monkeypatch.setattr(zs, "SCHEDULE_CAP", 3)
    s = zs.ScheduledReminders("w6")
    for i in range(5):
        s.add(100.0 + i, f"r{i}")
    assert [r["text"] for r in s.list_all()] == ["r2", "r3", "r4"]
