"""
Standalone relay verification for the Ziv “Try out” full demo.

It starts `agent/ziv_server.py` on a free port, waits for `/api/ziv/health`,
attaches a headless WS reader, schedules a reminder, and asserts the reminder
fires on the wire with the name-mark prefix before the content cells.

Run from the repo root:
    python agent/verify_relay.py              # smoke test, custom port optional
    python agent/verify_relay.py --demo       # also assert WS reminder fire
    python agent/verify_relay.py --port 8787  # custom port

Exit codes:
    0  relay started and health OK (and, with --demo, reminder fired on WS)
    1  --demo run but the reminder frame was not observed on the wire
    2  relay did not become ready
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import threading
import queue
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
RELAY = REPO_ROOT / "agent" / "ziv_server.py"

if not RELAY.is_file():
    sys.exit(f"missing relay entrypoint: {RELAY}")


def http_json(path: str, *, method: str = "GET", body=None, port: int = 8787,
              timeout: float = 8.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, raw
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return None, repr(exc)


def wait_ready(*, port: int = 8787, proc: subprocess.Popen, timeout_s: float = 45.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            s, body = http_json("/api/ziv/health", port=port)
            if s == 200 and '"status"' in body and '"ok"' in body:
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
    log = Path(f"agent/_verify_relay_{port}.log")
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


def ws_reader(q: queue.Queue, *, port: int = 8787) -> threading.Thread:
    def target():
        try:
            import asyncio
            import websockets

            async def run():
                try:
                    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                        while True:
                            msg = await ws.recv()
                            q.put(msg)
                except Exception as exc:
                    q.put(("error", repr(exc)))

            asyncio.run(run())
        except Exception as exc:
            q.put(("error", repr(exc)))

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


def run_demo(*, port: int = 8787, fake_seconds: float = 0.15) -> dict:
    log = Path(f"agent/_verify_relay_{port}.log")
    proc = start_relay(port=port, fake_seconds=fake_seconds)
    try:
        if not wait_ready(port=port, proc=proc):
            return {"error": "relay did not become ready", "log_tail": _log_tail(log)}

        q: queue.Queue = queue.Queue()
        ws_reader(q, port=port)
        time.sleep(0.6)

        http_json("/api/ziv/schedule", method="DELETE", port=port)
        fire_at = int(time.time()) + 3
        s, body = http_json(
            "/api/ziv/schedule",
            method="POST",
            body={"fire_at": float(fire_at), "text": "frontend corner turn"},
            port=port,
        )
        result: dict = {"schedule": {"status": s, "body": body[:300]}}

        deadline = time.time() + 12
        frames: list[str] = []
        fired = False
        while time.time() < deadline:
            try:
                msg = q.get(timeout=0.4)
                if isinstance(msg, tuple) and msg[0] == "error":
                    result["ws_error"] = msg[1]
                    break
                frames.append(msg)
                if "reminder: frontend corner turn" in msg:
                    fired = True
            except Exception:
                if time.time() >= deadline:
                    break
        result["frames"] = len(frames)
        result["fired"] = fired
        if frames:
            result["last"] = frames[-1][:200]
        return result
    finally:
        stop_relay(proc)


def _log_tail(path: Path, n: int = 2000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-n:]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ziv relay verification harness")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--fake", type=float, default=0.05,
                   help="ZIV_FAKE_MODEL_SECONDS for the run")
    p.add_argument("--demo", action="store_true",
                   help="attach a WS reader and assert the reminder fires on the wire")
    args = p.parse_args(argv)

    if args.demo:
        result = run_demo(port=args.port, fake_seconds=args.fake)
        print(json.dumps(result, ensure_ascii=False))
        if "error" in result:
            return 2
        if not result.get("fired"):
            return 1
        return 0

    log = Path(f"agent/_verify_relay_{args.port}.log")
    proc = start_relay(port=args.port, fake_seconds=args.fake)
    print(json.dumps({"pid": proc.pid, "port": args.port, "log": str(log)}))
    try:
        if not wait_ready(port=args.port, proc=proc):
            print("RELAY FAILED TO START", file=sys.stderr)
            print(_log_tail(log), file=sys.stderr)
            stop_relay(proc)
            return 2
        print("RELAY READY", flush=True)
        try:
            proc.wait()
        except KeyboardInterrupt:
            stop_relay(proc)
    except KeyboardInterrupt:
        stop_relay(proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
