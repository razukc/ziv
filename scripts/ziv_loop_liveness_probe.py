#!/usr/bin/env python3
"""
Probe the Ziv relay's always-on schedule loop from outside the box.

What this is for (from the plan §2.1 deliverable, not restatement):
- Confirm the relay's background schedule loop is running enough to fire a
  due reminder unprompted while nobody is chatting.
- If the loop is not running, report the control/health state the operator
  would use to prove that, rather than guessing.

It never restarts anything, but it is not read-only: it schedules one
"probe reminder" about 30 s out on the origin it is pointed at and watches
whether the loop fires it. Run it against the demo origin only when that
reminder playing is fine.

Exit codes, so this can gate a demo run:
  0  all three surfaces (/health, /ready, /control) report the loop running
  1  at least one surface reports the loop NOT running
  2  a surface could not be read, so liveness cannot be proven (fails closed)
  3  (``--wait-for-fire`` only) the loop says it is running, but the probe
     reminder was not proven fired: no band attached, the band was not idle,
     the schedule call was rejected, or no new fire stamp appeared

The default run is a cheap smoke: it schedules the reminder and checks the
loop state. ``--wait-for-fire`` instead waits for the loop to take that
reminder and record a new ``last_fire_at``, and refuses to schedule at all
unless a band is attached and idle (nothing queued, empty inbox) — otherwise
the reminder would queue behind the take and replay over it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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


def probe(*, wait_for_fire: bool = False, fire_in: int = 30,
          wait_timeout: int = 90) -> dict[str, Any]:
    out: dict[str, Any] = {
        "relay": RELAY,
        "now": time.time(),
        "checks": [],
        "wait_for_fire": wait_for_fire,
    }

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
    out["devices"] = health.get("devices")
    out["inbox_pending"] = health.get("inbox_pending")
    out["gate_queue"] = health.get("gate_queue")

    # Refuse before scheduling when the gate would fail anyway: a scheduled
    # reminder with no loop to take it would fire later, possibly mid-demo.
    if wait_for_fire:
        if not (out["loop_running"] and out["ready_loop_running"]
                and out["control_loop_running"]):
            out["skipped"] = "loop_not_running"
            return out
        # Waiting without a band would store the reminder in the inbox, and
        # a backlog would queue it behind the take.
        if not out["devices"]:
            out["skipped"] = "no_device_attached"
            return out
        if out["inbox_pending"] or out["gate_queue"]:
            out["skipped"] = "band_not_idle"
            return out

    # One future reminder is enough for a smoke if the loop is alive.
    # Use an epoch fire_at: the server's schedule_reminder parses that form.
    future = int(time.time()) + fire_in
    scheduled = _req(
        "POST",
        "/api/ziv/schedule",
        {"fire_at": float(future), "text": "probe reminder"},
    )
    out["schedule_request"] = scheduled

    if scheduled.get("status") == 200:
        reminder_id = scheduled.get("body", {}).get("id")
        out["scheduled_id"] = reminder_id
        if wait_for_fire:
            out.update(_wait_for_fire(
                reminder_id, out["last_fire_at"], future + wait_timeout))
            if not out.get("fired"):
                out["cleaned_up"] = _cancel_if_alone(reminder_id)
        else:
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


def _cancel_if_alone(reminder_id: Any) -> bool:
    """Cancel the probe reminder if it is the only one pending.

    There is no per-id cancel route, so this refuses to touch a schedule that
    holds anyone else's reminders. With a clean demo origin the probe's row is
    alone and a failed gate leaves nothing behind to fire later.
    """
    listed = _req("GET", "/api/ziv/schedule")
    rows = (listed.get("body") or {}).get("reminders") or []
    if [r.get("id") for r in rows if isinstance(r, dict)] != [reminder_id]:
        return False
    cleared = _req("DELETE", "/api/ziv/schedule")
    return cleared.get("status") == 200


def _wait_for_fire(reminder_id: Any, last_fire_before: Any,
                   deadline: float) -> dict[str, Any]:
    """Poll until the reminder has left the schedule and a fire stamp moved.

    The stamp is written when the loop's ``fire_due`` returns: with an idle
    band that is after the reminder's turn closes, which is the state the
    gate requires before it schedules. Clearing alone is not proof — a
    reminder claimed with no band attached is stored in the inbox and no
    stamp moves — and the schedule is claimed before playback, so the window
    where it is gone but the stamp has not moved yet is waited out.
    """
    seen: dict[str, Any] = {}
    started = time.time()
    while time.time() < deadline:
        ready = _req("GET", "/api/ziv/ready")
        health = _req("GET", "/api/ziv/health")
        if ready.get("status") == 200 and isinstance(ready.get("body"), dict):
            seen["ready_after_wait"] = ready["body"]
            pending = (ready["body"].get("schedule") or {}).get("pending") or []
            ids = {r.get("id") for r in pending if isinstance(r, dict)}
            seen["reminder_still_pending_after_wait"] = reminder_id in ids
        if health.get("status") == 200 and isinstance(health.get("body"), dict):
            loop = health["body"].get("schedule_loop") or {}
            seen["last_fire_at_after_wait"] = loop.get("last_fire_at")
            seen["loop_running_after_wait"] = bool(loop.get("running"))
        cleared = seen.get("reminder_still_pending_after_wait") is False
        stamp_moved = (seen.get("last_fire_at_after_wait") not in
                       (None, last_fire_before))
        if cleared and stamp_moved:
            seen["reminder_cleared"] = True
            seen["fired"] = True
            seen["waited_s"] = round(time.time() - started, 1)
            return seen
        time.sleep(1)

    seen["reminder_cleared"] = seen.get("reminder_still_pending_after_wait") is False
    seen["fired"] = False
    seen["timed_out"] = not seen["reminder_cleared"]
    seen["misfired"] = seen["reminder_cleared"]
    seen["waited_s"] = round(time.time() - started, 1)
    return seen


def gate(out: dict[str, Any]) -> tuple[int, str]:
    """Map a probe result to an exit code and a one-line reason.

    All three read surfaces are checked, not just /health: consenting
    answers are cheap, and a loop reported stopped by any of them is
    enough to fail the gate. Unreadable surfaces fail closed (2) rather
    than being reported as a stopped loop.
    """
    for check in out["checks"]:
        if check.get("status") != 200:
            detail = check.get("error") or f"status {check.get('status')}"
            return 2, f"cannot read {check['path']} ({detail})"

    stopped = [
        name
        for name, running in (
            ("/api/ziv/health schedule_loop.running", out["loop_running"]),
            ("/api/ziv/ready schedule.loop_running", out["ready_loop_running"]),
            ("/api/ziv/control loop.running", out["control_loop_running"]),
        )
        if not running
    ]
    if stopped:
        return 1, "schedule loop not running per " + ", ".join(stopped)

    if out.get("wait_for_fire"):
        if out.get("skipped") == "no_device_attached":
            return 3, ("no band attached - wake the band page first; a fire "
                       "cannot be proven without one")
        if out.get("skipped") == "band_not_idle":
            return 3, (f"band is not idle ({out.get('gate_queue')} queued, "
                       f"{out.get('inbox_pending')} in the inbox) - clear it "
                       "before the pre-flight")
        scheduled = out.get("schedule_request") or {}
        if scheduled.get("status") != 200:
            detail = scheduled.get("error") or f"status {scheduled.get('status')}"
            return 3, f"could not schedule the probe reminder ({detail})"
        if not out.get("reminder_cleared"):
            tail = (" (the probe reminder was canceled)"
                    if out.get("cleaned_up") else
                    " (it is still pending; clear it before the demo)")
            return 3, ("probe reminder stayed scheduled past its fire time; "
                       "the loop is not taking due work" + tail)
        if not out.get("fired"):
            return 3, ("probe reminder left the schedule without a new fire "
                       "stamp (misfire - did the band stay attached?)")

    return 0, "schedule loop running"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the Ziv relay's always-on schedule loop.")
    parser.add_argument(
        "--wait-for-fire", action="store_true",
        help="wait for the probe reminder to fire and require a new fire "
             "stamp; use this as a pre-demo gate")
    parser.add_argument(
        "--fire-in", type=int, default=30, metavar="SECONDS",
        help="schedule the probe reminder this far ahead (default: 30)")
    parser.add_argument(
        "--wait-timeout", type=int, default=90, metavar="SECONDS",
        help="how long to wait past the due time for the fire stamp "
             "(default: 90)")
    args = parser.parse_args(argv)

    import pprint

    result = probe(wait_for_fire=args.wait_for_fire, fire_in=args.fire_in,
                   wait_timeout=args.wait_timeout)
    pprint.pprint(result)
    code, reason = gate(result)
    print(f"{'PASS' if code == 0 else 'FAIL'}: {reason}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
