# android — the native phone renderer

The phone renderer of [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) §5.4: a
native Android app that is a *device* in the sense of §5.1. It holds a bounded
queue of utterances, plays exactly one at a time on the phone's motor with the
`single_actuator` profile (a letter as six time slots), reports `progress`,
`played` and `nack` over the wire of `ziv.wire`, takes the wearer's controls, and
keeps its queue across process restarts. Unlike the web client it runs in a
foreground service, so the channel works with the screen off and the app out of
sight.

```
android/
  settings.gradle.kts, build.gradle.kts, gradle.properties, gradlew   Gradle 8.9 wrapper, AGP 8.7.3, Kotlin 2.0.21
  core/        pure Kotlin/JVM, no Android dependency
    src/main/kotlin/ziv/core/
      Spec.kt        docs/haptic-timing.json (as GET /spec serves it) -> every duration the renderer uses; v4 required
      Wire.kt        the utterance and the frames both ways, exact JSON names (kotlinx.serialization); reasons stay open strings
      Sequencer.kt   (utterance, spec, pace, profile) -> segments -> timeline; the reference's model, label for label
      Player.kt      deadline scheduler over an injectable clock/timers and a vibrate(mask, ms) sink; drift never accumulates
      Device.kt      the renderer state machine: queue of 20, de-dup by id, cue interjection, working repeats, controls, prefs
      Transport.kt   hello-first over an abstract socket, ping cadence, doubling backoff, fresh hello with last_acked + held
      QueueStore.kt  the persisted snapshot (held entries + last_acked); memory implementation for tests
      Words.kt       compose normalisation: letters, digits spelled out, anything else refused naming the character
      Main.kt        the conformance player (`installDist` -> build/install/core/bin/core)
    src/test/kotlin/ziv/core/   JUnit: sequencer goldens, player, device, transport, wire-vs-schema, words, player CLI
  app/         the Android app (classic Views + ViewBinding, no Compose)
    src/main/kotlin/ziv/android/
      RendererService.kt   foreground service: owns the socket, the device, the player and the motor on one thread
      MainActivity.kt      the wearer's screen: status, five controls, pace, advance, reply box, setup
      AndroidVibrateSink.kt  VibratorManager/Vibrator, waveform at full amplitude or one-shot, accessibility usage
      OkHttpSockets.kt     OkHttp WebSocket behind the core's SocketFactory, callbacks marshalled to the device thread
      SqliteQueueStore.kt  the queue snapshot in SQLite, one row replaced per transaction
      RelayApi.kt          GET /spec, POST /devices/enroll, the plain-HTTP allow-list
      Settings.kt          relay URL, device key, profile, pace, advance, silent-ok in private preferences; spec cache
      HandlerTimers.kt, Phrasing.kt, BootReceiver.kt, ZivApp.kt
    src/debug/           network security config permitting cleartext (emulator host, loopback, LAN bench); release has none
```

## Build

JDK 17 and an Android SDK with `platforms;android-35` and `build-tools;35.0.0`
(`local.properties` with `sdk.dir=…`, or `ANDROID_HOME`). The wrapper fetches
Gradle 8.9; the first build fetches AGP, Kotlin and the libraries (pinned in
`build.gradle.kts` and the module files: kotlinx-serialization-json 1.7.3,
OkHttp 4.12.0, AppCompat 1.7.0, core-ktx 1.13.1, Material 1.12.0).

```bash
cd android
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ANDROID_HOME=$HOME/android-sdk
./gradlew :core:test            # the JVM suite
./gradlew :core:installDist     # the conformance player -> core/build/install/core/bin/core
./gradlew :app:assembleDebug    # -> app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:assembleRelease  # unsigned; TLS only
```

Last run (2026-11-06): `:core:test` 46 tests, 0 failures (DeviceTest 16,
SequencerGoldenTest 7, PlayerTest 6, TransportTest 6, WireTest 6, MainTest 3,
WordsTest 2); `app-debug.apk` 7 609 858 bytes.

## Conformance

The `:core` sequencer is a player for the cross-renderer oracle
([conformance/README.md](../conformance/README.md)): an utterance on stdin, the
timeline as JSON Lines on stdout. It finds `docs/haptic-timing.json` from the
working directory upward (the harness runs from the repo root) or takes
`--spec <path>`.

```bash
cd ..   # the repository root
.venv/bin/python conformance/run.py --player "android/core/build/install/core/bin/core" --profile single_actuator
.venv/bin/python conformance/run.py --player "android/core/build/install/core/bin/core" --profile six_actuator
```

Last run: 12/12 PASS on both profiles. The JVM test
`SequencerGoldenTest` holds the same sequencer to `conformance/expected/*.jsonl`
text for text, which is stricter than the harness's ±10 ms.

## Run on an emulator

```bash
export ANDROID_HOME=$HOME/android-sdk JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "emulator" "system-images;android-35;google_apis;x86_64"
echo no | $ANDROID_HOME/cmdline-tools/latest/bin/avdmanager create avd -n ziv -k "system-images;android-35;google_apis;x86_64" -d pixel_6
$ANDROID_HOME/emulator/emulator -avd ziv -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -memory 2048 &
$ANDROID_HOME/platform-tools/adb wait-for-device shell 'while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 1; done'
```

The emulator needs KVM: the user must be able to open `/dev/kvm`
(`sudo gpasswd -a $USER kvm`, then log in again; or `sudo setfacl -m u:$USER:rw /dev/kvm`).
On a minimal Ubuntu it also needs `libxkbfile1` (`sudo apt install libxkbfile1`).

Then the integration test, which boots the relay in-process on a loopback port
(reachable from the emulator as `10.0.2.2`), installs the debug APK, launches
the app with the relay URL and a fresh enroll code as intent extras, submits
utterances over HTTP and waits for `played` on the relay side; `adb logcat` for
the app's tag is attached to every failure:

```bash
cd ..
.venv/bin/python -m pytest -q -m device tests/device -rs
```

It is deselected by default (`pyproject.toml` `addopts`) and skips, naming the
reason, when adb, the APK or a booted emulator is missing. The debug build
accepts the setup as launch extras, so the same thing by hand is:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n ziv.android/.MainActivity --es relay_url http://10.0.2.2:8787 \
    --es enroll_code ABCD1234 --es profile single_actuator --ez silent_ok true
adb logcat -s ZivRenderer:D
```

`silent_ok` lets a device without a vibration motor play on its clock (an
emulator reports no motor, or one that cannot be felt); without it such a device
answers every `utterance.open` with `nack muted`, as the contract asks of a
renderer that cannot render. The wire log on logcat shows frame types and ids,
never words.

## Run on a phone over the LAN

Install the debug APK (`adb install`, or copy it and allow the install), open
the app, enter the relay address and an enrollment code from the console
(`ziv-relay enroll-code`), press **Connect**. The key the relay returns is kept
in the app's private storage and shown nowhere.

For a bench relay on the same network the debug build accepts plain
`http://`/`ws://` to a private address (10/8, 172.16/12, 192.168/16, link-local,
loopback and the emulator host); any other plain address is refused before a
connection is tried, and the release build has no cleartext permission at all,
so a real deployment is `https://`/`wss://` behind the relay's TLS. The relay
must listen on the LAN interface: `ziv-relay run --host 0.0.0.0 --allow-plain-http`.

A relay running inside **WSL2** is not on the LAN by default. Either forward the
port from Windows (`netsh interface portproxy add v4tov4 listenport=8787
listenaddress=0.0.0.0 connectport=8787 connectaddress=<WSL address>`, plus a
Windows firewall rule) or turn on mirrored networking (`networkingMode=mirrored`
in `%USERPROFILE%\.wslconfig`), then point the phone at the Windows host's
address.

## Accessibility

The wearer is deaf-blind; the screen is operated through TalkBack and a braille
display, never by sight. The layout is one scrolling column whose order is the
reading order and the focus order: status, what is playing, the five controls
(Stop, Replay message, Replay word, Skip word, Next message), the preferences
(pace slider bound to the spec's envelope in the spec's step, the advance toggle,
silent playback), the reply box, and the setup last. Every control is at least
72 dp tall and has a `contentDescription`; headings are marked as such; the
status, the playing line and the result lines are polite live regions and phase
changes are also announced with `announceForAccessibility`; nothing is conveyed
by colour alone. The notification is silent and never vibrates (the motor is the
channel) and shows the current phase. Vibrations are tagged accessibility usage
so Do Not Disturb and touch-feedback settings do not silence them. Only the
current utterance's words are ever shown (the word being played); there is no
history unless the wearer turns the preference on, and then it lives in memory
for the session only.

## Decisions where the contract left room

- **`muted` for `hidden`.** A phone has no hidden page; the renderer refuses
  (`nack muted`) when there is no vibration motor and silent playback is off,
  and stops with `nack muted` if the motor goes away mid-utterance. When it is
  back the service reconnects with a fresh hello so the relay offers again.
- **Spec v4 required.** The web client's v3 fallbacks (literal 2000 ms, word gap
  = cell gap, chord cells everywhere) are not ported: every duration comes from
  the spec that was fetched, and a spec without `kinds`, `profiles`,
  `word_gap_ms` and `working_every_ms` is refused with a reason.
- **The prefix tail** resolves as the web client does: a known pattern id plays
  as named; a kind name resolves to that kind's tail; anything else falls back
  to the utterance kind's tail. The reference refuses an inconsistent tail; for
  consistent input the two agree, which the goldens prove.
- **A cue announced between another utterance's cells is not repeated** at that
  utterance's turn (the web client's decision, kept).
- **Advance past an unfinished utterance drops it** with `nack
  cancelled_by_wearer` so the relay never waits out a handoff window.
- **Expired utterances** are dropped with `nack expired` unless the `late`
  preference is `play`.
- **Per-beat vibration.** The player drives the motor one beat at a time
  (`createWaveform` at full amplitude when the motor has amplitude control, else
  `createOneShot`), so a cue can cut in between cells and the pace can change
  mid-utterance exactly as the state machine decides. A partial wake lock is held
  while anything plays so the handler clock keeps time with the screen off.
- **Foreground service type `specialUse`.** The platform's named types do not
  describe a haptic message channel; the manifest carries the required
  explanation property.
- **The queue in SQLite holds unplayed words.** That is the queue the contract
  requires (held ids in hello, resume after a restart), not a history; a played
  entry leaves in the same write that records its id as acknowledged. The key
  and settings are in private preferences inside the app sandbox.
- **Plain HTTP is a debug-build, private-network affordance** (the emulator
  host, loopback, RFC 1918 and link-local); the release build is TLS only.

## What could not be verified here

- **No emulator boot on this machine.** `emulator -avd ziv …` stops with
  `ProbeKVM: This user doesn't have permissions to use KVM (/dev/kvm)`; the user
  is not in the `kvm` group and granting access needs root. The emulator binary
  also wants `libxkbfile.so.1`, which this Ubuntu lacks (`libxkbfile1`). So
  `tests/device/test_android_renderer.py` has not run against the app; it skips
  with the reason. The protocol it exercises is the one the JVM `DeviceTest`
  proves on a fake clock, and the Android layer around it has compiled but not
  executed.
- **No phone, no motor.** Whether a 50 ms pulse and a 30 ms slot gap are legible
  on a phone motor, and how far `Handler.postDelayed` jitter stays inside the
  10 ms tolerance under load, are open until a wearer has felt it and a logcat
  timeline has been diffed against the reference.
- **No TalkBack session.** The accessibility notes describe what the layout
  declares; nobody has driven it with a screen reader or a braille display.
