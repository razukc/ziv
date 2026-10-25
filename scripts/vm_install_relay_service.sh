#!/usr/bin/env bash
# Move the Ziv relay from a nohup background job to a systemd service.
#
# Run once as root on the demo VM, with the unit already copied next to it:
#   sudo bash vm_install_relay_service.sh
#
# It stops the old process that owns :8787, starts the unit, proves the relay
# answers, and then restarts the unit once to prove it recovers on its own.
set -euo pipefail

# Default to the unit sitting beside this script: that is what happens when both
# are copied to the VM as the docs say, and it works for any home directory
# (the deployed unit's User/WorkingDirectory are the demo VM's account; adjust
# them there if you are rebuilding under a different one).
UNIT_SRC="${UNIT_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ziv-relay.service}"
UNIT_DST="/etc/systemd/system/ziv-relay.service"
HEALTH="http://127.0.0.1:8787/api/ziv/health"

[ -f "$UNIT_SRC" ] || { echo "missing $UNIT_SRC" >&2; exit 1; }
install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable ziv-relay >/dev/null

# Retire the old nohup relay. Only kill the PID that owns :8787 and whose
# command line really is the relay, so nothing else is collaterally stopped.
OLD_PID="$(ss -ltnp 2>/dev/null | awk '/:8787/ {print $NF}' | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1)"
if [ -n "${OLD_PID:-}" ] && tr '\0' ' ' <"/proc/$OLD_PID/cmdline" | grep -q "ziv_server.py"; then
	echo "stopping old relay pid $OLD_PID"
	kill "$OLD_PID"
	for _ in $(seq 1 20); do
		kill -0 "$OLD_PID" 2>/dev/null || break
		sleep 0.5
	done
	kill -9 "$OLD_PID" 2>/dev/null || true
fi
for _ in $(seq 1 20); do
	ss -ltn 2>/dev/null | grep -q ':8787' || break
	sleep 0.5
done

wait_healthy() {
	local label="$1"
	for _ in $(seq 1 60); do
		if curl -fsS --max-time 5 "$HEALTH" >/dev/null 2>&1; then
			echo "$label: healthy"
			return 0
		fi
		sleep 1
	done
	echo "$label: FAILED to become healthy" >&2
	journalctl -u ziv-relay -n 40 --no-pager >&2 || true
	return 1
}

systemctl restart ziv-relay
wait_healthy "after install"

systemctl restart ziv-relay
wait_healthy "after restart"

echo "enabled=$(systemctl is-enabled ziv-relay) active=$(systemctl is-active ziv-relay)"
curl -fsS --max-time 5 "$HEALTH" | head -c 200; echo

if pgrep -af "ziv_server.py" | grep -v "systemd\|/usr/bin/" >/dev/null; then
	echo "note: another ziv_server.py process is still running:" >&2
	pgrep -af "ziv_server.py" >&2
fi
