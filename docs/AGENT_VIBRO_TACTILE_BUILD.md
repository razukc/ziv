# What I would actually build — a vibro-tactile AI companion for deaf-blind users
*(written for the agent that receives this repo; specific, buildable, honest)*

## What this document is

A concrete build plan from my side. Not a review of the existing plan — I read `HAPTIC_COMPANION_PLAN.md`, `DEVPOST_HAPTIC.md`, the relay seam (`ziv_relay.py`), the store (`ziv_store.py`), the relay v1 server (`ziv_server.py`), the phone PWA, the haptic sequencer (`firmware/haptic_out/`), the QEMU ladder, the timing spec, and the naming protocol. I'm saying what I would do with all of it, in what order, and what I would be honest about in the submission.

## What I'm building on (the good bones — don't throw these away)

- **The interaction invariants.** Six rules from Sense UK's early-years deafblind guidance — cue before content, mark the end, legible waiting, queue-don't-interrupt, universal structure with personal parameters, every transition feelable. These are real design law and they're the strongest thing in the whole project. A device for a population that receives little and distorted information has to hold itself to rules like these. Keep them. They're the reason the project isn't a generic IoT vibro-node with a deafblind caption.
- **The timing single source.** One JSON (`haptic-timing.json`) → generated phone feel-tool + firmware header + Python consumer + tests, all held by a drift guard. That's good engineering and it matters because vibro-braille is all about exact timing. If the phone and the wrist ever play different patterns, the whole thing is untrustworthy. Don't loosen this discipline.
- **The relay seam is real and tested.** `MessageGate` (queue-don't-interrupt, serialized under a lock, bounded queue, loud rejection) + `TurnTimeline` (accepted → processing → playing → closed → error, with processing ticks on a cadence, close before release) + `TurnEvent` vocabulary. Proven in hermetic e2e tests. This is the heart of the relay and it's done well. Build the relay on top of this seam, don't redesign it.
- **The store discipline.** `WearerMemory` (atomic JSON, corrupt-file recovery surfaced in health, never silent swallow) + `MessageInbox` (capped, persistent, peek-then-mark-delivered so a mid-delivery disconnect is redelivery not loss). Good. Keep it.
- **The phone PWA as dev band.** Renders relay turn events through the Vibration API, bootstraps ALL timing from `/api/ziv/timing` (zero hand-copied numbers), has the Omni spike seam (`/inject/audio`, MediaRecorder → base64 → Token Factory Omni → same turn). This is real and it's a good idea. The phone is a legitimate test instrument; be honest that it's a dev band, not the wrist.
- **The QEMU ladder.** Real firmware binary + bench mock bus reused verbatim + HAP timeline lines from the sequencer's own event stream + benchmark-vs-QEMU differ reading the derived fixture. If you get ESP-IDF + QEMU installed, this de-risks the firmware enormously before boards arrive. Worth doing if boards are late.
- **The naming protocol.** Teach-the-mark → M1-M4 measures → rename conversation with option A/B/C. Community holds naming authority. Ships under working title by design. Good, honest, and it's a real thing to do if you have braille readers available.

## What I would change before writing more code

1. **Restate "always-on" honestly.** The tagline "always-on AI companion" is true of the relay, not the device. The device sleeps between events and wakes on button/capture/WiFi. I would say: "an always-on agent with a wearable that wakes on events." Concretely: the relay is the 24/7 presence (heartbeat + scheduled jobs), the device is the on-demand interface. That distinction matters for the track criteria and it's honest.

2. **Make the demo's "conversation" moment explicit about the friend's side.** The demo script shows a friend speaking, the wrist playing braille, the wearer chording "yes, 2 min." But how does the friend know the answer? The plan says "in the MVP the reply reaches the friend as text on their phone (relay push); spoken replies are v2." I would make that visible in the demo and in the submission, not implicit. Either the friend reads text on their phone, or you show the relay log with the friend's side, or you narrate it. Don't let the demo room assume the friend heard a spoken reply — they didn't, because there's no speaker.

3. **Get real about the deadline tension.** 8-week plan, ~6.5 weeks to Oct 30, and the vibro-braille learnability risk is #1 with the naming-validation session in week 6. That's the part of the plan most exposed. I would compress the plan around risk, not around the original 8-week calendar. Specifically: I would not plan the week-6 naming session as if it has two weeks after it to act on results. If the mark fails M1, you need a rename, and a rename conversation + re-validation + re-documentation is a real time sink. Either front-load the braille-reader contact so you know the mark is viable earlier, or design the submission to be robust to a rename decision happening close to deadline (working title, fallback pure-rhythm mark).

4. **Decide what "working prototype" means before the submission.** The relay seam + store + timing + phone PWA + bench firmware + QEMU ladder + Omni spike seam are real. But there is no flashed board, no braille-chord input module, no real WS relay serving a real device, no real FreeRTOS task on ESP32. You have the *design* of a working prototype and substantial *infrastructure* for one, plus a phone that renders the relay's output through vibration. That's a strong Personal AI submission if you frame it honestly as "the relay + timing + output channel are built; the wrist is the dev band; the full device build is scoped and de-risked." It is not "here is a working wrist device." Know which claim you're making.

## The build, phased by risk not by week

I would build in this order, because the risk order is the build order:

### Phase A — prove the output channel is real and the timing is one source (now)

What exists: bench firmware + mock bus (274 checks), timing spec v3 with 7 patterns + 26-letter Grade-1 table, phone feel-tool, QEMU ladder spec with rung-1 app proven on bench (49 checks), drift guard. This is the foundation and it's already done well.

What I'd do:
- Get the bench suite green (it should already be). If it's not, that's the first fix — the bench is the source of truth for "the firmware plays what the spec says."
- Run the QEMU ladder rung 1 if you can get ESP-IDF + QEMU installed. The whole point is that the real binary boots in QEMU with the bench mock bus and plays the derived HAP fixture. If boards are delayed or you're not comfortable with soldering, this rung matters even more — it lets you prove the firmware is right before hardware exists.
- Make the phone feel-tool a first-class test instrument, not a nice-to-have. The drift guard already ties it to the spec. I'd lean into it: every pattern re-feeling on the phone is faster than flashing the board, and it's the same numbers. Use it as the primary timing validation loop.

### Phase B — prove the relay + output loop end to end (with the phone as the device)

What exists: `ziv_server.py` (relay v1, WS transport, `/api/ziv/message`, `/inject/audio` Omni spike, `/api/ziv/timing`, inbox, prefs, health), phone PWA, seam (`ziv_relay.py`).

What I'd do:
- Run the relay v1 server + phone PWA together and prove the full turn journey on the phone: cue → processing ticks → cue-as-content → cells → close → queue release. The existing e2e tests drive this through the in-process ASGI/WS transport; I'd also run it live on the LAN so the phone actually feels it. That's the moment the output channel stops being a design and becomes something you can hold in your hand (well, feel on your phone).
- Decide the fake-model vs live-model story for the demo. The relay's fake model sleeps `ZIV_FAKE_MODEL_SECONDS` so the phone visibly feels the processing ellipsis. For the demo, that's honest if you show it's a fake-model run, or you use a real Token Factory call. I'd probably demo with the fake model for reliability and show the relay log + telemetry as evidence the real path exists. Or demo one real Omni call if you have a key and the spike is green. Don't demo a fake model as if it were the live model — that's the kind of thing that reads wrong in review.

### Phase C — wire the input side
What doesn't exist: braille-chord input module, mic-to-device capture path (the phone has Omni spike, the device doesn't).

What I'd do:
- **Braille-chord input is the hard input problem.** Six keys, debounce, chord decode, text buffer. The plan's fallback (3-button mode: read/stop/repeat) is load-bearing and I'd build toward it explicitly, not as a footnote. If chord input proves too complex for the deadline, the device is still useful input-light (the mic for everything else, the 3-button for control). Don't let chord input become the feature that sinks the deadline.
- **Mic on the device** is the other input problem. The phone has MediaRecorder → `/inject/audio` → Omni. The device needs I2S capture → WAV/Opus frames → WS binary frames. The QEMU ladder rung 4 (audio seam, canned WAV) is the host-testable version of this. I'd build the audio seam behind a vtable so it's host-testable before the I2S driver exists, same discipline as the DRV2605 bus seam.

### Phase D — prove the Omni audio path end to end
What exists: `/inject/audio` on the relay (real, key-guarded, 503 without key, 502 on provider errors, `simulate` stub keeps hermetic path), phone Omni spike (MediaRecorder, posts base64, gets transcript, same turn).

What I'd do:
- Run the Omni spike live if you have a key: record a clip on the phone, post to `/inject/audio`, get the transcript, feel the turn on the phone. That's the week-1 spike gate from the plan, and it's the moment you know the audio-in path works. If it doesn't work (payload format, model availability, provider error), the fallback is relay-side STT — pre-decided, not improvised.
- Be honest in the submission about whether the Omni audio path is proven live or still at the spike/format-question stage. The `DEVPOST_HAPTIC.md` says "Push-to-talk sends the audio to Nemotron-3-Nano-Omni... (one model transcribes *and* understands)." That reads as done. If it's not done live, soften to "the relay has the Omni spike seam; the audio path is being verified in the week-1 spike." Honesty here is a credibility thing, not a modesty thing.

### Phase E — the always-on story
What exists: relay v1 with heartbeat + scheduled jobs story, inbox for messages that arrive with no band attached.

What I'd do:
- Demonstrate one scheduled job firing unprompted: a reminder that buzzes the phone (or would buzz the wrist) at a set time. That's the track's "acts while you're away" beat and it's the easiest always-on proof. Overnight cron log is the evidence. Build this early-ish because it's a track-criteria beat and it's not technically hard — it's a cron job + a stored message + the inbox delivery path.
- Be honest that "always-on" is the relay, not the device. The device sleeps. The relay is the 24/7 presence. Frame it that way.

### Phase F — the naming/validation session, only if you have braille readers

What exists: naming protocol (M1-M4, rename conversation A/B/C, option B mechanically validated by `rename_check.py`), five candidate marks in the spec, phone fallback with spell-any-word box.

What I'd do:
- Only do this if you can actually recruit braille readers (HKNC regional reps, NFB chapters, community orgs). If you can't get readers before the deadline, don't fake the session — frame the submission as "the mark and naming protocol are designed; community naming authority is respected; the submission ships under working title." That's honest and it's the right frame.
- If you do have readers, run the protocol and capture the rename decision honestly. If they rename the device, the submission's working-title framing actually earns its keep. If they validate the mark, great. Either way, don't overclaim.

## The demo I'd actually aim for

A ≤3-minute video that shows:

1. **The gap** — price cards: braille display $4,000, Hable One $349, this device ~$40. One sentence of who it's for. (from the plan §8, honest)
2. **The relay output channel working on the phone** — a message arrives, the phone feels the cue, the processing ticks, the cells, the close. Show the relay log + timing source. This is the moment the output channel is real, not designed. (honest: phone as dev band)
3. **The always-on beat** — a scheduled reminder buzzes unprompted, with the overnight cron log. (honest: relay always-on, device wakes)
4. **The conversation, with the friend's side shown honestly** — a sighted helper speaks (phone mic → `/inject/audio` if live Omni, or stub), the reply plays on the phone as braille, and the friend's side is shown as text on their phone or the relay log — NOT implied to be a spoken reply. (honest: no speaker, friend reads text)
5. **The security story** — device allow-list rejecting an unknown device, mic hardware switch off, the haptic channel shown leaking nothing. (honest: this is a design + relay behavior, demonstrated on the phone/relay)
6. **The stack** — Omni hears, Nano reasons, Nebius runs; cost per turn from telemetry. (honest: two Nemotron models, Token Factory inference, Serverless Jobs for scheduled briefs if you've wired that, otherwise say "scheduled jobs on the relay")
7. **The ask** — "Private by physics." (the best line in the pitch, keep it)

What I would NOT show:
- A flashed wrist device that doesn't exist. If the wrist doesn't exist, show the phone as the dev band and say so.
- A real braille-chord input that doesn't exist. If chord input isn't built, don't demo it — show the 3-button fallback or narrate the input design.
- A spoken reply from the friend. There is no speaker. Don't imply one.
- A live Omni call as if it's reliable when it's a spike with an open format question. If it's not proven, say so.

## What I'd be honest about in the submission

- **The device is a dev band + designed build, not a shipped wrist.** The phone PWA is the visible output channel. The firmware is bench-proven + QEMU-ladder-spec'd + bring-up-checklist'd. The wrist build is scoped (ESP32-S3 N16R8, DRV2605L + 6 LRAs, 6 chord keys, I2S mic, LiPo) and de-risked (QEMU ladder, hardware bring-up stages A-F), but not yet on a board. Frame it as "the relay, timing, and output channel are built; the wrist is the dev band and the hardware build is de-risked."
- **The Omni audio path status.** Proven live on the phone (if it is), or at the spike/format-question stage (if it isn't). Don't write "push-to-talk sends audio to Omni" as if it's a done live path when it's a seam with a real key-guarded endpoint but an open format question.
- **Vibro-braille learnability is the #1 risk and it's unproven at product level.** The plan already says this. I'd keep saying it, loudly, and point to the fallback ladder (attention vocabulary + 30-phrase fixed set, then 3-button mode). The honest claim is "a working prototype of a new channel," not "a proven braille-reading device." No clinical or efficacy claims. This is a feature of the submission, not a weakness — it's the kind of honesty that reads as credible.
- **The "always-on" is the relay.** Device sleeps. Relay is the 24/7 presence.
- **The friend's reply is text-on-phone, not spoken, in the MVP.** No speaker. v2 is TTS.
- **Naming authority is with the community.** Ships under working title. If you haven't run the naming session, say so — "naming protocol designed; community naming authority respected; ships under working title."

## What I would NOT claim

- That vibro-braille on 6 motors is a proven reading method. It's not. Research prototypes exist (V-Braille, HoliBraille, BrailleBand); none shipped. The claim is "temporal braille, Grade 1, as a new channel" + the learnability risk + the fallback.
- That the device is always-on in the sense of a device that's always vibrating or always listening. It's not. The relay is always-on; the device wakes on events; the mic is hardware-gated.
- That the submission is a finished product. It's a working prototype of a new channel, with the relay + timing + output channel built and the input side + wrist build scoped and de-risked.
- That the naming is decided. It's not. Community holds authority.
- That the Omni audio path is a solved, proven, reliable live path if it isn't one. If the week-1 spike hasn't confirmed the payload format and live transcription, the submission should say so and point to the fallback.

## The one thing I'd lean into hardest

**The interaction invariants + the timing single source + the relay seam together are the thing that makes this project real rather than a concept doc with a hardware list.** A generic IoT vibro-node with a deafblind caption is a weak submission. A device whose output channel is governed by six invariants borrowed from the field's own early-years guidance, whose timing is one generated source shared by phone and firmware, whose relay enforces queue-don't-interrupt as a tested seam, and whose mic is hardware-gated with no always-on listening — that's a different thing. That's the submission. Build on that, frame it that way, and be honest about what's built (relay + timing + output channel + phone dev band) vs what's designed-but-not-yet-on-hardware (chord input, device mic, flashed wrist, naming session).

The "private by physics" line is the strongest single claim and it's real — a haptic channel leaks nothing to the room. The interaction invariants are the strongest design claim and they're grounded in published practice, not intuition. The timing single source is the strongest engineering claim and it's real and enforced by a drift guard. Those three are the core. Everything else (Omni audio, chord input, flashed wrist, naming session, spoken replies v2, BLE caregiver bridge) is either a build-to or a scope decision. Get the core honest and visible, and the submission stands on what's actually there.
