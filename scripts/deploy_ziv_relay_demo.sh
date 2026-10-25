#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GCLOUD_PROJECT="${GCLOUD_PROJECT:-thermal-micron-237921}"
INSTANCE="${INSTANCE:-ziv-demoday-vm}"
ZONE="${ZONE:-us-central1-a}"
REMOTE_USER="${REMOTE_USER:-kc_razu_gmail_com}"
REMOTE_HOST="${REMOTE_HOST:-35.224.56.20}"
REMOTE_USER_HOST="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE="ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no ${REMOTE_USER_HOST}"

echo "PROJECT=${GCLOUD_PROJECT}  INSTANCE=${INSTANCE}  ZONE=${ZONE}"
echo "REMOTE_USER=${REMOTE_USER}  REMOTE_HOST=${REMOTE_HOST}"
echo

# ---------- 0. Fail closed before touching the VM ----------
# A shell change without a service-worker cache bump would deploy a new page
# that installed PWAs never see. Refuse before starting the VM or copying data.
echo "===== 0. verify client shell cache ====="
python3 "${SCRIPT_DIR}/ziv_client_cache.py" --check
echo

# ---------- 1. Bring the VM up ----------
echo "===== 1. start VM ====="
gcloud compute instances start "${INSTANCE}" --zone="${ZONE}" --project="${GCLOUD_PROJECT}" --quiet 2>&1 | tail -4
echo "start exit: ${PIPESTATUS[0]}"

# ---------- 2. Poll until RUNNING + ext IP + SSH responds ----------
echo
echo "===== 2. wait-for-ready ====="
MAX_WAIT=300
INTERVAL=5
ELAPSED=0
SSH_READY=false
while [ "${ELAPSED}" -lt "${MAX_WAIT}" ]; do
  STATUS=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${GCLOUD_PROJECT}" --format="value(status)" 2>/dev/null | tr -d '[:space:]')
  EXT_IP=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${GCLOUD_PROJECT}" --format="value(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null | tr -d '[:space:]')

  SSH_OK=false
  if ${SSH_READY}; then
    SSH_OK=true
  else
    if ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no "${REMOTE_USER}@${EXT_IP}" "echo OK" 2>/dev/null | grep -q OK; then
      SSH_OK=true
      SSH_READY=true
    fi
  fi

  echo "t=${ELAPSED}s status=${STATUS} ext_ip=${EXT_IP} ssh=${SSH_OK}"
  if [ "${STATUS}" = "RUNNING" ] && [ -n "${EXT_IP}" ] && ${SSH_READY}; then
    echo "READY: ext_ip=${EXT_IP}"
    break
  fi

  sleep "${INTERVAL}"
  ELAPSED=$((ELAPSED + INTERVAL))
done
if [ "${STATUS}" != "RUNNING" ] || [ -z "${EXT_IP}" ] || ! ${SSH_READY}; then
  echo "NOT READY after ${MAX_WAIT}s: status=${STATUS} ext_ip=${EXT_IP} ssh=${SSH_READY}"
  exit 1
fi
REMOTE_HOST="${EXT_IP}"
REMOTE_USER_HOST="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE="ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no ${REMOTE_USER_HOST}"

# ---------- 3. Install build tools + make a user venv ----------
echo
echo "===== 3. install system packages (sudo) + create user venv ====="
${REMOTE} bash - <<'REMOTE_EOF'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if sudo -n true 2>/dev/null; then
  echo "sudo available — installing system packages"
  sudo apt-get update -qq >/dev/null 2>&1 || true
  sudo apt-get install -y -qq build-essential python3-venv python3-pip >/dev/null 2>&1 || true
  echo "system packages: installed"
else
  echo "no passwordless sudo — using user-space python3 + venv only"
fi

HOME_DIR="$(eval echo ~$(whoami))"
VENV_DIR="${HOME_DIR}/ziv-venv"
if [ -d "${VENV_DIR}" ]; then
  echo "venv already exists at ${VENV_DIR}"
else
  python3 -m venv "${VENV_DIR}"
  echo "venv created at ${VENV_DIR}"
fi
"${VENV_DIR}/bin/python3" --version 2>&1 || true
REMOTE_EOF
echo "install/venv exit: ${PIPESTATUS[0]}"

# ---------- 4. Deploy code ----------
echo
echo "===== 4. deploy code to VM ====="
${REMOTE} bash - <<'REMOTE_EOF'
set -euo pipefail
HOME_DIR="$(eval echo ~$(whoami))"
DEPLOY_DIR="${HOME_DIR}/ziv-relay"
mkdir -p "${DEPLOY_DIR}"
echo "deploy dir: ${DEPLOY_DIR}"
REMOTE_EOF
echo "mkdir deploy dir exit: ${PIPESTATUS[0]}"

# Push the agent tree (Python source + client PWA) as a tar stream.
RELAY_TREE="agent"
if [ -d "${RELAY_TREE}" ]; then
  echo "pushing ${RELAY_TREE} -> ${REMOTE_USER_HOST}:~/ziv-relay/"
  tar cz -C "$(dirname "${RELAY_TREE}")" "$(basename "${RELAY_TREE}")" | \
    ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
        "${REMOTE_USER_HOST}" \
        "tar xz -C ~/ziv-relay 2>/dev/null || (mkdir -p ~/ziv-relay && tar xz -C ~/ziv-relay)"
  echo "push exit: ${PIPESTATUS[0]}"
else
  echo "WARNING: local tree '${RELAY_TREE}' not found; skipping push"
fi

# ---------- 5. Install Python deps into the user venv ----------
echo
echo "===== 5. pip install relay deps into user venv ====="
${REMOTE} bash - <<'REMOTE_EOF'
set -euo pipefail
HOME_DIR="$(eval echo ~$(whoami))"
VENV_DIR="${HOME_DIR}/ziv-venv"
SRC_DIR="${HOME_DIR}/ziv-relay/agent"

if [ ! -d "${SRC_DIR}" ]; then
  echo "ERROR: agent source not found at ${SRC_DIR}"
  exit 1
fi

echo "installing deps into ${VENV_DIR}"
"${VENV_DIR}/bin/python3" -m pip install --quiet --upgrade pip 2>/dev/null || true
"${VENV_DIR}/bin/python3" -m pip install --quiet starlette uvicorn[standard] 2>&1 | tail -5 || true
echo "pip install exit: $?"
"${VENV_DIR}/bin/python3" -c "import starlette, uvicorn; print('starlette', starlette.__version__, 'uvicorn', uvicorn.__version__)" 2>&1 || true
REMOTE_EOF
echo "pip deps exit: ${PIPESTATUS[0]}"

# ---------- 6. Start the relay on port 8787 ----------
echo
echo "===== 6. start Ziv relay ====="
${REMOTE} bash - <<'REMOTE_EOF'
set -euo pipefail
HOME_DIR="$(eval echo ~$(whoami))"
VENV_DIR="${HOME_DIR}/ziv-venv"
DEPLOY_DIR="${HOME_DIR}/ziv-relay"
SRC_DIR="${DEPLOY_DIR}/agent"
PORT=8787
LOG="${DEPLOY_DIR}/ziv-relay.log"

if [ ! -f "${SRC_DIR}/ziv_server.py" ]; then
  echo "ERROR: ziv_server.py not found at ${SRC_DIR}/ziv_server.py"
  exit 1
fi

# The relay runs as the `ziv-relay` systemd unit on this VM. Restart it through
# systemd when the unit exists, otherwise fall back to a plain nohup launch —
# never kill the unit's process and start a second one, or the two race for the
# port and systemd keeps restarting into a bind failure.
if systemctl cat ziv-relay >/dev/null 2>&1; then
  echo "restarting systemd unit ziv-relay"
  sudo systemctl restart ziv-relay
  sleep 1
else
  # Kill a stray relay if one is already bound on 8787.
  PID=$(ss -ltnp 2>/dev/null | grep -E ":${PORT}[[:space:]]" | awk '{print $6}' | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1)
  if [ -n "${PID}" ]; then
    echo "killing existing listener pid=${PID} on port ${PORT}"
    sudo kill "${PID}" 2>/dev/null || kill "${PID}" 2>/dev/null || true
    sleep 1
  fi

  export ZIV_PORT="${PORT}"
  echo "starting ziv_server.py on port ${PORT} (log: ${LOG})"
  nohup "${VENV_DIR}/bin/python3" "${SRC_DIR}/ziv_server.py" >> "${LOG}" 2>&1 &
  echo "launched pid=$!"
fi

for i in $(seq 1 20); do
  if ss -ltn 2>/dev/null | grep -qE ":${PORT}[[:space:]]"; then
    echo "relay bound on port ${PORT} after ~$i checks"
    break
  fi
  sleep 0.5
done

if ss -ltn 2>/dev/null | grep -qE ":${PORT}[[:space:]]"; then
  echo "OK: port ${PORT} is listening"
  echo "log tail:"
  tail -n 5 "${LOG}" 2>/dev/null || true
else
  echo "WARN: port ${PORT} not listening yet; log:"
  tail -n 20 "${LOG}" 2>/dev/null || true
fi
REMOTE_EOF
echo "start relay exit: ${PIPESTATUS[0]}"

# ---------- 7. Smoke-test from the public IP ----------
echo
echo "===== 7. smoke test from public IP ====="
PUBLIC_URL="${PUBLIC_URL:-https://${REMOTE_HOST//./-}.sslip.io}"
echo "target: ${PUBLIC_URL}"
echo
echo "--- GET /ziv_client/index.html ---"
curl -sS -m 20 -o /dev/null -w "HTTP %{http_code} size=%{size_download}\n" "${PUBLIC_URL}/ziv_client/index.html" || echo "curl failed"
echo
echo "--- GET /api/ziv/health ---"
curl -sS -m 20 "${PUBLIC_URL}/api/ziv/health" || echo "curl failed"
echo
echo "--- POST schedule a 60s reminder ---"
REMINDER_PAYLOAD='{"fire_at":'$(( $(date +%s) + 60 )).',"text":"demo beat"}'
echo "${REMINDER_PAYLOAD}" | curl -sS -m 20 -X POST -H "Content-Type: application/json" -d @- "${PUBLIC_URL}/api/ziv/schedule" || echo "curl failed"
echo
echo "===== DONE ====="
echo "Public relay URL: ${PUBLIC_URL}"
echo "PWA page:         ${PUBLIC_URL}/ziv_client/index.html"
echo "Logs on VM:       sudo journalctl -u ziv-relay   (unit) or ~/ziv-relay/ziv-relay.log (nohup fallback)"
