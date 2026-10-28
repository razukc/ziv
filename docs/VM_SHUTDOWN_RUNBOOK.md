# Demo VM shutdown runbook — post-judging

The demo VM **stays running through the judging period**. This is the dated
sequence for stopping it, snapshotting it, and deleting it after judging ends.

## Decision (2026-10-28)

The GCP cost question is settled: keep `ziv-demoday-vm` running. Dismiss the
Idle VM recommendation; do not stop before the judging period ends. The Nebius
account has enough credit for the demo's model calls, so the model path is not
a reason to stop either. The next scheduled action is the **December 16** stop
and snapshot below.

Do not run the stop step early: the live PWA URL is the working-demo link on the
submitted Devpost page, and the [official rules](https://nebiusglobalaihackathon.devpost.com/rules)
require the project to stay available, free of charge, for testing and
evaluation until the Judging Period ends.

## Calendar (Pacific Time)

| Date | Action |
|---|---|
| **Fri, Oct 30, 2026, 10:00 AM** | Submissions close. The project is already submitted. |
| **Tue, Dec 1, 2026, 9:00 AM** | Judging starts. The VM must be up and the live demo must answer. |
| **Tue, Dec 15, 2026, 12:00 PM** | Judging ends. This is the **earliest safe stop time**. |
| **Wed, Dec 16, 2026** | Recommended stop + snapshot day. Keep the disk and static IP. |
| **Mon, Jan 11, 2027, 12:00 PM** | Winners announced **on or around** this date. After any follow-up verification, delete the VM, disk, and static IP. Keep the snapshot. |

Source: [Nebius x NVIDIA Global AI Hackathon — Official Rules](https://nebiusglobalaihackathon.devpost.com/rules).
The rules state the project must remain available without restriction until the
Judging Period ends.

## Why the idle recommendation is expected

Google Cloud's Idle VM Recommender flags near-zero CPU. That is normal for this
relay: it waits on HTTP and WebSocket traffic, and the schedule loop polls once
per second. Low CPU is not evidence that the demo is unused.

The recommendation is financially accurate, but the safe action is to dismiss
it until **December 16**. Stopping before then saves a small monthly compute
charge and creates a dead link during judging.

## VM identity

Confirmed against the project on 2026-10-28:

| Property | Value |
|---|---|
| Project | `thermal-micron-237921` |
| Instance | `ziv-demoday-vm` |
| Zone | `us-central1-a` |
| Machine type | `e2-small` |
| Boot disk | `ziv-demoday-vm` (20 GB, `pd-balanced`) |
| Static IP | `ziv-demoday-ip` → `35.224.56.20` |
| Public URL | `https://35-224-56-20.sslip.io` |
| Services | `ziv-relay` and `caddy`, both systemd-enabled |
| Public ports | 80/443 only; port 8787 is not exposed |

Set these once in the shell. Keep using the explicit project flag so a different
active `gcloud` project cannot be changed by accident.

```bash
PROJECT=thermal-micron-237921
ZONE=us-central1-a
REGION=us-central1
INSTANCE=ziv-demoday-vm
DISK=ziv-demoday-vm
IP_NAME=ziv-demoday-ip
SNAPSHOT=ziv-demoday-vm-postjudging-20261216
```

The snapshot name is a label, not a scheduled action. Change the date suffix if
you run this on a different day; the commands do not depend on the name.

## 1. Preflight — confirm this is the right VM

Do this on **December 16**, after the judging period has closed.

```bash
gcloud compute instances describe "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE" \
  --format='yaml(name,status,machineType.basename(),disks[].source.basename(),networkInterfaces[].accessConfigs[].natIP,creationTimestamp)'
```

Expected:

- `name: ziv-demoday-vm`
- `status: RUNNING`
- boot disk `ziv-demoday-vm`
- `natIP: 35.224.56.20`

Confirm the live origin is still the VM and not a cached or alternate service:

```bash
curl -fsS https://35-224-56-20.sslip.io/api/ziv/ready
curl -fsS https://35-224-56-20.sslip.io/api/ziv/health
```

Both should answer `200`. The ready payload should show
`schedule.loop_running: true`.

## 2. Stop the VM

```bash
gcloud compute instances stop "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE"
```

Verify the stopped state:

```bash
gcloud compute instances describe "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE" \
  --format='value(status)'
```

Expected: `TERMINATED` (the console calls this **Stopped**).

The public URL will now fail. That is expected. The static IP, boot disk,
certificate, `.env`, and `ziv_data/` remain on disk.

## 3. Snapshot the stopped boot disk

Snapshot from the stopped disk, not the running VM, so the archive is a clean
post-judging state.

```bash
gcloud compute disks snapshot "$DISK" \
  --project="$PROJECT" --zone="$ZONE" \
  --snapshot-names="$SNAPSHOT" \
  --description="Ziv post-judging archive after Dec 15 2026 judging; includes relay, Caddy, .env, and ziv_data"
```

This copies the whole boot disk. The snapshot contains the relay's `.env` and
the demo store, so treat it as sensitive. Do not share it or make it public.

Verify the snapshot reached `READY`:

```bash
gcloud compute snapshots describe "$SNAPSHOT" \
  --project="$PROJECT" \
  --format='yaml(name,status,diskSizeGb,sourceDisk,creationTimestamp)'
```

Expected: `status: READY` and `diskSizeGb: '20'`.

List it if needed:

```bash
gcloud compute snapshots list \
  --project="$PROJECT" \
  --filter="name=$SNAPSHOT"
```

Do not delete the VM or disk until this snapshot is `READY`.

## 4. Delete the VM

Do this **after January 11, 2027**, once the winners have been announced and any
organizer follow-up is finished. Keeping the disk through the announcement is
cheap and leaves room to restart the demo if needed.

### Retire completely (snapshot is the archive)

This deletes the instance and its boot disk in one step:

```bash
gcloud compute instances delete "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE" \
  --delete-disks=all --quiet
```

### Keep the disk for a possible rebuild

If you are not ready to retire the disk, keep it:

```bash
gcloud compute instances delete "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE" \
  --keep-disks=boot --quiet
```

Then delete the disk later, after the snapshot has been verified:

```bash
gcloud compute disks delete "$DISK" \
  --project="$PROJECT" --zone="$ZONE" --quiet
```

## 5. Release the static IP

The static IP stays reserved and billable after the VM is stopped or deleted.
Release it only when you are finished with the URL. Releasing it makes
`35-224-56-20.sslip.io` stop resolving; the Devpost page still points at that
name.

```bash
gcloud compute addresses describe "$IP_NAME" \
  --project="$PROJECT" --region="$REGION" \
  --format='yaml(name,address,status)'

gcloud compute addresses delete "$IP_NAME" \
  --project="$PROJECT" --region="$REGION" --quiet
```

Expected before deletion: `address: 35.224.56.20`. After the VM is gone the
status changes from `IN_USE` to `RESERVED`; it remains billable until deleted.

## 6. Optional cleanup — firewall rule

The app's only public ingress rule is `ziv-web-80-443` (tcp 80/443, tag
`ziv-relay`). It costs nothing to leave it, but it is safe to delete after the
VM is gone. The project also has the default SSH/RDP/ICMP rules; leave those
alone here — `default-allow-ssh` is how the VM is administered.

```bash
gcloud compute firewall-rules delete ziv-web-80-443 \
  --project="$PROJECT" --quiet
```

Do not delete it before the VM is retired; it is the front door for Caddy.

## If you need the demo back

Start the VM. The reserved static IP keeps the hostname valid, and both
services are enabled, so they start automatically; no manual service start is
normally needed.

```bash
gcloud compute instances start "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE"
```

Wait for `200` on the public origin, then verify the loop:

```bash
until curl -fsS https://35-224-56-20.sslip.io/api/ziv/ready; do sleep 5; done
curl -fsS https://35-224-56-20.sslip.io/api/ziv/health
```

The previous reboot recovered in about 19 seconds. If the VM has been stopped
past the certificate's January 23, 2027 expiry, Caddy renews it on start; keep
the static IP attached until that succeeds.

## Cost notes

- **While running:** the `e2-small` compute charge plus the 20 GB disk and the
  external IPv4 address. The console's recommendation estimated the combined
  saving at about `$11.27/month`; treat that as an estimate, not a bill.
- **While stopped:** compute stops; the 20 GB disk and the reserved static IP
  remain billable. That is the cheap state to sit in after December 16.
- **After deletion:** the VM and disk charges stop. The snapshot remains as
  small snapshot-storage cost until you delete it.
- **Do not delete the snapshot** until you are sure you no longer need the
  relay's `.env`, `ziv_data/`, or Caddy configuration. It is the only archive
  of the deployed state.

## Order of operations

1. **Through Dec 15, 12:00 PM PT:** leave the VM RUNNING. Dismiss the idle
   recommendation.
2. **Dec 16:** stop, snapshot, verify `READY`; keep the disk and static IP.
3. **Jan 11, 2027 onward:** after winners/follow-up, delete the VM and disk.
4. **After the URL is retired:** release the static IP and optionally delete
   the firewall rule.
