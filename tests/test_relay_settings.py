"""Settings from the environment, and the plain-HTTP guard."""
from __future__ import annotations

import pytest
from pathlib import Path

from ziv.relay.settings import DEFAULT_NEBIUS_BASE_URL, DEFAULT_TEXT_MODEL, Settings, SettingsError


def test_defaults():
    s = Settings.from_env({}, dotenv=False)
    assert s.db_path == "./ziv_data/ziv.sqlite" and s.host == "127.0.0.1" and s.port == 8787
    assert s.allow_plain_http is False and s.admin_token is None
    assert (s.budget_ms, s.outbox_cap, s.schedule_cap) == (15_000, 20, 64)
    assert (s.handoff_window_s, s.body_timeout_s, s.poll_s, s.retention_days) == (8.0, 20.0, 1.0, 7.0)
    assert s.nebius_base_url == DEFAULT_NEBIUS_BASE_URL and s.text_model == DEFAULT_TEXT_MODEL
    assert s.compose_configured is False
    s.check()


def test_from_env_parses_every_knob():
    env = {
        "ZIV_DB_PATH": "/tmp/x.sqlite", "ZIV_HOST": "0.0.0.0", "ZIV_PORT": "9000", "ZIV_ALLOW_PLAIN_HTTP": "yes",
        "ZIV_ADMIN_TOKEN": "t", "ZIV_BUDGET_MS": "12000", "ZIV_OUTBOX_CAP": "5", "ZIV_SCHEDULE_CAP": "7",
        "ZIV_HANDOFF_WINDOW_S": "4.5", "ZIV_BODY_TIMEOUT_S": "10", "ZIV_POLL_S": "0.5", "ZIV_RETENTION_DAYS": "2",
        "NEBIUS_API_KEY": "k", "NEBIUS_BASE_URL": "https://p.example/v1", "ZIV_TEXT_MODEL": "m",
    }
    s = Settings.from_env(env, dotenv=False)
    assert s.db_path == "/tmp/x.sqlite" and s.host == "0.0.0.0" and s.port == 9000 and s.allow_plain_http
    assert s.admin_token == "t" and s.budget_ms == 12000 and s.outbox_cap == 5 and s.schedule_cap == 7
    assert s.handoff_window_s == 4.5 and s.body_timeout_s == 10 and s.poll_s == 0.5 and s.retention_days == 2
    assert s.nebius_api_key == "k" and s.nebius_base_url == "https://p.example/v1" and s.text_model == "m"
    assert s.compose_configured
    assert "k" not in str(s.public().values()) and "admin_token" not in s.public()


def test_bad_values_are_loud():
    with pytest.raises(SettingsError):
        Settings.from_env({"ZIV_PORT": "eighty"}, dotenv=False)
    with pytest.raises(SettingsError):
        Settings(port=70000).check()
    with pytest.raises(SettingsError):
        Settings(tls_cert="c").check()


def test_plain_http_off_loopback_is_refused_unless_allowed():
    with pytest.raises(SettingsError, match="plain HTTP"):
        Settings(host="0.0.0.0").check()
    Settings(host="0.0.0.0", allow_plain_http=True).check()
    Settings(host="0.0.0.0", tls_cert="c.pem", tls_key="k.pem").check()
    Settings(host="localhost").check()
    Settings(host="::1").check()


def test_dotenv_is_read_from_cwd_only(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ZIV_PORT=9999\nZIV_ADMIN_TOKEN=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ZIV_PORT", raising=False)
    monkeypatch.setenv("ZIV_ADMIN_TOKEN", "from-env")
    s = Settings.from_env()
    assert s.port == 9999 and s.admin_token == "from-env"     # the process environment wins
    monkeypatch.chdir(tmp_path.parent)
    assert Settings.from_env({"ZIV_X": "1"}).port == 8787


def test_cli_run_refuses_plain_http_off_loopback(capsys):
    from ziv.cli import main

    rc = main(["run", "--host", "0.0.0.0", "--port", "8787"])
    assert rc == 2 and "plain HTTP" in capsys.readouterr().err


def test_cli_init_and_sender_and_events(tmp_path, capsys, monkeypatch):
    from ziv.cli import main

    monkeypatch.chdir(tmp_path)
    for var in ("ZIV_ADMIN_TOKEN", "ZIV_DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    db = str(tmp_path / "cli.sqlite")
    assert main(["--db", db, "init"]) == 0
    out = capsys.readouterr().out
    token = out.strip().splitlines()[-1]
    assert "admin token (shown once" in out and len(token) >= 32
    assert main(["--db", db, "init"]) == 0
    assert "already minted" in capsys.readouterr().out
    assert main(["--db", db, "sender", "add", "mum", "--scopes", "send,read", "--rate", "5"]) == 0
    out = capsys.readouterr().out
    assert "token (shown once)" in out
    assert main(["--db", db, "enroll-code"]) == 0
    assert "enrollment code:" in capsys.readouterr().out
    assert main(["--db", db, "events", "--tail", "10"]) == 0
    out = capsys.readouterr().out
    assert "admin_token_minted" in out and "sender_created" in out and "enroll_code" in out
    assert token not in out
    # the minted token authenticates as admin
    from ziv.relay.app import create_app
    from ziv.relay.settings import Settings
    from fastapi.testclient import TestClient

    app = create_app(Settings(db_path=db, poll_s=0))
    with TestClient(app) as c:
        assert c.get("/devices", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        assert c.get("/devices", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_front_end_dist_settings_from_env(tmp_path):
    from ziv.relay.settings import Settings, default_dist

    built = tmp_path / "console-build"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html>", encoding="utf-8")
    s = Settings.from_env({"ZIV_CONSOLE_DIST": str(built), "ZIV_CLIENT_DIST": "off"}, dotenv=False)
    assert s.console_dist == str(built) and s.client_dist is None
    # unset: the repo's own build when it exists, else off; never an error
    s = Settings.from_env({}, dotenv=False)
    assert s.client_dist == default_dist("client") and s.console_dist == default_dist("console")
    for v in (s.client_dist, s.console_dist):
        assert v is None or (v.endswith("dist") and (Path(v) / "index.html").is_file())
    assert "client_dist" in Settings().public() and Settings().client_dist is None
