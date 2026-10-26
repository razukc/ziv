# Ziv on the demo VM — live PWA link

The GCP VM serves a working client over **HTTPS**. HTTPS is not cosmetic here:
service workers, `wss://`, and the install prompt all require a secure context, so this
is what makes the PWA installable at all. The deployed page matches this checkout's
client, including the busy-sheet compose path, mid-turn queueing, the redial give-up,
and the red dead-end note.

## Live URL

```
https://35-224-56-20.sslip.io
```

| path | what it is |
| --- | --- |
| `/` | redirects to the client page |
| `/ziv_client/index.html` | the phone shell |
| `/ziv_client/manifest.json` | PWA manifest |
| `/ziv_client/ziv_sw.js` | service worker |
| `/api/ziv/health` | relay health (also what the queue badge polls) |
| `/ws` | relay WebSocket |

`sslip.io` resolves the IP embedded in the name, so the hostname needs no domain
purchase and no DNS records. `35.224.56.20` is reserved as a **static** address
(`ziv-demoday-ip`, region `us-central1`), which is what keeps the name valid across
stop/start — an ephemeral IP would silently break it.

## How the front door works

| piece | detail |
| --- | --- |
| TLS terminator | Caddy 2.6.2 (Debian package), config `/etc/caddy/Caddyfile` |
| config | `35-224-56-20.sslip.io { encode zstd gzip; reverse_proxy 127.0.0.1:8787 }` |
| certificate | Let's Encrypt, issued and renewed by Caddy (HTTP-01 on `:80`) |
| HTTP | `308` redirect to HTTPS |
| service | `systemctl enable caddy` — it comes back by itself after a reboot |
| firewall | `ziv-web-80-443` (tcp 80/443, tag `ziv-relay`) is the **only** rule — `ziv-relay-8787` was deleted, so the relay is reachable from outside only through Caddy |
| setup script | [`scripts/vm_setup_caddy.sh`](../scripts/vm_setup_caddy.sh) — one-shot root install |

## Verified on this origin (2026-10-25)

- Cert: `issuer=Let's Encrypt CN=YE1`, `subject=CN=35-224-56-20.sslip.io`,
  valid 25 Oct 2026 → 23 Jan 2027; plain HTTP answers `308` to HTTPS.
- Page, manifest, service worker, both icons, health, `/`, `/favicon.ico`: all `200`
  (`/` and `/favicon.ico` are `307`s to the page).
- In a real browser: `isSecureContext: true`; service worker `activated` and
  **controlling** the page with the `ziv-phone-band-v4` cache; WebSocket `wss://`
  connected; header shows the relay's own `spec v3 · 7 patterns · mark ziv`, badge
  `queue 0/8 · reminders 0/64`.
- A live `POST /api/ziv/message` turn returned `turn_complete` and rendered **12/12**
  braille cells, then returned to the locked screen.
- **Survived a real reboot.** `gcloud compute instances reset` → the public URL went
  `down → 502 → 200` in **19 s** with no manual step: Caddy and `ziv-relay` are both
  `enabled`, the reserved IP stayed on `35.224.56.20`, and the certificate was reused
  from disk. After the reset, a live turn completed and the client reconnected on its
  own (`wss://` connected, service worker controlling, 11 braille cells for the
  11 non-space characters of "systemd turn", then back to locked).
- **Port 8787 is closed to the internet.** After deleting the rule, a direct
  `http://35.224.56.20:8787/api/ziv/health` times out from off-VM, while HTTPS kept
  working; the browser reconnected over `wss://` and a `POST /api/ziv/message` turn
  rendered all 10 cells of "port closed" (spaces produce no cell).
- **Redeployed with the loop and telemetry fixes (2026-10-25 07:25 UTC).**
  `ziv_server.py` is `fda634d2…` on the VM (backups under
  `~/ziv-relay/backups/`); server, relay seam, store and timing module match this
  checkout. At that point the deployed `ziv_client/index.html` was the earlier
  38,201-byte build; it was replaced by the client deploy below. The relay now
  binds its asyncio primitives per event loop and no longer busy-waits while
  paused. Verified live:
  `POST /api/ziv/control/pause` followed by `GET /api/ziv/health` answered in
  **1.25 s** (before the fix the next request never returned), `resume` cleared the
  pause, a `wss://` turn played **9/9** cells (`turn_complete`, 8.9 s), and an
  unprompted reminder fired with `schedule_loop.last_fire_at` set and all 9 cells
  rendered in the attached browser. That last field had never been written: the loop's
  telemetry call omitted the required `retries` argument, the resulting `TypeError`
  was swallowed by the loop's guard, and health reported `last_fire_at: None` on every
  fire. Fixed by passing `retries=0`.
- **Client redeployed with the busy-sheet and settle-timer fix (2026-10-25 10:17 UTC).**
  `ziv_client/index.html` is `ea917300…` (**45,812 bytes**) and `ziv_client/ziv_sw.js`
  is `52b13a41…` with cache **`ziv-phone-band-v4`**; the previous directory is backed
  up under `~/ziv-relay/backups/client-20261025T101732Z/`. No service restart was
  needed — the route reads the files per request. Verified on the public HTTPS origin
  with a fresh browser context: `isSecureContext: true`, WebSocket
  `wss://35-224-56-20.sslip.io/ws` open, service worker controlling with only the v4
  cache. While `taxi waiting` was playing, the device bar exposed **Write a message**;
  the sheet's Send posted `on my way` and got `200 {"queued": true, "queue_len": 1}`,
  the sheet closed with the reply screen still live, the queued text replayed, and the
  turn finished `turn_complete` with `drained: 1` and no page errors. The first live
  attempt exposed a stale `finishReply` settle timer blanking the screen during a
  short queued replay; the timer is now in the cancellable `stageTimers` list, and the
  final deploy above includes that fix.
- Installability checked with **real Chrome** via DevTools
  ([`scripts/check_installable.py`](../scripts/check_installable.py)):
  `manifest_errors: []`, `installability_errors: []`. The in-app preview is Electron,
  which never fires `beforeinstallprompt`, so its disabled "Install app" button is not
  a signal — Chrome's own verdict is.
- **Always-on schedule loop probed from off-VM (2026-10-25 15:24 UTC).**
  [`scripts/ziv_loop_liveness_probe.py`](../scripts/ziv_loop_liveness_probe.py) against
  the public origin: `/api/ziv/health`, `/api/ziv/ready` and `/api/ziv/control` all
  answered `200`; `schedule_loop.running: true` (`poll_s: 1.0`), `/api/ziv/ready`
  reported `schedule.loop_running: true` with `pending: []`, and `/api/ziv/control`
  reported `loop: {started: true, running: true, iface: true}`. The probe is not
  read-only — it schedules one `probe reminder` — and that one (`id 3`) was due at
  `15:24:36Z`; the probe's 8-second recheck still found it pending, as designed. Read
  again after the due time: `pending: []` and `last_fire_at: 2026-10-25T15:24:50.97Z`.
  No client request and no HTTP message caused that turn — health showed **one device
  attached**, so the reminder played to it, which is exactly the always-on path.
  The telemetry rows behind that stamp are `message_turn 10.9 s`
  (`source: scheduled`) and `scheduled_reminder_fired 15.0 s`; the 15 s is
  due-to-completion, not poll lag — `last_fire_at` is written after `fire_due()`
  returns, i.e. once the reminder's turn has closed. Before this run the stamp was
  `07:25:55Z`, 7 h earlier, so the new value is this probe's fire. The probe now
  exits `0` only when all three surfaces agree the loop is running, `1` when one
  reports it stopped, and `2` when a surface cannot be read (fails closed), so a
  demo run can gate on it.
- **Pre-flight gate passed against the live origin (2026-10-26 05:53 UTC).**
  `ZIV_RELAY=https://35-224-56-20.sslip.io bash scripts/demo_preflight.sh` exited
  **`0`** with `PASS: schedule loop running` / `preflight passed - the loop is
  running and fired the probe reminder`. The read-only checks before scheduling
  agreed on all three surfaces (`schedule_loop.running`, `schedule.loop_running`,
  `loop.running` all true) with **one device attached, `gate_queue: 0`,
  `inbox_pending: 0`, `schedule_pending: 0`**, so the probe scheduled its reminder
  instead of refusing. Reminder `id 4` was due `05:53:07Z`; the loop took it and
  wrote `last_fire_at: 2026-10-26T05:53:21.714953Z` after **21.3 s** of waiting
  (previous stamp `2026-10-25T15:24:50.97Z`). Telemetry behind the stamp:
  `message_turn 10.8 s (source: scheduled)` and `scheduled_reminder_fired 14.7 s`
  at the same instant. Afterwards `/api/ziv/ready` reported `pending: []` and
  health still showed `gate_queue: 0`, `inbox_pending: 0`, `devices: 1` — nothing
  left queued to replay over a take. The reminder played on the attached live
  band; the gate is not read-only, which is why it runs before the take and not
  during one.

## What runs on the VM

| thing | where |
| --- | --- |
| relay | systemd unit **`ziv-relay`** → `~/ziv-relay/agent/ziv_server.py`, venv `~/ziv-venv`, port 8787 |
| relay log | `journalctl -u ziv-relay` (the old `~/ziv-relay/ziv-relay.log` is no longer written) |
| Caddy | `systemctl status caddy`, log via `journalctl -u caddy` |
| fallback tunnel | `~/bin/cloudflared` — **not running**: it was a `nohup` job and did not survive the reboot. Its old `trycloudflare.com` name is dead; Caddy is the front door. |
| code deployed from | this repo's `agent/` (server + `ziv_client/`) |

Restart the relay (a service now, so it also comes back by itself after a reboot):

```bash
ssh kc_razu_gmail_com@35.224.56.20
sudo systemctl restart ziv-relay
systemctl status ziv-relay --no-pager
journalctl -u ziv-relay -n 40 --no-pager
```

Install or repair the unit from this repo: copy
[`scripts/ziv-relay.service`](../scripts/ziv-relay.service) and
[`scripts/vm_install_relay_service.sh`](../scripts/vm_install_relay_service.sh) to the VM
and run the script as root. It stops any leftover `nohup` relay, starts the unit, and
restarts it once to prove recovery.

For a **client-only** update, use the guarded deploy:

```bash
scripts/deploy_ziv_client.sh
```

It runs [`scripts/ziv_client_cache.py`](../scripts/ziv_client_cache.py) first, backs up
the remote client directory, copies only the five client files, verifies every remote
SHA-256, and does not restart the relay. If the client shell changed without a
service-worker cache bump, the deploy stops with a fail-closed message; bump and record
the shell with:

```bash
python scripts/ziv_client_cache.py --bump
scripts/deploy_ziv_client.sh
```

The fingerprint and cache name live in
[`scripts/ziv_client_shell_cache.json`](../scripts/ziv_client_shell_cache.json). CI runs
`ziv_client_cache.py --check`, so a stale cache is caught before it reaches this VM. The
same check runs at commit time from [`hooks/pre-commit`](../hooks/pre-commit) with
`--staged`, so it judges the index (exactly what the commit contains) rather than the
working tree — a bump that was run but never staged is blocked too. The digest is
line-ending canonical, so a Windows checkout and a Linux CI run agree on the same shell.

For a **server-only** update, copy just the changed source and restart the unit:

```bash
gcloud compute scp agent/ziv_server.py \
  kc_razu_gmail_com@35.224.56.20:/home/kc_razu_gmail_com/ziv-relay/agent/ziv_server.py
ssh kc_razu_gmail_com@35.224.56.20 'sudo systemctl restart ziv-relay'
```

Do **not** re-run [`scripts/deploy_ziv_relay_demo.sh`](../scripts/deploy_ziv_relay_demo.sh)
casually for a one-file change: it tars the whole `agent/` tree, so it would overwrite
the VM's `ziv_data/` (the wearer's inbox and schedule) and `.env` with the local copies.
It now runs the client cache check before copying, but that does not make it safe for
data-bearing one-file updates.

Reload Caddy after editing its config:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

## Honest limits

- The relay used to be a `nohup` job; it is a systemd unit now (`Restart=always`,
  `RestartSec=2`), so a reboot costs about 20 seconds and nothing manual.
- There is no tunnel any more: `cloudflared` was a `nohup` job, did not survive the last
  reboot, and its old `trycloudflare.com` name is dead. The sslip.io URL is the only
  address to share.
- Nothing outside the VM can reach `8787` any more: the only listener exposed is Caddy
  on 80/443, and it proxies to `127.0.0.1:8787`. Re-running
  [`scripts/deploy_ziv_relay_demo.sh`](../scripts/deploy_ziv_relay_demo.sh) smoke-tests the
  HTTPS origin, not the raw port.
- Nothing is authenticated (`ZIV_RELAY_TOKEN` is unset on the VM), so anyone with the URL
  can post messages or read the inbox. Fine for a judged demo, not for private data.
