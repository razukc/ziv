# Week 1 — Ziv Phone Prototype (Sep 21–Sep 27, 2026)

> The sprint's first week. The Omni spike is the gate: if it works, the "uses NVIDIA model on Nebius" claim is solid; if it fails, the keyless stub
> is the demo path and the gap is documented honestly. The relay + PWA are reachable from the internet by the end of the week, and the always-on
> skeleton's groundwork is laid. README + Devpost draft (Best Apps and Agents, honest scope) are written.
>
> **Track:** Best Apps and Agents. **Model:** NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory. **Demo deliverable:** a working PWA judges can open on
> their own Android phone and feel a message arrive.

---

## Day 1 — Omni spike (the gate)

The phone records a voice clip via MediaRecorder and posts it to `/inject/audio` as `{"audio_b64": "...", "mime": "webm"}`. The relay transcribes it with
Nemotron-3-Nano-Omni on Token Factory (guarded by `NEBIUS_API_KEY`) and runs the same turn/gate/queue path a typed message would take. The phone renders
the turn as vibro-braille through the Vibration API.

**What we verify:**
1. The real TF call works with a real key — the track's core claim ("uses NVIDIA model on Nebius") is solid.
2. If it fails, we know what TF actually returns (502 with the provider's words, or "no transcript", or "unreachable") and we document the gap honestly:
   the `simulate` stub is the demo path; the relay code, the timing, the haptics, the inbox, the memory are all still real.

**The spike's fallback is pre-decided:** if the real TF call fails, ship the keyless stub for the demo and keep the relay code as the real thing — the
submission's "uses NVIDIA model" claim is then "wired and tested with real keys; the demo uses the keyless stub for convenience." Honest either way.

**How the spike runs (the relay-side path that's already wired):**
- The phone's MediaRecorder produces a WebM clip; the PWA converts it to a base64 data URL and posts `{"audio_b64": "...", "mime": "webm"}` to
  `/inject/audio`.
- `agent/ziv_server.py`'s `_transcribe_omni()` builds an OpenAI-compatible chat-completions payload with an `input_audio` content part (base64 data URL),
  model `nemotron-3-nano-3b-preview:omni`, and `Authorization: Bearer {NEBIUS_API_KEY}`, and posts it to `NEBIUS_BASE_URL + "/chat/completions"`.
- The transcript comes back as `resp.json()["choices"][0]["message"]["content"]`, runs through `run_message_turn()` (same path as a typed message), and the
  turn's events are pushed to the WS as haptic frames the phone renders through the Vibration API.

**The keyless stub** (`{"simulate": "<text>"}`) keeps the demo runnable without a key: it skips the TF call and feeds the text straight into `run_message_turn()`.
Swapping between them changes nothing on the phone.

---

## Day 2 — Reachable relay URL

The relay serves the PWA at `/ziv_client/index.html`. We make it reachable from the internet so judges can open it on their own Android phone:

- Start the relay (`python agent/ziv_server.py`, default port 8787), serving the PWA at `http://<host>:8787/ziv_client/index.html`.
- Expose it: a long-running container on Nebius (preferred for the submission's "Run on Nebius" claim) or a simple tunnel (ngrok / Cloudflare tunnel) for the
  demo.
- The phone's PWA connects to the relay over WS; the relay's `/api/ziv/timing` endpoint bootstraps the phone's vibrate patterns (zero hand-copied numbers).

**What we verify:** a judge (or us, on a second device) opens the PWA on Android Chrome, the WS connects, the timing bootstraps, and a message sent to
`/api/ziv/message` plays as vibro-braille on the phone.

---

## Day 3 — Always-on skeleton groundwork

A scheduled relay job that fires an unprompted reminder while nobody is "chatting" — the track's "acts while you're away" beat. Week 3's milestone, but we
lay the groundwork this week:

- The relay's cron/heartbeat endpoint (a simple scheduled task that the health endpoint surfaces).
- The scheduled-job shape (what fires, when, what the wearer feels).
- The cron log shape (what the demo shows as proof).

**What we verify:** the skeleton exists and the health endpoint surfaces the cron state; the full beat (live unprompted buzz) is week 3.

---

## Day 4 — README + Devpost draft (Best Apps and Agents, honest scope)

Write the honest README and the Devpost draft, reflecting the scope:

- What builds this sprint (the relay, the PWA, the timing spec, the inbox + memory, the test suite, the Omni spike, the always-on skeleton).
- What does not build this sprint (the wrist hardware, the braille-chord input, the hardware-gated mic, the wearer-hosted relay, the fine-tuned model,
  the v2 ideas).
- The honest claims table (what the track says vs what this prototype actually does).
- Apache 2.0 LICENSE in the repo (mirrors SkillForge's LICENSE).

**Files written this day:**
- `README.md` — honest scope, repo layout, quick start, tests, the timing spec note, security, LICENSE.
- `DEVPOST_HAPTIC.md` — Devpost draft for Best Apps and Agents: the problem, the solution, the competition, the key technologies, how we built it, the
  Devpost-specific answers (track, what it does, what makes it unique, challenges, technologies), demo video outline, license.

---

## Day 5 — Test suite + drift guard + demo-chain

Run the hermetic suite, the drift guard, and the demo-chain generation. Confirm everything green before the week closes:

- `python -m pytest -q` in `agent/` — hermetic suite (seam, server endpoints, store, timing drift guard, demo-chain generation).
- `python tools/haptic_timing.py` — drift guard (fails on any hand edit to a generated block).
- `python tools/build_ziv_demo.py` — demo-chain generation (one `DEMO_STAGES` generates app, fixture, and docs).
- `python firmware/app/ziv_qemu/run_ziv_tests.py` — the 49-check C bench + boot check (host-portable, needs a C toolchain; exits cleanly on machines
  without one).
- The e2e tier (Playwright) runs the redial test: a real `MessageGate` filled to the cap, a 429, and the client re-sending by itself when the freeing
  close lands on the wire. (`python -m pytest -m e2e` in `agent/` — needs Playwright installed.)

**What we verify:** the whole stack is green before the week closes. Any red is a week-2 start, not a week-1 surprise.

---

## Week 1 done — checklist

- [ ] Omni spike works end to end (voice clip → TF Omni → vibro-braille on the phone), **or** the fallback is documented honestly.
- [ ] The relay + PWA are reachable from the internet and a judge can open the PWA on their Android phone and feel a message arrive.
- [ ] The always-on skeleton's groundwork is laid (cron/heartbeat endpoint, scheduled-job shape, cron log shape).
- [ ] README + Devpost draft (Best Apps and Agents, honest scope) are written.
- [ ] Apache 2.0 LICENSE is in the repo.
- [ ] The test suite + drift guard + demo-chain are green.

---

*Week 1 sets up the demoable bar. Week 2 polishes the conversation demo (friend speaks → phone vibrates → wearer replies). Week 3 builds the always-on
beat. Week 4 prepares the submission (demo video ≤3 min, Devpost final, repo polish, LICENSE, README, test suite green).*
