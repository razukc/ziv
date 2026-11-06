"""The SQLite store: pragmas, idempotent migrations, leases, atomic firing, retention."""
from __future__ import annotations

import sqlite3

import pytest

from ziv.core.model import OutboxEntry, ScheduleEntry, to_datetime
from ziv.store import RetentionPolicy, Store, StoreBusy
from ziv.store.repos import decode_entry, encode_entry
from ziv.wire import Kind, Reason, State, Utterance


def make_store(path, **kw) -> Store:
    s = Store(path, **kw)
    s.migrate(0.0)
    s.wearers.ensure("w", "wearer", 0.0)
    return s


def entry(i: int, now: float, state=State.pending, **kw) -> OutboxEntry:
    utt = Utterance(id=f"u{i:08d}", wearer="w", kind=Kind.message, **{"from": {"sender": "t"}},
                    words=["hi"], spec_version=3, expires=to_datetime(now + 60))
    return OutboxEntry(utterance=utt, state=state, created=now, updated=now, duration_ms=1000, budget_ms=15000, **kw)


def test_pragmas(tmp_path):
    s = make_store(tmp_path / "z.sqlite")
    assert s.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert s.conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    assert s.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrations_are_idempotent_and_recorded(tmp_path):
    p = tmp_path / "z.sqlite"
    s = Store(p)
    assert s.migrate(1.0) == [1]
    assert s.migrate(2.0) == []
    s.close()
    again = Store(p)
    assert again.migrate(3.0) == []
    assert again.applied_versions() == [1]
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"wearers", "devices", "senders", "utterances", "schedule", "prefs", "replies", "events",
            "enroll_codes", "meta", "schema_migrations"} <= tables


def test_integrity_check_records_an_event_instead_of_raising(tmp_path):
    s = make_store(tmp_path / "z.sqlite")
    assert s.integrity_check(5.0) is True
    ev = s.events.tail(1)[0]
    assert ev["kind"] == "integrity_check" and ev["counts"] == {"ok": 1, "findings": 0}


def test_outbox_roundtrip(tmp_path):
    s = make_store(tmp_path / "z.sqlite")
    e = entry(1, 10.0, State.sent, device="d1", sent_at=10.0, tried=frozenset({"d0"}), late=True, lossy=True)
    assert decode_entry(encode_entry(e)) == e
    with s.tx():
        s.outbox.insert(e)
    assert s.outbox.get(e.id) == e
    assert s.outbox.active("w") == [e] and s.outbox.by_device("d1") == [e]
    assert s.outbox.counts()["sent"] == 1
    played = e.with_(state=State.played, updated=20.0)
    with s.tx():
        assert s.outbox.save_changed([e], [played]) == 1
    assert s.outbox.get(e.id).state == State.played and s.outbox.active("w") == []


def test_lease_recovery_after_a_crash_between_claim_and_insert(tmp_path):
    p = tmp_path / "z.sqlite"
    s = make_store(p)
    with s.tx():
        row = s.schedule.insert(ScheduleEntry(None, "w", 100.0, Kind.reminder, "meds", None, 3600, 0.0))
    claimed = s.schedule.claim_due(100.0, 30.0)
    assert [c.id for c in claimed] == [row.id] and claimed[0].lease_until == 130.0
    s.close()  # the process dies before fire()

    s2 = Store(p)
    s2.migrate()
    assert s2.schedule.claim_due(100.0, 30.0) == []       # still leased
    assert s2.schedule.claim_due(129.9, 30.0) == []
    re = s2.schedule.claim_due(130.0, 30.0)               # lease expired: claimed again
    assert [c.id for c in re] == [row.id]
    assert s2.schedule.fire(row.id, entry(1, 130.0)) is True
    assert s2.schedule.fire(row.id, entry(2, 130.0)) is False   # already fired
    assert s2.schedule.count() == 0 and s2.outbox.get("u00000001") is not None
    assert s2.outbox.get("u00000002") is None


def test_two_connections_cannot_double_claim(tmp_path):
    p = tmp_path / "z.sqlite"
    a = make_store(p)
    b = Store(p, busy_timeout_ms=50)
    b.migrate()
    with a.tx():
        row = a.schedule.insert(ScheduleEntry(None, "w", 100.0, Kind.reminder, "meds", None, 3600, 0.0))
    assert [c.id for c in a.schedule.claim_due(100.0, 30.0)] == [row.id]
    assert b.schedule.claim_due(100.0, 30.0) == []   # sees the lease
    # a holds the write lock mid-transaction: b cannot claim, loudly
    a.conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StoreBusy):
            b.schedule.claim_due(200.0, 30.0)
    finally:
        a.conn.execute("ROLLBACK")
    assert [c.id for c in b.schedule.claim_due(200.0, 30.0)] == [row.id]


def test_fire_is_atomic(tmp_path):
    s = make_store(tmp_path / "z.sqlite")
    with s.tx():
        row = s.schedule.insert(ScheduleEntry(None, "w", 100.0, Kind.reminder, "meds", None, 3600, 0.0))
        s.outbox.insert(entry(1, 50.0))
    with pytest.raises(sqlite3.IntegrityError):
        s.schedule.fire(row.id, entry(1, 100.0))  # duplicate id: the insert fails ...
    assert s.schedule.get(row.id) is not None      # ... and the delete rolled back with it
    assert not s.conn.in_transaction


def test_prune_counts_and_keeps_active(tmp_path):
    s = make_store(tmp_path / "z.sqlite")
    with s.tx():
        s.outbox.insert(entry(1, 0.0, State.played))
        s.outbox.insert(entry(2, 0.0, State.pending))
        s.outbox.insert(entry(3, 500.0, State.failed, reason=Reason.hidden))
        s.replies.insert("w", None, None, ["ok"], 0.0)
        s.events.append(0.0, "old")
        s.events.append(900.0, "new")
    policy = RetentionPolicy(utterances_s=100, replies_s=100, events_s=100)
    counts = s.prune(1000.0, policy)
    assert counts == {"utterances": 2, "replies": 1, "events": 1, "enroll_codes": 0}
    assert s.outbox.get("u00000001") is None and s.outbox.get("u00000003") is None
    assert s.outbox.get("u00000002") is not None          # active rows are never pruned
    assert [e["kind"] for e in s.events.tail(5)] == ["new", "prune"]
    assert s.events.tail(1)[0]["counts"]["utterances"] == 2


def test_events_are_content_free_by_construction(tmp_path):
    s = make_store(tmp_path / "z.sqlite")
    s.events.append(1.0, "k", wearer="w", reason=Reason.over_budget,
                    counts={"duration_ms": 1200, "text": "secret words", "ok": True}, detail="x" * 500)
    ev = s.events.tail(1)[0]
    assert ev["counts"] == {"duration_ms": 1200, "ok": 1}
    assert len(ev["detail"]) == 200 and ev["reason"] == "over_budget"


def test_credentials_are_hashed_and_matched_in_constant_time(tmp_path):
    from ziv.core.credentials import hash_secret
    from ziv.core.model import Device, Sender

    s = make_store(tmp_path / "z.sqlite")
    with s.tx():
        s.devices.insert(Device("d1", "w", "band", "six_actuator", True, 0, hash_secret("key-one-1234567890"), 0.0))
        s.senders.insert(Sender("s1", "w", "friend", hash_secret("tok-one-1234567890"), frozenset({"send"}), 60, 0.0))
    assert s.devices.find_by_key("key-one-1234567890").id == "d1"
    assert s.devices.find_by_key("key-one-123456789X") is None
    assert s.senders.find_by_token("tok-one-1234567890").scopes == {"send"}
    assert s.senders.find_by_token("nope") is None
    dump = "\n".join(s.conn.iterdump())
    assert "key-one-1234567890" not in dump and "tok-one-1234567890" not in dump


def test_enroll_codes_consume_once_and_expire(tmp_path):
    from ziv.core.credentials import hash_secret

    s = make_store(tmp_path / "z.sqlite")
    with s.tx():
        s.enroll_codes.insert(hash_secret("ABCD2345"), "w", expires_at=100.0, now=0.0)
        s.enroll_codes.insert(hash_secret("WXYZ6789"), "w", expires_at=100.0, now=0.0)
    with s.tx():
        assert s.enroll_codes.consume("ABCD2345", 10.0) == "w"
        assert s.enroll_codes.consume("ABCD2345", 11.0) is None      # used
        assert s.enroll_codes.consume("WXYZ6789", 100.0) is None     # expired
        assert s.enroll_codes.prune(100.0) == 2
