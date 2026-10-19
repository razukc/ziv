"""
Run the Ziv relay and serve the real client page from `agent/ziv_client/index.html`
so the preview can open the full demo (not only a static band).

This is the companion to the repo’s own run instructions:
  cd agent && python ziv_server.py
and the relevant JUDGE_REPRO.md “Step 2” LAN note: the phone opens
  http://<lan-ip>:8787/ziv_client/index.html
because `ziv_server.py` serves that page itself — no separate static file server
is needed when the relay is running.

Quick start (preview agent local loopback):
    python agent/serve_for_preview.py
Then open http://127.0.0.1:8787/ziv_client/index.html in the preview tab.

On the same WiFi, swap 127.0.0.1 for this machine’s LAN IPv4 address.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELAY = REPO_ROOT / "agent" / "ziv_server.py"
PORT = int(os.environ.get("ZIV_PORT", "8787"))
FAKE = float(os.environ.get("ZIV_FAKE_MODEL_SECONDS", "0.05"))


def main() -> int:
    if not RELAY.is_file():
        print(f"missing: {RELAY}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["ZIV_PORT"] = str(PORT)
    env["ZIV_FAKE_MODEL_SECONDS"] = str(FAKE)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    print(f"starting relay on :{PORT} (fake model {FAKE}s)", flush=True)
    proc = subprocess.Popen(
        [sys.executable, str(RELAY)],
        cwd=str(RELAY.parent),
        env=env,
        stdin=subprocess.DEVNULL,
    )
    try:
        # Wait until health answers
        import urllib.request
        deadline = time.time() + 45
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                print("relay exited early", file=sys.stderr)
                return 1
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/ziv/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200 and b'"ok"' in resp.read():
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(0.2)
        if not ready:
            print("relay did not become ready in time", file=sys.stderr)
            return 1
        print(f"relay ready: http://127.0.0.1:{PORT}/ziv_client/index.html", flush=True)
        print(f"pid={proc.pid}", flush=True)
        proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(
            __import__("signal").CTRL_BREAK_EVENT if os.name == "nt" else __import__("signal").SIGINT
        )
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            proc.wait(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
