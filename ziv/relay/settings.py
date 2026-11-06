"""ziv.relay.settings — one frozen settings object, read from the environment.

``Settings.from_env()`` reads ``os.environ`` over a ``.env`` in the current
directory (and nowhere else). Every provider URL has exactly one default.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path

DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_TEXT_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


class SettingsError(ValueError):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int, name: str) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer, got {value!r}") from exc


def _float(value: str | None, default: float, name: str) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number, got {value!r}") from exc


def _str(value: str | None, default: str | None) -> str | None:
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: str = "./ziv_data/ziv.sqlite"
    host: str = "127.0.0.1"
    port: int = 8787
    allow_plain_http: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    admin_token: str | None = None
    budget_ms: int = 15_000
    outbox_cap: int = 20
    schedule_cap: int = 64
    handoff_window_s: float = 8.0
    body_timeout_s: float = 20.0
    poll_s: float = 1.0
    retention_days: float = 7.0
    nebius_api_key: str | None = None
    nebius_base_url: str = DEFAULT_NEBIUS_BASE_URL
    text_model: str = DEFAULT_TEXT_MODEL
    # bounds that are not in the architecture's list but keep the relay bounded
    device_capacity: int = 4           # utterances a device may hold at once
    lease_s: float = 30.0              # schedule claim lease
    hello_timeout_s: float = 5.0       # first frame must arrive within this
    send_timeout_s: float = 5.0        # one frame to one device
    max_body_bytes: int = 64 * 1024
    prune_interval_s: float = 600.0
    enroll_code_ttl_s: float = 600.0
    default_wearer: str = "w_1"
    wearer_name: str = "wearer"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, dotenv: bool = True) -> "Settings":
        merged: dict[str, str] = {}
        if dotenv:
            try:
                from dotenv import dotenv_values

                path = Path.cwd() / ".env"
                if path.is_file():
                    merged.update({k: v for k, v in dotenv_values(path).items() if v is not None})
            except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
                pass
        merged.update(os.environ if env is None else env)
        g = merged.get
        d = cls()  # defaults (slots: the class attributes are descriptors)
        return cls(
            db_path=_str(g("ZIV_DB_PATH"), d.db_path) or d.db_path,
            host=_str(g("ZIV_HOST"), d.host) or d.host,
            port=_int(g("ZIV_PORT"), d.port, "ZIV_PORT"),
            allow_plain_http=_bool(g("ZIV_ALLOW_PLAIN_HTTP"), False),
            tls_cert=_str(g("ZIV_TLS_CERT"), None),
            tls_key=_str(g("ZIV_TLS_KEY"), None),
            admin_token=_str(g("ZIV_ADMIN_TOKEN"), None),
            budget_ms=_int(g("ZIV_BUDGET_MS"), d.budget_ms, "ZIV_BUDGET_MS"),
            outbox_cap=_int(g("ZIV_OUTBOX_CAP"), d.outbox_cap, "ZIV_OUTBOX_CAP"),
            schedule_cap=_int(g("ZIV_SCHEDULE_CAP"), d.schedule_cap, "ZIV_SCHEDULE_CAP"),
            handoff_window_s=_float(g("ZIV_HANDOFF_WINDOW_S"), d.handoff_window_s, "ZIV_HANDOFF_WINDOW_S"),
            body_timeout_s=_float(g("ZIV_BODY_TIMEOUT_S"), d.body_timeout_s, "ZIV_BODY_TIMEOUT_S"),
            poll_s=_float(g("ZIV_POLL_S"), d.poll_s, "ZIV_POLL_S"),
            retention_days=_float(g("ZIV_RETENTION_DAYS"), d.retention_days, "ZIV_RETENTION_DAYS"),
            nebius_api_key=_str(g("NEBIUS_API_KEY"), None),
            nebius_base_url=_str(g("NEBIUS_BASE_URL"), DEFAULT_NEBIUS_BASE_URL) or DEFAULT_NEBIUS_BASE_URL,
            text_model=_str(g("ZIV_TEXT_MODEL"), DEFAULT_TEXT_MODEL) or DEFAULT_TEXT_MODEL,
            device_capacity=_int(g("ZIV_DEVICE_CAPACITY"), d.device_capacity, "ZIV_DEVICE_CAPACITY"),
            lease_s=_float(g("ZIV_LEASE_S"), d.lease_s, "ZIV_LEASE_S"),
            hello_timeout_s=_float(g("ZIV_HELLO_TIMEOUT_S"), d.hello_timeout_s, "ZIV_HELLO_TIMEOUT_S"),
            send_timeout_s=_float(g("ZIV_SEND_TIMEOUT_S"), d.send_timeout_s, "ZIV_SEND_TIMEOUT_S"),
            max_body_bytes=_int(g("ZIV_MAX_BODY_BYTES"), d.max_body_bytes, "ZIV_MAX_BODY_BYTES"),
            prune_interval_s=_float(g("ZIV_PRUNE_INTERVAL_S"), d.prune_interval_s, "ZIV_PRUNE_INTERVAL_S"),
            enroll_code_ttl_s=_float(g("ZIV_ENROLL_CODE_TTL_S"), d.enroll_code_ttl_s, "ZIV_ENROLL_CODE_TTL_S"),
            default_wearer=_str(g("ZIV_WEARER_ID"), d.default_wearer) or d.default_wearer,
            wearer_name=_str(g("ZIV_WEARER_NAME"), d.wearer_name) or d.wearer_name,
        )

    def with_(self, **changes) -> "Settings":
        return replace(self, **changes)

    @property
    def is_loopback(self) -> bool:
        return self.host.strip().lower() in LOOPBACK_HOSTS

    @property
    def tls(self) -> bool:
        return bool(self.tls_cert and self.tls_key)

    @property
    def compose_configured(self) -> bool:
        return bool(self.nebius_api_key and self.text_model)

    def check(self) -> None:
        """Refuse a plain-HTTP bind off loopback unless explicitly allowed (§9)."""
        if self.port < 1 or self.port > 65535:
            raise SettingsError(f"ZIV_PORT must be 1..65535, got {self.port}")
        if self.budget_ms < 1000:
            raise SettingsError("ZIV_BUDGET_MS must be at least 1000")
        for name in ("outbox_cap", "schedule_cap", "device_capacity"):
            if getattr(self, name) < 1:
                raise SettingsError(f"{name} must be at least 1")
        if (self.tls_cert is None) != (self.tls_key is None):
            raise SettingsError("ZIV_TLS_CERT and ZIV_TLS_KEY must be set together")
        if not self.is_loopback and not self.tls and not self.allow_plain_http:
            raise SettingsError(
                f"refusing to serve plain HTTP on {self.host}:{self.port}: off loopback the relay needs TLS "
                "(ZIV_TLS_CERT + ZIV_TLS_KEY, or a TLS reverse proxy in front of a loopback bind). "
                "For a LAN bench only, set ZIV_ALLOW_PLAIN_HTTP=1."
            )

    def public(self) -> dict[str, object]:
        """The settings without secrets, for the CLI's banner."""
        hidden = {"admin_token", "nebius_api_key"}
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in hidden}
