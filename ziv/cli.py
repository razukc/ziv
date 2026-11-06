"""ziv.cli — ``ziv-relay``: run, init, enroll-code, sender add, events."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from ziv.relay.settings import Settings, SettingsError


def _relay(settings: Settings):
    from ziv.relay.clock import SystemClock
    from ziv.relay.composer import EchoComposer
    from ziv.relay.service import Relay
    from ziv.store import Store

    relay = Relay(settings, Store(settings.db_path), SystemClock(), EchoComposer())
    relay.start()
    return relay


def cmd_init(settings: Settings, args: argparse.Namespace) -> int:
    relay = _relay(settings)
    token = relay.mint_admin_token()
    print(f"database: {settings.db_path}")
    print(f"wearer:   {settings.default_wearer}")
    if token:
        print("admin token (shown once; put it in .env as ZIV_ADMIN_TOKEN or keep it where the console reads it):")
        print(token)
    elif settings.admin_token:
        print("admin token: from ZIV_ADMIN_TOKEN")
    else:
        print("admin token: already minted (hash stored); rerun with ZIV_ADMIN_TOKEN to replace it")
    relay.close()
    return 0


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    if args.host:
        settings = settings.with_(host=args.host)
    if args.port:
        settings = settings.with_(port=args.port)
    if args.allow_plain_http:
        settings = settings.with_(allow_plain_http=True)
    try:
        settings.check()
    except SettingsError as exc:
        print(f"ziv-relay: {exc}", file=sys.stderr)
        return 2
    import uvicorn

    from ziv.relay.app import create_app

    scheme = "https" if settings.tls else "http"
    print(f"ziv-relay listening on {scheme}://{settings.host}:{settings.port}  db={settings.db_path}  "
          f"compose={'live' if settings.compose_configured else 'echo'}")
    if not settings.tls and not settings.is_loopback:
        print("WARNING: plain HTTP off loopback (ZIV_ALLOW_PLAIN_HTTP). Bench use only.", file=sys.stderr)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info",
                ssl_certfile=settings.tls_cert, ssl_keyfile=settings.tls_key)
    return 0


def cmd_enroll_code(settings: Settings, args: argparse.Namespace) -> int:
    relay = _relay(settings)
    resp = relay.enroll_code(settings.default_wearer)
    print(f"enrollment code: {resp.code}  (valid until {resp.expires.isoformat()})")
    relay.close()
    return 0


def cmd_sender_add(settings: Settings, args: argparse.Namespace) -> int:
    from ziv.wire import CreateSender

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    relay = _relay(settings)
    view = relay.create_sender(settings.default_wearer, CreateSender(label=args.label, scopes=scopes, rate_per_min=args.rate))
    print(f"sender {view.id} ({view.label}) scopes={','.join(view.scopes)} rate={view.rate_per_min}/min")
    print("token (shown once):")
    print(view.token)
    relay.close()
    return 0


def cmd_events(settings: Settings, args: argparse.Namespace) -> int:
    from ziv.store import Store

    store = Store(settings.db_path)
    store.migrate()
    for row in store.events.tail(args.tail, kind=args.kind):
        when = datetime.fromtimestamp(row["time"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        counts = json.dumps(row["counts"], sort_keys=True) if row["counts"] else ""
        bits = [when, row["kind"]]
        if row["wearer"]:
            bits.append(f"wearer={row['wearer']}")
        if row["reason"]:
            bits.append(f"reason={row['reason']}")
        if counts and counts != "{}":
            bits.append(counts)
        if row["detail"]:
            bits.append(f"detail={row['detail']}")
        print("  ".join(bits))
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ziv-relay", description="Ziv relay: a haptic message channel for deaf-blind wearers")
    p.add_argument("--db", help="override ZIV_DB_PATH")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="serve the relay (uvicorn)")
    run.add_argument("--host")
    run.add_argument("--port", type=int)
    run.add_argument("--allow-plain-http", action="store_true", help="serve plain HTTP off loopback (bench only)")
    run.set_defaults(fn=cmd_run)

    init = sub.add_parser("init", help="create the database and the admin token")
    init.set_defaults(fn=cmd_init)

    code = sub.add_parser("enroll-code", help="mint a short-lived device enrollment code")
    code.set_defaults(fn=cmd_enroll_code)

    sender = sub.add_parser("sender", help="manage senders")
    sender_sub = sender.add_subparsers(dest="sender_command", required=True)
    add = sender_sub.add_parser("add", help="create a sender token")
    add.add_argument("label")
    add.add_argument("--scopes", default="send,read", help="comma-separated: send,read,admin")
    add.add_argument("--rate", type=int, default=60, help="requests per minute")
    add.set_defaults(fn=cmd_sender_add)

    events = sub.add_parser("events", help="print the tail of the content-free event log")
    events.add_argument("--tail", type=int, default=50)
    events.add_argument("--kind")
    events.set_defaults(fn=cmd_events)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        print(f"ziv-relay: {exc}", file=sys.stderr)
        return 2
    if args.db:
        settings = settings.with_(db_path=args.db)
    return int(args.fn(settings, args))


if __name__ == "__main__":
    sys.exit(main())
