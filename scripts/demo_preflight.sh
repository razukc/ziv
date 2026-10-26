#!/usr/bin/env bash
# Pre-flight gate for a Ziv demo take: stop before the run if the relay's
# always-on schedule loop cannot fire a reminder.
#
# Start the relay and wake the band page first, then from the repo root:
#   bash scripts/demo_preflight.sh
#
# Against the deployed origin instead of the local relay:
#   ZIV_RELAY=https://35-224-56-20.sslip.io bash scripts/demo_preflight.sh
#
# The probe is not read-only: it schedules one "probe reminder" ~10 s out and
# this script waits for the loop to take it and stamp a new ``last_fire_at``
# (with an idle band, after the reminder's full turn). It refuses before
# scheduling when the loop is not running, no band is attached, or the band is
# not idle, so a failed gate does not leave a reminder to replay over the take.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGIN="${ZIV_RELAY:-http://127.0.0.1:8787}"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
	for candidate in "$ROOT/agent/venv/Scripts/python.exe" "$ROOT/agent/venv/bin/python"; do
		if [ -x "$candidate" ]; then
			PY="$candidate"
			break
		fi
	done
fi
if [ -z "$PY" ]; then
	if command -v python3 >/dev/null 2>&1; then
		PY=python3
	else
		PY=python
	fi
fi
if ! command -v "$PY" >/dev/null 2>&1; then
	echo "preflight: no python interpreter found (set PYTHON=/path/to/python)" >&2
	exit 2
fi

echo "preflight: $ORIGIN (one probe reminder will play on the attached band)" >&2

if ZIV_RELAY="$ORIGIN" "$PY" "$ROOT/scripts/ziv_loop_liveness_probe.py" \
	--wait-for-fire --fire-in 10 --wait-timeout 90; then
	rc=0
else
	rc=$?
fi

case "$rc" in
	0)
		echo "preflight passed - the loop is running and fired the probe reminder" >&2
		;;
	1)
		echo "DEMO BLOCKED: a surface reports the schedule loop stopped." >&2
		echo "Restart the relay (systemctl restart ziv-relay on the VM, or restart ziv_server.py), then re-run." >&2
		;;
	2)
		echo "DEMO BLOCKED: the relay could not be read at $ORIGIN." >&2
		echo "Start it, or point ZIV_RELAY at the origin you are demoing on." >&2
		;;
	3)
		echo "DEMO BLOCKED: the loop says it is running but no fire was proven." >&2
		echo "Attach and wake the band, clear its queue/inbox, resume a paused loop, then re-run." >&2
		;;
	*)
		echo "DEMO BLOCKED: the probe exited $rc." >&2
		;;
esac
exit "$rc"
