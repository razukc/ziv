#!/usr/bin/env python3
from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORT = int(os.environ.get("ZIV_PORT") or "8791")
BASE = f"http://127.0.0.1:{PORT}"

def http_get(path: str, timeout: float = 5.0) -> tuple[int | None, str]:
    try:
        req = Request(f"{BASE}{path}")
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as exc:
        return None, str(exc)

def http_post(path: str, data: bytes, content_type: str = "application/json", timeout: float = 5.0) -> tuple[int | None, str]:
    try:
        req = Request(f"{BASE}{path}", data=data, headers={"Content-Type": content_type})
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as exc:
        return None, str(exc)

async def read_ws(timeout_s: float = 12.0, max_frames: int = 20) -> list[str]:
    try:
        import websockets
    except Exception as exc:
        return [f"(websockets unavailable: {exc})"]
    ws_url = BASE.replace("http", "ws", 1) + "/ws"
    frames: list[str] = []
    try:
        async with websockets.connect(ws_url) as ws:
            end = time.time() + timeout_s
            while time.time() < end and len(frames) < max_frames:
                msg = await asyncio.wait_for(ws.recv(), timeout=min(0.5, end - time.time()))
                frames.append(msg)
                if "end-of-message" in msg:
                    break
    except asyncio.TimeoutError:
        pass
    except Exception as exc:
        return [f"ws error: {exc}"]
    return frames

def main() -> int:
    env = dict(os.environ)
    env["ZIV_FAKE_MODEL_SECONDS"] = "0.4"
    env["ZIV_PORT"] = str(PORT)

    proc = subprocess.Popen(
        [sys.executable, "ziv_server.py"],
        cwd=str(HERE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.time() + 20.0
    ready = False
    while time.time() < deadline:
        status, _ = http_get("/api/ziv/health")
        if status == 200:
            ready = True
            break
        time.sleep(0.4)

    if not ready:
        print("RELAY DID NOT BECOME READY")
        try:
            out = proc.stdout.read()
            print("relay stdout tail:", out[-1500:] if out else "(empty)")
        except Exception as exc:
            print("read failed:", exc)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        return 2

    try:
        print("mode: cwd=agent, start=python ziv_server.py, ZIV_PORT=", PORT)
        print("health:", http_get("/api/ziv/health")[0])
        print("page:", http_get("/ziv_client/index.html")[0])
        print("schedule(get):", http_get("/api/ziv/schedule")[0])

        fire_at = int(time.time()) + 4
        status, body = http_post(
            "/api/ziv/schedule",
            json.dumps({"fire_at": fire_at, "text": "pills"}).encode("utf-8"),
        )
        print("schedule(post):", status)
        if status == 200:
            print(json.dumps(json.loads(body), indent=2)[:800])
        # Keep the foreground WS attached through the reminder window, then shut.
        ws_frames = asyncio.run(read_ws(timeout_s=12.0, max_frames=20))
        print("ws frames:", len(ws_frames))
        for frame in ws_frames:
            print(type(frame), frame[:260])
        if ws_frames and "end-of-message" not in ws_frames[-1]:
            print("CAVEAT: foreground ws did not capture end-of-message before we stopped reading; reminder may still have fired after close")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return 0

if __name__ == "__main__":
    sys.exit(main())
