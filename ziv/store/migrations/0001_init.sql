-- 0001_init: the relay's tables (docs/ARCHITECTURE.md §7).
-- Content lives only where a device must read it back (utterances.body,
-- replies.words); events is content-free by construction.

CREATE TABLE IF NOT EXISTS wearers (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    created REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id         TEXT PRIMARY KEY,
    wearer     TEXT NOT NULL REFERENCES wearers(id),
    name       TEXT NOT NULL,
    profile    TEXT NOT NULL,
    key_hash   TEXT NOT NULL UNIQUE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    ord        INTEGER NOT NULL DEFAULT 0,
    created    REAL NOT NULL,
    last_seen  REAL
);
CREATE INDEX IF NOT EXISTS devices_wearer ON devices(wearer, ord);

CREATE TABLE IF NOT EXISTS senders (
    id           TEXT PRIMARY KEY,
    wearer       TEXT NOT NULL REFERENCES wearers(id),
    label        TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    scopes       TEXT NOT NULL,
    rate_per_min INTEGER NOT NULL,
    created      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS senders_wearer ON senders(wearer);

-- the outbox: the utterance and its bookkeeping as JSON, plus indexed columns
CREATE TABLE IF NOT EXISTS utterances (
    id      TEXT PRIMARY KEY,
    wearer  TEXT NOT NULL REFERENCES wearers(id),
    state   TEXT NOT NULL,
    device  TEXT,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    expires REAL,
    body    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS utterances_wearer_state ON utterances(wearer, state, created);
CREATE INDEX IF NOT EXISTS utterances_device ON utterances(device, state);
CREATE INDEX IF NOT EXISTS utterances_state_updated ON utterances(state, updated);

CREATE TABLE IF NOT EXISTS schedule (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wearer          TEXT NOT NULL REFERENCES wearers(id),
    fire_at         REAL NOT NULL,
    kind            TEXT NOT NULL,
    text            TEXT,
    intent          TEXT,
    expires_after_s INTEGER NOT NULL,
    label           TEXT,
    created         REAL NOT NULL,
    lease_until     REAL
);
CREATE INDEX IF NOT EXISTS schedule_due ON schedule(fire_at);
CREATE INDEX IF NOT EXISTS schedule_wearer ON schedule(wearer, fire_at);

CREATE TABLE IF NOT EXISTS prefs (
    wearer  TEXT PRIMARY KEY REFERENCES wearers(id),
    pace_ms INTEGER NOT NULL,
    advance TEXT NOT NULL,
    late    TEXT NOT NULL,
    history INTEGER NOT NULL DEFAULT 0,
    updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS replies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wearer      TEXT NOT NULL REFERENCES wearers(id),
    device      TEXT,
    in_reply_to TEXT,
    words       TEXT NOT NULL,
    created     REAL NOT NULL,
    delivered   REAL
);
CREATE INDEX IF NOT EXISTS replies_wearer ON replies(wearer, delivered, created);

-- append-only, content-free: time, wearer, kind, reason, counts
CREATE TABLE IF NOT EXISTS events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    time   REAL NOT NULL,
    wearer TEXT,
    kind   TEXT NOT NULL,
    reason TEXT,
    counts TEXT NOT NULL DEFAULT '{}',
    detail TEXT
);
CREATE INDEX IF NOT EXISTS events_time ON events(time);

CREATE TABLE IF NOT EXISTS enroll_codes (
    code_hash  TEXT PRIMARY KEY,
    wearer     TEXT NOT NULL REFERENCES wearers(id),
    expires_at REAL NOT NULL,
    used       REAL,
    created    REAL NOT NULL
);

-- relay-wide key/value (the admin token's hash lives here when minted by `init`)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
