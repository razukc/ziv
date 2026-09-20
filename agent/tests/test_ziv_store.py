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
    assert not list(zs.DATA_DIR.glob("*.tmp"))
