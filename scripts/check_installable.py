"""Ask real Chrome whether a URL is installable, via the DevTools protocol.

The Freebuff preview pane is Electron, which never fires ``beforeinstallprompt``,
so the in-app "Install app" button staying disabled proves nothing either way.
This drives a throwaway headless Chrome profile against the public origin and
reads Chrome's own installability verdict.

Usage: python scripts/check_installable.py https://example.com/page.html
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PORT = 9333


def http_json(path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


async def cdp(url: str) -> dict:
    import websockets

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        next_id = 0

        async def call(method: str, **params):
            nonlocal next_id
            next_id += 1
            await ws.send(json.dumps({"id": next_id, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == next_id:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        await call("Page.enable")
        await call("ServiceWorker.enable")
        try:
            await call("Page.navigate", url=target)
        except Exception:
            pass
        await asyncio.sleep(6)

        manifest = await call("Page.getAppManifest")
        errors = await call("Page.getInstallabilityErrors")

        # The manifest check and the "is it installable" check are separate.
        for _ in range(10):
            if not errors.get("installabilityErrors"):
                break
            if not any(e.get("errorId") == "no-service-worker" for e in errors["installabilityErrors"]):
                break
            await asyncio.sleep(2)
            errors = await call("Page.getInstallabilityErrors")

        return {
            "manifest_url": manifest.get("url"),
            "manifest_errors": manifest.get("errors", []),
            "installability_errors": errors.get("installabilityErrors", []),
        }


target = sys.argv[1] if len(sys.argv) > 1 else "https://35-224-56-20.sslip.io/ziv_client/index.html"
profile = Path(tempfile.mkdtemp(prefix="ziv-install-"))
proc = subprocess.Popen(
    [
        str(CHROME),
        "--headless=new",
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        target,
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

try:
    ws_url = None
    for _ in range(40):
        try:
            targets = http_json("/json/list")
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                ws_url = pages[0]["webSocketDebuggerUrl"]
                break
        except Exception:
            pass
        time.sleep(0.25)

    if not ws_url:
        print(json.dumps({"error": "chrome did not expose a page target"}))
        raise SystemExit(2)

    print(json.dumps(asyncio.run(cdp(ws_url)), indent=2))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(0.5)
    shutil.rmtree(profile, ignore_errors=True)
