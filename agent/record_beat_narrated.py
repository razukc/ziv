"""record_beat_narrated.py — the demo beat, with narration baked in.

Devpost's organizers are explicit: name Nebius Token Factory / AI Cloud and
the NVIDIA model "clearly — with audio — in your demo video, not just a
passing mention." record_beat.py's webm is silent, so this pipeline adds the
voiceover:

  1. record the 0:20-1:10 beat exactly as record_beat.py does (the e2e-style
     in-process timing trick: the victim's real click lands while the gate is
     provably full), stamping a wall-clock mark at each phase's sync point;
  2. synthesize one narration segment per phase with Windows SAPI (PowerShell
     System.Speech — no pip deps, works offline);
  3. place each segment at its mark's offset over a silence bed and mux with
     ffmpeg (webm + narration -> demo_beat_narrated.mp4). The video's last
     frame is held while the closing "stack" lines finish speaking, so the
     required names are never cut off.

Run (server already up on :8787, FAKE_MODEL_SECONDS=8, cell_gap 250):
    venv/Scripts/python.exe record_beat_narrated.py
Out:   demo_beat.webm (silent master, same as record_beat.py)
       narration/seg_*.wav + narration/marks.json (kept for re-mixing)
       demo_beat_narrated.mp4 (the upload track)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8787"
OUT = Path("demo_beat.webm")
MP4 = Path("demo_beat_narrated.mp4")
NARR_DIR = Path("narration")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
VOICE = "Microsoft Zira Desktop"  # falls back to the SAPI default if absent

# (phase, [lines]) — the lines NAME the required tools out loud.
SCRIPT: list[tuple[str, list[str]]] = [
    ("intro", [
        "This is Ziv: messages you can feel. Nobody else can see.",
        "Every pattern on screen is played by the relay in real time.",
    ]),
    ("starter", [
        "A typed message enters the relay's one turn pipeline:",
        "arrival cue, working ticks, braille cells, end of message.",
    ]),
    ("fills", [
        "While it plays, more messages arrive.",
        "The haptic channel is serial, so they queue instead of interrupting.",
    ]),
    ("refusal", [
        "At the cap, the sender gets H T T P four twenty nine:",
        "a plain language refusal, never a silent drop.",
    ]),
    ("redial", [
        "The refused message redials itself when the wrist feels the closing pulse.",
        "The queue drains, oldest first, each replay opening with its cue.",
    ]),
    ("stack", [
        "Ziv's hearing layer is NVIDIA Nemotron three Nano Omni on Nebius Token Factory:",
        "speech in, text out, one audio native model on an Open A I compatible endpoint.",
    ]),
]

_MARKS: dict[str, float] = {}
_T0 = 0.0


def mark(name: str) -> None:
    """Stamp a wall-clock mark (seconds since the recording started)."""
    _MARKS[name] = time.time() - _T0


# ---------------------------------------------------------------- SAPI TTS


def say(line: str, wav: Path) -> None:
    """One SAPI segment -> 48 kHz 16-bit mono PCM WAV."""
    ps = f"""
      Add-Type -AssemblyName System.Speech
      $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
      try {{ $s.SelectVoice('{VOICE}') }} catch {{ }}
      $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
      $s.SetOutputToWaveFile('{wav.resolve()}', $fmt)
      $s.Rate = 0
      $s.Speak('{line.replace("'", "''")}')
      $s.Dispose()
    """
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   capture_output=True, timeout=120)


def build_segments() -> dict[str, list[Path]]:
    NARR_DIR.mkdir(exist_ok=True)
    segs: dict[str, list[Path]] = {}
    for phase, lines in SCRIPT:
        segs[phase] = []
        for i, line in enumerate(lines):
            wav = NARR_DIR / f"seg_{phase}_{i}.wav"
            say(line, wav)
            segs[phase].append(wav)
    return segs


def media_seconds(path: Path, is_video: bool = False) -> float:
    """Duration via `ffmpeg -i` (last time= / Duration: in stderr)."""
    proc = subprocess.run([FFMPEG, "-i", str(path), "-f", "null", "-"],
                          capture_output=True, text=True)
    err = proc.stderr
    if is_video:
        m = re.findall(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", err)
    else:
        m = re.findall(r"time=(\d+):(\d+):(\d+)\.(\d+)", err)
    if not m:
        return 0.0
    h, mnt, s, cs = (int(x) for x in m[-1])
    return h * 3600 + mnt * 60 + s + cs / 100.0


# ---------------------------------------------------------------- mux


def mux(video: Path, segs: dict[str, list[Path]]) -> None:
    """Place each phase's segments at its mark offset over a silence bed.

    The video's final frame is cloned (tpad) for exactly as long as the
    audio runs past it, so the closing stack lines (the required names)
    always have picture and are never truncated.
    """
    video_s = media_seconds(video, is_video=True)

    events: list[tuple[int, float, float]] = []  # (input idx, offset, dur)
    inputs = ["-i", str(video)]
    chains = []
    file_idx = 1  # input FILE index — len(inputs) counts CLI items (2/file)
    cursor = 0.0  # global narration cursor: lines queue, never overlap
    for phase, _ in SCRIPT:
        base = _MARKS.get(phase)
        if base is None or not segs.get(phase):
            continue
        offset = max(base, cursor)
        for wav in segs[phase]:
            dur = wav_seconds_cached(wav)
            if dur <= 0:
                continue
            inputs += ["-i", str(wav)]
            ms = int(offset * 1000)
            chains.append(f"[{file_idx}:a]adelay={ms}:all=1[d{file_idx}]")
            events.append((file_idx, offset, dur))
            file_idx += 1
            offset += dur + 0.7  # a breath between lines
        cursor = offset
    audio_end = max((o + d for _, o, d in events), default=0.0)
    hold = max(0.0, audio_end - video_s + 0.5)
    total = max(audio_end, video_s) + 0.5

    inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
    bed = file_idx  # the silence bed lands on the next file index
    mix_ins = "".join(f"[d{i}]" for i, _, _ in events)
    graph = (
        "[0:v]tpad=stop_mode=clone:stop_duration=" + f"{hold:.2f}[v];"
        + ";".join(chains) + ";"
        + f"[{bed}:a]{mix_ins}amix=inputs={len(events) + 1}:normalize=0[out]"
    )
    cmd = [FFMPEG, "-y", *inputs,
           "-filter_complex", graph,
           "-map", "[v]", "-map", "[out]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-t", f"{total:.2f}",  # the unbounded silence bed needs a cap
           str(MP4)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-3000:])
        raise SystemExit("ffmpeg mux failed")


_cache: dict[Path, float] = {}


def wav_seconds_cached(path: Path) -> float:
    if path not in _cache:
        _cache[path] = media_seconds(path)
    return _cache[path]


def clear_state() -> None:
    """Empty the inbox + schedule before recording.

    A stale inbox poisons the beat: on attach the server replays every
    stored message as a full turn, and the script's tight timing races
    against the drain (learned the hard way — ten stored messages from
    failed runs made the victim unrefusable). Same hygiene as
    record_gallery.py's main().
    """
    for path in ("api/ziv/inbox", "api/ziv/schedule"):
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"{BASE}/{path}", method="DELETE"),
                timeout=10)
        except urllib.error.HTTPError:
            pass


def gate_depth() -> int:
    with urllib.request.urlopen(f"{BASE}/api/ziv/health", timeout=5) as x:
        return int(json.loads(x.read())["gate_queue"])


def wait_gate_full(timeout_s: float = 30.0) -> int:
    """Block until the replay queue holds all 8 fills; return the depth."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with urllib.request.urlopen(f"{BASE}/api/ziv/health", timeout=5) as x:
            depth = json.loads(x.read())["gate_queue"]
        if depth >= 8:
            return depth
        time.sleep(0.1)
    raise AssertionError("the replay queue never filled — fills failed")


def main() -> int:
    global _T0
    clear_state()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir=".",
            record_video_size={"width": 1280, "height": 800},
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(f"{BASE}/ziv_client/index.html", wait_until="domcontentloaded")
        page.locator("#queueBadge").wait_for(state="visible", timeout=10000)
        page.locator("#state").filter(has_text="connected").wait_for(timeout=10000)
        page.locator("#btnUnlock").click()
        # Preflight: a poisoned gate (a previous run/device vanished with
        # entries still queued) queues the starter behind ghosts and no
        # message frame ever renders. Fail loud with the fix, not quiet
        # 12 s later.
        depth = gate_depth()
        if depth != 0:
            print(f"relay gate holds {depth} queued entries — restart the "
                  "relay for a clean take (a queue whose freeing turn ended "
                  "with no device attached never drains)")
            return 1
        _T0 = time.time()
        mark("intro")

        # Beat 1: the starter turn via a real click.
        page.locator("#msg").fill("hold that thought")
        page.locator("#btnSend").click()
        page.wait_for_selector("text=message: hold that thought", timeout=12000)
        mark("starter")
        # The word rides in argv and json.dumps builds the payload — no
        # nested-quote escaping to get wrong (a doubled backslash here once
        # turned every fill into a 422 and the victim was never refused).
        fill_code = (
            "import sys, urllib.request, json;"
            "req=urllib.request.Request("
            f"'{BASE}/api/ziv/message',"
            "data=json.dumps({'text': sys.argv[1]}).encode(),"
            "headers={'Content-Type':'application/json'});"
            "urllib.request.urlopen(req, timeout=120)"
        )
        procs = [
            subprocess.Popen([sys.executable, "-c", fill_code, w])
            for w in ("alpha", "bravo", "charlie", "delta",
                      "echo", "foxtrot", "golf", "hotel")
        ]
        mark("fills")
        for p in procs:
            p.wait(timeout=120)
        wait_gate_full()  # checked, not assumed: the gate holds all 8

        # The victim: a real click, now that the gate is provably full.
        page.locator("#msg").fill("nine")
        page.locator("#btnSend").click()
        page.locator("#state").filter(has_text="wrist is busy").wait_for(timeout=8000)
        note = page.locator("#redialNote")
        note.wait_for(state="visible", timeout=5000)
        assert "nine" in note.inner_text() and "3 chances left" in note.inner_text()
        mark("refusal")

        # The redial: fires on the freeing close, on camera.
        page.locator("#log div").filter(
            has_text="↻ redial — resending"
        ).first.wait_for(timeout=60000)
        page.locator("#log div").filter(has_text="POST ok").first.wait_for(timeout=60000)
        page.locator("#queueBadge").filter(has_text="queue 0/8").wait_for(timeout=120000)
        mark("redial")
        time.sleep(1.0)
        mark("stack")  # narration continues over the drained tail
        video = page.video
        context.close()  # flush the recording
        path = video.path() if video else None
        browser.close()

    if not path:
        print("no video captured")
        return 1
    NARR_DIR.mkdir(exist_ok=True)
    # Marks hit disk BEFORE anything can fail on the rename — a lost take's
    # timing is unrecoverable otherwise. os.replace: overwrite-safe on
    # Windows (Path.rename raises FileExistsError on an existing target).
    (NARR_DIR / "marks.json").write_text(json.dumps(_MARKS, indent=2))
    import os
    os.replace(path, OUT)
    print("silent master:", OUT.resolve())
    print("marks:", json.dumps({k: round(v, 2) for k, v in _MARKS.items()}))

    print("synthesizing narration (SAPI)...")
    segs = build_segments()
    print("muxing with ffmpeg...")
    mux(OUT, segs)
    print("saved:", MP4.resolve())
    print("beat narrated: starter -> 8 fills -> refusal -> redial -> drained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
