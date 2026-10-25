#!/usr/bin/env bash
# Deploy only the PWA client to the demo VM, with the service-worker cache
# check enforced before anything is copied.
#
# Usage:
#   scripts/deploy_ziv_client.sh
#
# Override REMOTE_USER / REMOTE_HOST / REMOTE_DIR for another relay host.
# This script does not touch ziv_data/, .env, or the Python server, and does not
# restart the relay: the static routes read these files per request.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLIENT_DIR="${REPO_ROOT}/agent/ziv_client"
REMOTE_USER="${REMOTE_USER:-kc_razu_gmail_com}"
REMOTE_HOST="${REMOTE_HOST:-35.224.56.20}"
REMOTE_DIR="${REMOTE_DIR:-/home/${REMOTE_USER}/ziv-relay/agent/ziv_client}"
REMOTE_BACKUP_ROOT="${REMOTE_BACKUP_ROOT:-/home/${REMOTE_USER}/ziv-relay/backups}"
LIVE_URL="${LIVE_URL:-https://35-224-56-20.sslip.io}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no)
FILES=()
while IFS= read -r client_file; do
  client_file="${client_file%$'\r'}"  # Windows Python stdout is CRLF
  [ -n "${client_file}" ] || continue
  FILES+=("${client_file}")
done < <(python3 "${SCRIPT_DIR}/ziv_client_cache.py" --print-shell)

cd "${REPO_ROOT}"

echo "===== 1. verify client shell cache ====="
python3 "${SCRIPT_DIR}/ziv_client_cache.py" --check

echo
echo "===== 2. back up the VM client directory ====="
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${REMOTE_BACKUP_ROOT}/client-${STAMP}"
ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" \
  "test -d '${REMOTE_DIR}' && mkdir -p '${BACKUP_DIR}' && cp -a '${REMOTE_DIR}/.' '${BACKUP_DIR}/' && echo 'backed up: ${BACKUP_DIR}'"

echo
echo "===== 3. copy client files ====="
for file in "${FILES[@]}"; do
  scp "${SSH_OPTS[@]}" "${CLIENT_DIR}/${file}" \
    "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/${file}"
done

echo
echo "===== 4. verify remote hashes ====="
for file in "${FILES[@]}"; do
  local_hash="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${CLIENT_DIR}/${file}")"
  remote_hash="$(ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "sha256sum '${REMOTE_DIR}/${file}'" | awk '{print $1}')"
  if [ "${local_hash}" != "${remote_hash}" ]; then
    echo "HASH MISMATCH: ${file}" >&2
    echo "  local:  ${local_hash}" >&2
    echo "  remote: ${remote_hash}" >&2
    exit 1
  fi
  echo "OK ${file} ${local_hash}"
done

echo
echo "client deployed. No relay restart was needed."
echo "live: ${LIVE_URL}/ziv_client/index.html"
echo "backup: ${BACKUP_DIR}"
