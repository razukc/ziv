"""
Standalone relay smoke harness for the Ziv full-demo “Try out” link.

Runs the relay as a child process on a free port, waits for health, then
optionally connects a headless WebSocket reader and asserts the reminder
fire + queue + 429 contracts over the wire.

Usage examples:
    python agent/_run_relay.py                        # start relay only
    python agent/_run_relay.py --demo                 # run the WS smoke test
    python agent/_run_relay.py --demo --port 8787     # custom port
"""
from __future__ import annotations

import argparse, json, os, signal, subprocess, sys, time, threading, queue
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
RELAY = REPO_ROOT / "agent" / "ziv_server.py"
DEFAULT_PORT = 8787


def http_json(path: str, *, method: str = "GET", body=None, port: int = DEFAULT_PORT,
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


def wait_ready(*, port: int = DEFAULT_PORT, timeout_s: float = 60.0,
               proc: subprocess.Popen | None = None) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            s, body = http_json("/api/ziv/health", port=port)
            if s == 200 and '"status"' in body and '"ok"' in body:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def run_relay(*, port: int = DEFAULT_PORT, fake_seconds: float = 0.05,
              log: Path | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env["ZIV_PORT"] = str(port)
    env["ZIV_FAKE_MODEL_SECONDS"] = str(fake_seconds)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if log is None:
        log = Path(f"agent/_relay_{port}.log")
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


def kill(proc: subprocess.Popen) -> int | None:
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


def reader_thread(q: queue.Queue, *, port: int = DEFAULT_PORT) -> threading.Thread:
    def run():
        try:
            import asyncio
            import websockets

            async def _run():
                try:
                    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                        while True:
                            msg = await ws.recv()
                            q.put(msg)
                except Exception as exc:
                    q.put(("error", repr(exc)))

            asyncio.run(_run())
        except Exception as exc:
            q.put(("error", repr(exc)))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def run_demo(*, port: int = DEFAULT_PORT, fake_seconds: float = 0.15) -> dict:
    log = Path(f"agent/_relay_{port}.log")
    proc = run_relay(port=port, fake_seconds=fake_seconds, log=log)
    try:
        if not wait_ready(port=port, proc=proc):
            return {"error": "relay did not become ready", "log_tail": log_read_tail(log)}

        q: queue.Queue = queue.Queue()
        reader_thread(q, port=port)
        time.sleep(0.6)

        http_json("/api/ziv/schedule", method="DELETE", port=port)
        fire_at = int(time.time()) + 3
        s, body = http_json("/api/ziv/schedule", method="POST",
                            body={"fire_at": float(fire_at), "text": "frontend corner turn"},
                            port=port)
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
        kill(proc)


def log_read_tail(path: Path, n: int = 2000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-n:]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ziv relay smoke harness")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--fake", type=float, default=0.05,
                   help="ZIV_FAKE_MODEL_SECONDS (shorten for tests)")
    p.add_argument("--demo", action="store_true",
                   help="attach a WS reader and assert the reminder fire")
    args = p.parse_args(argv)

    if args.demo:
        res = run_demo(port=args.port, fake_seconds=args.fake)
        print(json.dumps(res, ensure_ascii=False))
        if "error" in res:
            return 2
        if not res.get("fired"):
            print("RESULT: reminder fire NOT observed on the wire", file=sys.stderr)
            return 1
        print("RESULT: reminder fired on the wire OK")
        return 0

    log = Path(f"agent/_relay_{args.port}.log")
    proc = run_relay(port=args.port, fake_seconds=args.fake, log=log)
    print(json.dumps({"pid": proc.pid, "port": args.port, "log": str(log)}))
    try:
        if not wait_ready(port=args.port, proc=proc):
            print("RELAY FAILED TO START", file=sys.stderr)
            print(log_read_tail(log), file=sys.stderr)
            return 1
        print("RELAY READY", flush=True)
        try:
            proc.wait()
        except KeyboardInterrupt:
            kill(proc)
    except KeyboardInterrupt:
        kill(proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
