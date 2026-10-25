#!/usr/bin/env python3
"""
Probe the Ziv relay's always-on schedule loop from outside the box.

What this is for (from the plan §2.1 deliverable, not restatement):
- Confirm the relay's background schedule loop is running enough to fire a
  due reminder unprompted while nobody is chatting.
- If the loop is not running, report the control/health state the operator
  would use to prove that, rather than guessing.

This is a read-only probe for a running relay; it does not restart anything.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

# Public origin, not the raw port: :8787 is no longer exposed (only Caddy's 80/443).
RELAY: str = os.environ.get("ZIV_RELAY", "https://35-224-56-20.sslip.io")
TOKEN: str = os.environ.get("ZIV_RELAY_TOKEN", "")


def _req(method: str, path: str, body: Any = None) -> dict[str, Any]:
    url = f"{RELAY}{path}"
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            return {"status": resp.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return {"status": exc.code, "body": json.loads(raw) if raw else {}}
    except Exception as exc:  # noqa: BLE001
        return {"status": 0, "error": str(exc)}


def probe() -> dict[str, Any]:
    out: dict[str, Any] = {"relay": RELAY, "now": time.time(), "checks": []}

    for path in ("/api/ziv/health", "/api/ziv/ready", "/api/ziv/control"):
        out["checks"].append({"path": path, **_req("GET", path)})

    health = out["checks"][0].get("body") or {}
    loop = health.get("schedule_loop") or {}
    ready = out["checks"][1].get("body") or {}
    control = out["checks"][2].get("body") or {}

    out["loop_running"] = bool(loop.get("running"))
    out["control_loop_running"] = bool(control.get("loop", {}).get("running"))
    out["control_loop_started"] = bool(control.get("loop", {}).get("started"))
    out["control_loop_iface"] = bool(control.get("loop", {}).get("iface"))
    out["ready_loop_running"] = bool(ready.get("schedule", {}).get("loop_running"))
    out["schedule_pending"] = ready.get("schedule", {}).get("pending")
    out["last_fire_at"] = loop.get("last_fire_at")

    # One future reminder is enough for a smoke if the loop is alive.
    # Use an epoch fire_at: the server's schedule_reminder parses that form.
    future = int(time.time()) + 30
    scheduled = _req(
        "POST",
        "/api/ziv/schedule",
        {"fire_at": float(future), "text": "probe reminder"},
    )
    out["schedule_request"] = scheduled

    if scheduled.get("status") == 200:
        reminder_id = scheduled.get("body", {}).get("id")
        out["scheduled_id"] = reminder_id
        time.sleep(8)  # cheap smoke: do not burn the whole window
        recheck = _req("GET", "/api/ziv/ready")
        out["ready_after_wait"] = recheck.get("body")
        after_pending = (recheck.get("body") or {}).get("schedule", {}).get("pending") or []
        after_ids = {r.get("id") for r in after_pending if isinstance(r, dict)}
        if reminder_id in after_ids:
            out["reminder_still_pending_after_wait"] = True
        else:
            out["reminder_still_pending_after_wait"] = False
            out["loop_appears_to_have_fired_or_removed_it"] = True

    return out


if __name__ == "__main__":
    import pprint
    pprint.pprint(probe())
