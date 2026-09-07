# Research Note: MimiClaw · Pi Pin · ESP32-S3 "OpenClaw" Boards · Nebius

Research artifact for the Personal AI / always-on-agent direction. Question
under investigation: **what an ESP32-S3 "OpenClaw board" actually supports
(mic, voice, BLE, battery), and whether it can stream audio to a Nebius-backed
brain.** Facts below were captured Sep 5, 2026 from vendor docs, source trees,
and reviews, with sources linked. Claims we could not fully verify are flagged
`⚠` or listed under [Open questions](#open-questions-verify-before-scoping)
rather than asserted.

---

## TL;DR

- **MimiClaw** (`memovai/mimiclaw`, ~5.7k★, MIT) is ESP32-S3 **firmware only** —
  a text agent that talks over Telegram/WebSocket to Claude or an OpenAI-style
  API. Its full source tree contains **no microphone, no I2S, no BLE, and no
  battery code**. You "talk" to it by typing on your phone.
- **Pi Pin** (`liltom-eth/pi-pin`) is a **different project entirely**: an
  open-source *wearable* on a **Raspberry Pi Zero 2 W** + I2S mic + LiPo that
  **records audio locally** and summarizes it later (Whisper + GPT-4 on a
  laptop). No ESP32, no WiFi streaming, no BLE, no speaker, no real-time voice.
  Relevant only as the *pin/wearable form factor* reference.
- Boards sold as "OpenClaw/MimiClaw-compatible ESP32-S3 kits" (Xiaozhi-class
  N16R8 boards) **do physically carry a mic, speaker, and battery connector** —
  MimiClaw ignores all of it.
- **Audio → Nebius is feasible on the silicon, not with stock MimiClaw, and not
  against Nebius's hosted API alone.** Nebius exposes an OpenAI-compatible
  *text* API (chat/completions, embeddings, rerank, responses, images,
  fine-tuning — **no audio transcription, no TTS, no realtime WebSocket** in the
  spec captured Sep 5, 2026).

---

## 1. What MimiClaw actually is

Pure C on ESP-IDF 5.5+, no Linux/Node. An agent loop (ReAct, ≤10 tool
iterations, non-streaming JSON) runs on core 1 while WiFi + channel polling run
on core 0. State lives as markdown/JSONL text files on a 12 MB SPIFFS partition
(`SOUL.md`, `USER.md`, `MEMORY.md`, daily notes, `tg_<id>.jsonl` sessions).
Supports: Telegram + Feishu channels, a text WebSocket JSON gateway on port
18789, serial REPL, WiFi on-boarding captive portal, OTA, cron/heartbeat,
skills loader, and GPIO/file/cron/search tools. Latest merged commit at capture
time: Aug 21, 2026 (Telegram group-message filtering) — **no audio work**.

Hard requirement: **ESP32-S3 with 16 MB flash + 8 MB PSRAM** (12 MB SPIFFS +
2×2 MB OTA slots). Named-compatible boards: Xiaozhi AI board (~$10), LILYGO
T7-S3, FireBeetle 2 ESP32-S3, ESP32-S3-DevKitC-1-N16R8, Seeed XIAO ESP32S3
Plus. Providers: Anthropic (default, `claude-opus-4-5`) or OpenAI
(`/v1/chat/completions` with tool calling), switchable at runtime via CLI/NVS —
**but the base URL is a compile-time constant**, not a config string (see §4).

## 2. What Pi Pin actually is

An "AI Pin you can wear all day" (Mar 2024), modeled on the Humane-Pin concept,
**not** an OpenClaw descendant. BOM: Pi Zero 2 W (~$15), Adafruit SPH0645LM4H
I2S MEMS mic, 3.7 V 600 mAh LiPo + boost/charge module, slide switch, 3D-printed
case. A systemd service runs `record_on_boot.py` (pyaudio) at boot and records
WAV continuously; the "AI" step is offline — copy files to a laptop and run
OpenAI Whisper for STT + GPT-4 to summarize. So: recorder-first wearable with
no streaming, no BLE, no wake word, no voice feedback. It shares no software or
silicon with MimiClaw.

## 3. The "ESP32-S3 OpenClaw board": three capability layers

| Layer | Mic | Speaker / voice | BLE | Battery |
|---|---|---|---|---|
| **ESP32-S3 SoC** | none on-die; 2× I2S + PDM peripherals drive a digital MEMS mic | needs external amp/codec (no DAC) | BT 5 LE + BR/EDR + mesh in silicon | no charger in chip; ADC could read a battery divider |
| **Typical N16R8 chatbot kit** | INMP441 / MSM261-class MEMS mic on board | MAX98357A class-D amp + 3 W-class speaker | radio present (unused by agent firmware) | LiPo connector + charge IC on most kits ⚠ per revision |
| **Under MimiClaw firmware** | **unused** — no I2S driver in tree | **unused** — replies are Telegram text | **disabled** — Bluetooth stack never initialized; WiFi STA/AP only | **unused** — assumes USB power (0.5 W claim), no battery/fuel-gauge code |

The silicon class fully supports voice: the XiaoZhi platform (same SoC, same
N16R8 boards) documents on-device wake word + cloud ASR (~300 ms) + LLM + TTS
at ~1.66 s end-to-end. MimiClaw deliberately took the $5 text path; its own
roadmap lists "Telegram Media Handling — only processes `message.text`, ignores
all media" and "Voice Transcription (Whisper)" as **not implemented**.

## 4. Can it stream audio to a Nebius-backed brain?

**Board side — hardware: yes.** 16 kHz / 16-bit mono ≈ 256 kbps raw (far less
Opus/ADPCM compressed) — trivial for the S3's WiFi. ESP32-S3-BOX, XiaoZhi, and
ESP-ADF already do continuous duplex voice-over-WiFi to cloud ASR on this
hardware.

**Firmware side — no, stock MimiClaw.** Nothing captures or ships audio: LLM
calls are non-streaming HTTPS JSON; the WebSocket gateway (port 18789) speaks
text JSON frames only. Voice support means custom C: an I2S capture task →
encode → binary frames over the existing WS gateway (or multipart upload), then
inject recognized text into the inbound queue so the existing agent loop
responds.

**Brain side — a small patch + an extra speech service.**

- Pointing MimiClaw's `openai` provider at Nebius needs an edit, not config:
  `MIMI_OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"` is a
  macro in `mimi_config.h`, and the proxy path hardcodes the `api.openai.com`
  host. Change both to `api.studio.nebius.com` / `api.tokenfactory.nebius.com`
  (Bearer key; model IDs like `meta-llama/Llama-3.3-70B-Instruct`).
- The bigger gap is Nebius itself. The hosted API spec
  (`api.studio.nebius.com/openapi.json`, version `20260903-6fd241231`, fetched
  Sep 5, 2026) exposes: `/v1/completions`, `/v1/chat/completions`,
  `/v1/embeddings`, `/v1/rerank`, `/v1/responses`, `/v1/models`, `/v1/files`,
  `/v1/images/generations`, `/v1/fine_tuning/jobs` — **no `/v1/audio/*`, no
  TTS, no realtime/WebSocket channel**. "Board streams PCM straight into a
  Nebius model" does not exist yet.

### Realistic integration routes

| Route | What it is | Gaps today | Effort |
|---|---|---|---|
| **A. Text brain swap** | MimiClaw agent with Nebius/Token Factory as the LLM (text in/out) | base URL compile-time; works with today's API | Small (config/code edit) |
| **B. Push-to-talk voice note** | Record WAV/Opus on board → upload → STT → text into agent loop → reply as Telegram text (later: TTS + speaker) | no STT on Nebius hosted API; MimiClaw has no capture/upload code; media messages ignored | Medium (custom firmware) |
| **C. Duplex streaming** | Board WS audio → relay on Nebius → ASR → LLM → (TTS) → text/audio back | needs self-hosted Whisper on Nebius (AI Cloud/DevPod/Endpoint or NIM-style) since hosted API has no audio; WS gateway must accept binary frames | Larger (firmware + relay) |

Route C matches the architecture this repo already uses (SkillForge): thin
client → relay → Nebius/Token Factory LLM turns; the speech pieces run on the
relay, not on Nebius's hosted inference API.

## 5. Board-selection table

All boards must be the **N16R8 (16 MB flash + 8 MB PSRAM)** variant to run
MimiClaw — vendors sell identical-looking boards with smaller memory. Cells
marked ⚠ come from a single vendor page/review and should be checked against
the actual revision before buying.

| Board | Chip config | Mic / speaker | Display / input | Battery | MimiClaw fit |
|---|---|---|---|---|---|
| **Xiaozhi AI chatbot board** (Spotpear 1.54"/1.85" round & similar OEMs, ~$10) | ESP32-S3 N16R8 | on-board MEMS mic (INMP441-class) + amp/speaker | round LCD + buttons + RGB LED | charge IC + 3.7 V LiPo connector on most revisions ⚠ | **Best**: the board MimiClaw's quick start names; also runs full XiaoZhi voice firmware |
| **ESP32-S3-DevKitC-1 N16R8** (~$8) | ESP32-S3-WROOM-1 N16R8 | none — add INMP441 (GPIO4/5/6) + MAX98357A (GPIO7/15/16) + OLED (I2C) per XiaoZhi reference wiring | Boot/buttons; add your own | none (USB) | Great DIY path; MimiClaw-listed |
| **LILYGO T7-S3** (~$8–16) | N16R8 | none | compact, no display | 2-pin JST LiPo + charging | Good bare dev board; MimiClaw-listed |
| **DFRobot FireBeetle 2 ESP32-S3** | N16R8 only on "AI Acceleration"/camera variants (4 MB versions don't qualify) | none | none | Li-ion charging + on/off | Good low-power; MimiClaw-listed; pick N16R8 SKU |
| **Seeed XIAO ESP32S3 Plus** | 16 MB flash + 8 MB PSRAM | none (Sense variant adds mic+camera but is 8 MB flash) | none (tiny) | battery charge support ⚠ | Smallest form factor for a "pin"; MimiClaw-listed |
| **Waveshare ESP32-S3-Touch-LCD-3.49** (N16R8) | N16R8 | onboard speaker + mic audio circuits ⚠ | 3.49″ 480×640 IPS touch | n/k | All-in-one XiaoZhi "plug-and-play"; strong voice candidate |

## 6. Route comparison for a wearable demo

Scored for a "personal AI pin/companion" demo on this stack (ESP32-S3 N16R8
board + a relay on Nebius + Token Factory open models). Ranges below are
order-of-magnitude engineering estimates for a competent ESP-IDF + backend
developer, not measurements — verify pricing and power before quoting them.

| | **A — Text brain swap** | **B — Push-to-talk voice** | **C — Duplex streaming** |
|---|---|---|---|
| Wearer experience | type in Telegram on phone; agent answers in Telegram | press-to-talk into the pin; reply returns as text (spoken reply later) | hands-free conversation: wake word, stream audio up, spoken replies down |
| On-device audio | none needed | I2S mic capture + encode + upload (works on single-mic boards) | wake word + continuous Opus uplink + AEC — realistically needs a dual-mic board + speaker |
| New backend pieces | none (edit base URL + model in `mimi_config.h`) | Whisper-class STT on the relay; rest unchanged | streaming ASR + TTS + full-duplex WS on the relay |
| Dev effort | ~1 day | ~1–2 weeks | ~3–6 weeks (wake word, AEC, latency) |
| Latency to first reply | 3–8 s text (measured by XDA review) | ≈ clip length + 2–5 s (e.g. ~8–11 s for a 6 s clip) | target ≈ 1.7 s per turn (XiaoZhi measured end-to-end voice pipeline) |
| LLM cost/turn | open model on Token Factory — sub-cent to a few cents per short turn (verify page pricing) | same as A | same as A, but more turns if always-listening |
| Speech cost | $0 | ~$0.001–0.01 per ~30 s clip (Whisper-class hosted rates or GPU seconds) | per-minute streaming ASR + TTS + GPU hosting for the relay |
| Power profile | lightest (WiFi poll only) | idle + bursty capture/upload | heaviest — continuous mic + WiFi TX (measured runtime: open question) |
| Key risks | none audio-related; model-ID/URL config | clip-boundary UX; echo if you add a speaker | AEC/wake-word robustness; latency tuning; bigger case + battery |

### Recommendation

Start with **A (≈1 day)** — an always-on text agent on NVIDIA open models via
Nebius is the track floor and ships regardless of anything else. Increment to
**B (≈1–2 weeks)** for the demo's "voice" moment: real I2S capture on the $10
Xiaozhi board, STT on a Nebius relay, LLM via Token Factory. Treat **C as the
stretch goal** — only pursue it if hands-free conversation *is* the demo
thesis, and if so buy a dual-mic board and budget the AEC risk up front. B
offers the best wow-per-effort for a wearable personal-assistant demo; A is
the fallback that always works; C is where the project lives if the pitch is
real-time voice.

## 7. Route scoring vs. the Personal AI track (submission direction)

Scoring A/B/C against the criteria already laid out in
[CAPABILITIES.md](./CAPABILITIES.md): the track reads as two parts — (1) an
always-on, private assistant with persistent memory, reusable skills, chosen
tools/channels, doing daily tasks; (2) built with ≥1 NVIDIA open model and
Nebius Serverless-class tooling used to **Assemble / Secure / Run** it. Judges
weigh equally: Technological Implementation, Design, Potential Impact,
Quality of the Idea, gated by Stage One (a genuine attempt, not a rebrand).
Scores 1–5, higher = better; these are judgment calls, not measurements.

| Criterion | **A — Text swap** | **B — Push-to-talk** | **C — Duplex streaming** |
|---|---|---|---|
| Stage One fit (full sentence) | 4 | 4 | 5 |
| Technological Implementation | 3 | 4 | 5 *if shipped* |
| Design (demo narrative) | 3 | 4 | 5 |
| Potential Impact | 3 | 4 | 4 |
| Quality of the Idea | 3 | 4 | 5 |
| Feasibility (8 wks, $150) | 5 | 4 | 2–3 |
| Demoability (≤3 min video, judges won't test) | 5 | 4 | 3 |
| **Risk-adjusted best case** | safe floor | **best overall** | stretch only |

### Why B wins on balance

- **A is the floor, not the pitch.** It clears always-on + memory + NVIDIA
  model via Token Factory and demos cleanly (Telegram, like the XDA review),
  but it is text-only on a crowded "OpenClaw on ESP32" field — several ports
  already exist, so Quality-of-Idea risk is the rebrand flag Stage One
  screens for.
- **B adds the one increment that reads as a wearable pin**: real I2S voice
  capture on the $10 Xiaozhi board → Whisper-class STT on a Nebius relay →
  Nemotron/Token Factory turn → reply. Voice is where consumer "pins" live,
  and B keeps the demo reliable (push-to-talk, no live-AEC roulette).
- **C has the best ceiling and the worst variance.** Hands-free conversation
  on cheap hardware is a 5/5 idea, but wake word + AEC (needs a dual-mic
  board) + streaming ASR/TTS + latency work is a 3–6+ week build whose
  failure mode is a dead live demo — the worst outcome when judges won't
  re-test and the video is ≤3 minutes.

### Track-fit notes (verify against rules before scoping)

- **NVIDIA model**: satisfied by Nemotron on Token Factory — and function
  calling against Nemotron is already proven in this repo's live compose
  path, which de-risks MimiClaw's OpenAI-style tool dialect.
- **Assemble/Secure/Run**: all three routes *Run* via Token Factory but
  **none use Hermes/OpenShell/NemoClaw** — the agent lives on the chip. Two
  defensible postures: (a) argue the chip **is** the personal system (data on
  flash, no OS, no cloud shell) with Token Factory as the Run layer; or
  (b) strengthen **Secure** cheaply by implementing MimiClaw's missing bot
  allow-list (its own TODO lists this as P1) — "the agent only answers me"
  is a 10-second demoable line that mirrors OpenShell's egress story.
- **Privacy/data control**: A is strongest (text only, memory on flash). B/C
  transmit audio — keep the STT relay self-hosted on Nebius (our account,
  our retention), and note that Telegram replies route through a third party;
  the WebSocket gateway (port 18789) is the third-party-free alternative.
- **Costs**: A ≈ LLM tokens only; B adds GPU-seconds for STT (scale-to-zero
  Endpoint/DevPod — fits the $150 envelope at demo scale); C is the most
  expensive (always-on streaming ASR/TTS hosting) but still demo-sized.

### Recommendation

**Submit B, built so it collapses to A.** *(Superseded Sep 7, 2026: the
submission direction pivoted to the deaf-blind haptic companion — see
[HAPTIC_COMPANION_PLAN.md](./HAPTIC_COMPANION_PLAN.md), which keeps B's
push-to-talk input, replaces the screen/speaker output with vibro-braille,
and collapses the Route C hard problems by design.)* Day-1 spike gates everything: get a
voice clip from the N16R8 board into a Nebius relay and back as text — if
that works in week 1, proceed on B; if not, ship A and still clear the bar.
Gate C behind the same spike plus a dual-mic board arriving in week 1; do not
plan the submission around C unless hands-free voice *is* the thesis. Carry
SkillForge's differentiators into the pitch: per-turn budget/model routing
(cost-aware autonomy = the track's Run economics), the no-OS data-on-chip
privacy story, and the allow-list as the visible Secure beat.

## Sources

- MimiClaw repo: <https://github.com/memovai/mimiclaw>
- MimiClaw docs: [ARCHITECTURE.md](https://github.com/memovai/mimiclaw/blob/main/docs/ARCHITECTURE.md), [TODO.md](https://github.com/memovai/mimiclaw/blob/main/docs/TODO.md), [mimi_config.h](https://github.com/memovai/mimiclaw/blob/main/main/mimi_config.h), [llm_proxy.c](https://github.com/memovai/mimiclaw/blob/main/main/llm/llm_proxy.c) (full `main/` tree, latest merge Aug 21, 2026)
- Reviews: [CNX Software (Feb 13, 2026)](https://www.cnx-software.com/2026/02/13/mimiclaw-is-an-openclaw-like-ai-assistant-for-esp32-s3-boards/), [XDA hands-on (Apr 9, 2026)](https://www.xda-developers.com/tried-openclaw-inspired-ai-assistant-on-10-esp32-board-itworks/)
- Pi Pin: <https://github.com/liltom-eth/pi-pin>
- XiaoZhi ESP32-S3 technical specs & reference wiring: <https://xiaozhi.dev/en/docs/esp32/technical-specs/>
- Nebius OpenAI-compatible API spec: <https://api.studio.nebius.com/openapi.json>; docs <https://api.studio.nebius.com/docs>
- Boards: [LILYGO T7-S3](https://lilygo.cc/en-us/products/t7-s3), [CNX on T7-S3](https://www.cnx-software.com/2022/10/31/lilygo-t7-s3-esp32-s3-board-16mb-flash-8mb-psram-lipo-battery/), [FireBeetle 2 ESP32-S3 wiki](https://wiki.dfrobot.com/dfr0975/), [XIAO ESP32S3 wiki](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)

## Open questions (verify before scoping)

- [ ] Does any MimiClaw fork or sibling repo (e.g., the ESP32/ESP32-C3 "OpenClaw"
      ports, `zclaw`, WireClaw) add I2S mic capture or BLE audio? (MimiClaw main
      branch: no.)
- [ ] Exact battery life of the Xiaozhi-class N16R8 boards streaming voice over
      WiFi (no measured numbers found; XiaoZhi spec quotes ~100 mA connected /
      ~0.5 W idle MimiClaw).
- [ ] Whether Nebius adds audio transcription / TTS / a realtime channel to its
      hosted API (public spec on 2026-09-03 has none; community idea boards
      still request TTS).
- [ ] Actual BLE/A2DP speaker-out feasibility on this board class (SoC supports
      BT 5 LE + audio via I2S amp; no firmware uses it yet).
- [ ] Board-level detail per vendor revision: battery charge IC, mic model, amp
      gain — cells marked ⚠ above.

## How this note is used

1. Pick a hardware direction (pin-style wearable vs. desktop agent dongle) →
   one-page problem brief.
2. Resolve the open questions that gate the chosen direction (relay/STT
   placement on Nebius first — it is the top architecture risk).
3. If pursuing the voice route, scope the build as Route A/B/C above: what the
   board sends, where speech lives, and which Nebius surface drives the brain.
4. Feed verified claims back into the Devpost write-up so nothing is asserted
   without a source.
