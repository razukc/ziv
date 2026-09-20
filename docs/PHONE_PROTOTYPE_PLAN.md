# 4-Week Build Plan — Ziv Phone Prototype (Nebius Global AI Hackathon, Best Apps and Agents track)

> **Scope:** a phone-based prototype of an always-on AI companion for deaf-blind users, demoed on Android Chrome via the Vibration API. The wrist
> hardware (ESP32 + DRV2605L + 6 LRA motors, a ~$40 BOM) is the **next revision**, not this submission. This doc records the 4-week sprint scope,
> the schedule, the week-1 detail, and the honest-claims table. The full 8-week wrist plan lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md).
>
> **Track:** Best Apps and Agents. **Model:** NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory (the hearing layer). **Demo deliverable:** a working
> PWA judges can open on their own Android phone and feel a message arrive. **Deadline:** Oct 30, 2026 @ 1:00pm EDT. **Credits:** $25 Token Factory via
> promo code `NEBIUS-DEVPOST-GLOBAL26` + another $25 via the Nebius Builders Program (also Tavily, Academy, office hours).

---

## 1. Scope statement — what this sprint builds, and what it does not

### Builds this sprint (the demoable bar)

- **The relay** — FastAPI server that owns the interaction loop: WS transport, the message gate (queue-don't-interrupt), the turn timeline, the
  generated timing module, the inbox, the wearer memory, the health endpoint, and the PWA it serves. This is `agent/ziv_server.py`, already real
  and passing its hermetic tests.
- **The phone PWA** — `agent/ziv_client/index.html`, a small Android-Chrome PWA that connects to the relay over WS and renders the relay's turns
  through the Vibration API, using the *same* timing derivation as the firmware (zero hand-copied numbers). The mic records via MediaRecorder and the
  relay transcribes with Nemotron-3-Nano-Omni on Token Factory (`/inject/audio`, the Omni spike). A keyless stub (`{"simulate": "..."}`) keeps the
  demo runnable without a key.
- **The timing spec** — `docs/haptic-timing.json`, the single source of truth; seven consumers are generated from it (firmware header, feel-tool JS,
  the ladder doc's demo table, …). The drift guard (`tools/haptic_timing.py`) fails on any hand edit to a generated block.
- **The inbox + memory** — `agent/ziv_store.py`: a persistent capped inbox (messages that arrive with no band attached are stored, not dropped) and
  per-wearer memory (the playback-pace preference, clamped into the spec envelope). Survives restarts; gitignored.
- **The test suite** — 8 hermetic tests in `agent/tests/` covering the seam (gate, timeline, thread safety), the server endpoints, the store, the
  timing drift guard, and the demo-chain generation. The e2e tier includes the redial test: a real `MessageGate` filled to the cap, a 429, and the
  client re-sending by itself when the freeing close lands on the wire.
- **The Omni spike** — week 1: one voice clip from the phone → Token Factory Omni → reply text → vibro-braille pattern on the phone's vibration motor,
  end to end. If it works, the "uses NVIDIA model on Nebius" claim is solid. If it fails, the keyless stub is the demo path and the relay code is still
  the real thing.
- **The always-on skeleton** — week 3: a scheduled relay job that fires an unprompted reminder while nobody is "chatting"; the always-on demo beat,
  proven by a cron log.

### Does not build this sprint (the next revision)

- The wrist hardware — ESP32-S3 N16R8 + DRV2605L + 6 LRA motors + 6 tactile keys + LiPo, a ~$40 BOM. The phone is the dev band until boards ship.
- The braille-chord input (6-key braille chord keyboard) — input on the phone is mic + text for this prototype.
- The hardware-gated mic — push-to-talk through the phone mic (software-gated) for this prototype; the ESP32 pin's hardware gating is the next revision.
- The wearer-hosted relay — this prototype runs on our Nebius account; the wearer-hosted relay is the next revision (the honest answer to "data under
  your control").
- The fine-tuned braille-output model (Qwen3-1.7B LoRA distillation) — v2.
- Per-contact people-marks, on-device practice mode — v2, from the early-years practice ideas.

### Honest claims table (for the submission)

| What the track says | What this prototype actually does |
|---|---|
| Assemble, secure, and run your own personal AI system | A phone-based prototype run on our Nebius account; the wearer does not yet self-host or control their data — that is the next revision |
| Always-on personal AI | A scheduled-job skeleton (builds in week 3) that fires unprompted — a demo beat, not a full 24/7 agent |
| Private / data under your control | The haptic output is private by physics (vibration felt only by the wearer); the mic is push-to-talk (not always-on listening). Data resides on our Nebius infrastructure in this prototype |
| Reusable skills / tools/channels of the wearer's choosing | The interaction vocabulary (7 attention patterns + 26-letter alphabet + 5 marks + prefix) is a real skill set, but not a rich skills system; input is mic + text, not a broad tools ecosystem |
| Hardware-gated mic (ESP32 pin) | Push-to-talk through the phone mic (software-gated) — hardware gating is a wrist-device property, built for the next revision |

The strongest track-claimed properties are real: **≥1 NVIDIA open model on Nebius (Token Factory)**, **persistent memory**, and a **working demo the wearer
feels on their phone**.

---

## 2. Schedule (4 weeks, deadline Oct 30)

| Week | Dates (target) | Milestone | Gate |
|---|---|---|---|
| 1 | Sep 21–Sep 27 | **Spike + setup:** Omni spike end to end (voice clip → TF Omni → vibro-braille on the phone), reachable relay URL, always-on skeleton, README + Devpost draft honest | Omni spike works, or fallback decision documented |
| 2 | Sep 28–Oct 4 | **Interaction polish:** the phone feels a real conversation (friend speaks → phone vibrates braille → wearer replies by text/mic), redial flow proven, timing drift guard green, e2e suite green | Two-way conversation demoable on the phone |
| 3 | Oct 5–Oct 11 | **Always-on beat:** the scheduled-job skeleton fires an unprompted reminder while nobody is "chatting"; overnight cron log; memory file on disk shown | Unprompted buzz demoable; cron log proven |
| 4 | Oct 12–Oct 18 | **Submission prep:** demo video (≤3 min), Devpost write-up final, repo polish, LICENSE, README, test suite green, pre-commit on | Submission live before Oct 30; video ≤3 min |

Weeks 5–6 are buffer + polish before the Oct 30 deadline. The wrist hardware (boards, motors, driver) is ordered in week 1 for the next revision but is
not part of this submission.

---

## 3. Week 1 detail (the sprint's first week)

### Day 1 — Omni spike (the gate)

The phone records a voice clip via MediaRecorder and posts it to `/inject/audio` as `{"audio_b64": "...", "mime": "webm"}`. The relay transcribes it with
Nemotron-3-Nano-Omni on Token Factory (guarded by `NEBIUS_API_KEY`) and runs the same turn/gate/queue path a typed message would take. The phone renders
the turn as vibro-braille through the Vibration API.

**What we verify this day:**
1. The real TF call works with a real key — the track's core claim ("uses NVIDIA model on Nebius") is solid.
2. If it fails, we know what TF actually returns (502 with the provider's words, or "no transcript", or "unreachable") and we document the gap honestly:
   the `simulate` stub is the demo path; the relay code, the timing, the haptics, the inbox, the memory are all still real.

**The spike's fallback is pre-decided:** if the real TF call fails, ship the keyless stub for the demo and keep the relay code as the real thing — the
submission's "uses NVIDIA model" claim is then "wired and tested with real keys; the demo uses the keyless stub for convenience." Honest either way.

### Day 2 — Reachable relay URL

The relay serves the PWA at `/ziv_client/index.html`. We make it reachable from the internet so judges can open it on their own Android phone. Options:
a long-running container on Nebius, or a simple tunnel (ngrok/Cloudflare tunnel) for the demo. The phone PWA connects to the relay over WS; the relay's
`/api/ziv/timing` endpoint bootstraps the phone's vibrate patterns (zero hand-copied numbers).

### Day 3 — Always-on skeleton

A scheduled relay job that fires an unprompted reminder while nobody is "chatting" — a simple cron/heartbeat that the demo shows as a live buzz. The
always-on story is the track's "acts while you're away" beat; the skeleton is week 3's milestone but we lay the groundwork (the relay's cron/heartbeat
endpoint, the scheduled-job shape) this week.

### Day 4 — README + Devpost draft

Write the honest README and the Devpost draft (Best Apps and Agents track), reflecting the scope above — what builds this sprint, what does not, and the
honest claims table. Apache 2.0 license (mirrors SkillForge's LICENSE).

### Day 5 — Test suite + drift guard

Run the hermetic suite (`python -m pytest -q` in `agent/`), the drift guard (`python tools/haptic_timing.py`), and the demo-chain generation
(`python tools/build_ziv_demo.py`). Confirm everything green before the week closes. The e2e tier (Playwright) runs the redial test: a real
`MessageGate` filled to the cap, a 429, and the client re-sending by itself when the freeing close lands on the wire.

---

## 4. What "done" looks like for this sprint

- The Omni spike works end to end (voice clip → TF Omni → vibro-braille on the phone), or the fallback is documented honestly.
- The relay + PWA are reachable from the internet and a judge can open the PWA on their Android phone and feel a message arrive.
- The always-on skeleton fires an unprompted reminder, proven by a cron log.
- The README and Devpost draft are honest about what this prototype is and isn't (Best Apps and Agents track, phone-based, next revision = wrist hardware).
- The test suite and drift guard are green.
- Apache 2.0 LICENSE is in the repo.
- Submission live before Oct 30, demo video ≤3 min.

---

## 5. Carry-over from SkillForge / earlier work

- Relay patterns (WS transport, bounded retry with backoff, thread-safe telemetry ring, fake-model harness) — carried into `agent/ziv_server.py`.
- Timing spec + drift guard (`tools/haptic_timing.py`, the generated consumer `tools/haptic_timing_gen.py`) — carried, one JSON → phone feel-tool + firmware
  header.
- Hermetic test discipline — 8 tests in `agent/tests/`, the seam-first approach.
- The Omni audio payload format question is the week-1 spike's first question (the plan doc's §11 open question).

---

## 6. Open questions (week 1)

- **Token Factory Omni audio input:** exact payload format (base64 audio in message content vs file upload vs both) and any context-length or audio-length
  limits on the TF endpoint. The vLLM blog confirms the model takes audio; TF's serving format is the spike's first question.
- **Omni pricing/context on TF** (third-party trackers say ~$0.06/$0.24 per 1M tokens, 66k context ⚠ — verify on the TF model page).
- **Reachable URL strategy:** long-running container on Nebius vs a simple tunnel for the demo.
- **Demo video:** storyboard ≤3 min; the conversation demo (friend speaks → phone vibrates → wearer replies) is the spine.

---

*This doc is the sprint's scope + schedule + week-1 detail. The full 8-week wrist plan (hardware, braille-chord input, hardware-gated mic, wearer-hosted
relay) lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) and is the next revision, not this submission.*
