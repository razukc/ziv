#!/usr/bin/env bash
# One-shot root setup for the Ziv demo VM: serve the relay on a permanent
# HTTPS hostname instead of an ephemeral trycloudflare.com quick tunnel.
#
# Hostname: 35-224-56-20.sslip.io  (sslip.io resolves the embedded IP, so no
# domain purchase and no DNS records are needed). The IP is reserved as a
# static address (ziv-demoday-ip), so the name stays valid across reboots.
#
# Run once as root on the VM:  sudo bash vm_setup_caddy.sh
set -euo pipefail

HOST="35-224-56-20.sslip.io"
RELAY="127.0.0.1:8787"

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq caddy

cat >/etc/caddy/Caddyfile <<EOF
# Managed for the Ziv demo. HTTP->HTTPS redirects, the certificate is issued
# and renewed automatically by Caddy via Let's Encrypt (HTTP-01 on :80).
$HOST {
	encode zstd gzip
	reverse_proxy $RELAY
}
EOF

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

systemctl enable caddy >/dev/null 2>&1 || true
systemctl restart caddy
systemctl is-active --quiet caddy

# Give ACME a moment, then confirm the origin answers through the proxy.
for _ in $(seq 1 40); do
	if curl -fsS -o /dev/null "https://$HOST/api/ziv/health"; then
		echo "OK: https://$HOST is serving"
		exit 0
	fi
	sleep 3
done

echo "FAILED: https://$HOST did not answer; see: journalctl -u caddy -n 80" >&2
exit 1
