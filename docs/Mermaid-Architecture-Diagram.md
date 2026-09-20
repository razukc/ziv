# Ziv system architecture

Mermaid diagram of the current Ziv relay, timed output channel, and the
honest scope of the device (dev band vs. scoped wrist build). Rendered
from this markdown with any mermaid viewer (e.g. a `.mmd` import, Obsidian,
the [Mermaid live editor](https://mermaid.live)).

```mermaid
architecture-beta
    %% Styles so the honest frames are visually readable
    group gCore[" Built & proven in the relay/timing/output channel "]
    group gDevBand[" Phone dev band (visible output channel today) "]
    group gScope[" Device scope: designed / de-risked, not on hardware yet "]
    group gOut[" Honest frames (not a layer in the system) "]

    service kernel[" 🖥  Relay process (Python, FastAPI + WS)"] in gCore
    service seam[" ziv_relay.py  —  MessageGate + TurnTimeline + TurnEvent vocabulary "] in gCore
    service store[" ziv_store.py  —  wearer memory (atomic JSON) + capped inbox "] in gCore
    service server[" ziv_server.py  —  WS transport /api/ziv/message /api/ziv/timing /inject/audio health "] in gCore
    service timing[" Generated timing module  (docs/haptic-timing.json → spec envelope, no hand-copied numbers) "] in gCore
    service qemu[" QEMU ladder  —  bench binary + boot app + derived-fixture differ (firmware de-risking) "] in gCore

    service phone[" 📱 Phone PWA  (Vibration API, zero hand-copied timing) "] in gDevBand
    service oppo[" 👤 Friend's phone  (text-side of the conversation) "] in gDevBand

    service wrist[" Wristband (ESP32-S3 N16R8 + 6× DRV2605L + 6 LRAs + 6 chord keys + I2S mic + LiPo)  —  scoped / de-risked, not flashed yet "] in gScope
    service inputDev[" Chord input  (6-key debounce + chord decode + text buffer)  —  not built yet "] in gScope
    service micDev[" Device mic  (I2S → WAV/Opus frames → WS binary)  —  not built yet "] in gScope

    service omniaws[" Nebius Token Factory  (Nemotron-3-Nano-Omni, audio-in / text-out) "] in gCore
    service cron[" Scheduled jobs / heartbeat  (the always-on relay presence) "] in gCore

    %% -- Data / control flows --
    lane flows over gCore

    phone:RIGHT_WITH_TOP>server:"WS connect + optional ZIV_RELAY_TOKEN"
    server:RIGHT_SW>seam:"admit(text) → TurnTimeline lifecycle"
    seam:RIGHT>store:"deliver queued message on next attach (mark-after-play)"
    server:LEFT_WITH_TOP>timing:"reads feel spec (timing bootstrap)"
    server:DOWN_WITH_TOP>omniaws:"/inject/audio → Omni transcript → same turn"
    server:DOWN_WITH_TOP>cron:"scheduled job → message → inbox delivery"
    seam:LEFT_WITH_TOP>server:"TurnEvents (kind cue → processing → cells → close)"
    server:LEFT_SW>phone:"frame stream (text / cue / cells / close, free: true)"
    phone:RIGHT_SW>phone:"Vibrate pattern matching TurnTimeline"

    %% -- The honest frames (as notes, not system layers) --
    note oAlways[" always-on is the relay (24/7 presence); the wristband sleeps between events and wakes on button / chord / mic / WiFi activity "] in gOut
    note oDevBand[" phone is the visible output channel today (dev band), not a flashed wrist "] in gOut
    note oFriend[" friend reads the reply as text on their phone / relay log — no speaker in the room; spoken replies are v2 (TTS on the relay) "] in gOut
    note oRefuse[" full queue refusals: gate returns message:rejected (reason: queue_full); server maps to HTTP 429; client shows \"wrist is busy\" + re-arms its own redial on free: true close "] in gOut
    note oScope[" wrist build is scoped + de-risked (QEMU ladder, bring-up stages A-F) but not on hardware yet "] in gOut

    %% connect notes to the relevant nodes as visual anchors
    oAlways:BELOW(node kernel)
    oDevBand:BELOW(node phone)
    oFriend:BELOW(node oppo)
    oRefuse:BELOW(node seam)
    oScope:BELOW(node wrist)
```
