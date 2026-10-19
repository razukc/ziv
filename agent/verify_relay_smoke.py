"""
Minimal relay smoke check for the Ziv full demo.

Starts `agent/ziv_server.py` on a free port and asserts the essentials:
- `/api/ziv/health` answers 200 ok
- `/ziv_client/index.html` is served

This is the non-WS baseline. The full reminder-fire contract is in
`agent/verify_relay.py --demo`.

Run from the repo root:
    python agent/verify_relay_smoke.py
    python agent/verify_relay_smoke.py --port 8787
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
RELAY = REPO_ROOT / "agent" / "ziv_server.py"

if not RELAY.is_file():
    sys.exit(f"missing relay entrypoint: {RELAY}")

HEALTH_URL = "/api/ziv/health"
PAGE_URL = "/ziv_client/index.html"


def http_get(path: str, *, port: int = 8787, timeout: float = 8.0):
    req = Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        return None, str(exc).encode("utf-8", "replace")


def wait_ready(*, port: int = 8787, proc: subprocess.Popen, timeout_s: float = 45.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            status, body = http_get(HEALTH_URL, port=port)
            if status == 200 and b"ok" in body and b"status" in body:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def start_relay(*, port: int = 8787, fake_seconds: float = 0.05) -> subprocess.Popen:
    env = os.environ.copy()
    env["ZIV_PORT"] = str(port)
    env["ZIV_FAKE_MODEL_SECONDS"] = str(fake_seconds)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    log = Path(f"agent/_verify_relay_smoke_{port}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")
    return subprocess.Popen(
        [sys.executable, str(RELAY)],
        cwd=str(RELAY.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log.open("ab"),
        stderr=subprocess.STDOUT,
    )


def stop_relay(proc: subprocess.Popen) -> int | None:
    if proc.poll() is not None:
        return proc.returncode
    try:
        sig = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT
        proc.send_signal(sig)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
    return proc.returncode


def log_tail(path: Path, n: int = 2000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-n:]
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ziv relay smoke check")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--fake", type=float, default=0.05)
    args = p.parse_args(argv)

    port = args.port
    log = Path(f"agent/_verify_relay_smoke_{port}.log")
    proc = start_relay(port=port, fake_seconds=args.fake)
    try:
        ready = wait_ready(port=port, proc=proc)
        print("ready:", ready, flush=True)

        health_status, health_body = http_get(HEALTH_URL, port=port)
        page_status, page_body = http_get(PAGE_URL, port=port)

        print("health:", health_status, flush=True)
        print("page:", page_status, len(page_body), flush=True)

        if not ready:
            print("RESULT: relay did not become ready", flush=True)
            print("LOG:", log_tail(log), flush=True)
            return 2

        if health_status != 200:
            print("RESULT: health check failed", flush=True)
            return 3

        if page_status != 200:
            print("RESULT: client page not served", flush=True)
            return 4

        print("RESULT: relay OK", flush=True)
        return 0
    finally:
        stop_relay(proc)


if __name__ == "__main__":
    raise SystemExit(main())
