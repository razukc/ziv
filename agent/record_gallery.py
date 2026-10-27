"""record_gallery.py — the Devpost screenshot gallery, recorded like record_beat.py.

DEVPOST_UPLOAD_CHECKLIST.md §3 wants 4–6 gallery shots; this script produces
them (9 files, so the uploader can pick 4–6) the same way record_beat.py
produces the demo video: the real relay live in-process on an ephemeral port,
a headless Chromium page on the dev-band PWA, and every state captured on cue
— zero human/tool latency, the timing trick the e2e suite proved.

Shot files (each PNG is exactly 3:2 — Devpost: JPG/PNG/GIF, ≤5 MB, 3:2):

    01-turn-vocabulary.png    cells box lighting up + the wire log walking
                              cue → processing → message → cells → queued
                              (the whole vocabulary in one frame)
    02-badge-queue3.png       the badge healthy: queue 3/8 · reminders 0/64
    02-badge-refusing.png     the badge full: refusing — queue full (8/8),
                              the busy note and the redial armed
    03-redial-dead-end.png    the red dead-end note after three tries
    03-redial-lifecycle.png   the give-up line → manual send → POST ok
    04-reminder-turn.png      reminder: pills unprompted, Z-I-V cells,
                              triple-pulse in the log
    05-health-json.png        the operator view: gate_queue, schedule_pending,
                              queue_rejections — the numbers the badge renders
    06-test-proof.png         the pytest tail beside the firmware bench line
    07-fire-while-away.png    inbox:stored while no band is attached →
                              reattach → the self-naming replay

Presentation note: the shots are real server-rendered states; the only
presentational tweaks are the checklist's own idea (readable zoom) plus
hiding the PWA's instructional paragraph so the evidence (badge, note,
cells, wire log) fits one 3:2 frame.

Run (self-contained — starts and stops its own relay; no other service needed):

    cd agent
    venv/Scripts/python.exe record_gallery.py        # POSIX: venv/bin/python

Out: agent/gallery_shots/*.png — plus CAPTIONS.md, the paste-ready per-image
captions for Devpost's caption field (edit CAPTIONS below, not the .md).
Gitignored — regenerate before uploading.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OUT_DIR = HERE / "gallery_shots"
VW, VH = 1260, 840   # 3:2 — every shot is a full frame of a page this size
ZOOM = 1.2           # the checklist's readable-log zoom; the band still fits
FAKE_MODEL_SECONDS = "0.5"
CELL_GAP_MS = 250    # the wearer's fastest pace, as in the e2e suite
STARTER = "Taxi arrived"  # 11 letters ≈ 5 s of playback — the fill window

# Devpost's image gallery has a per-image caption field; these are the
# paste-ready texts, emitted as gallery_shots/CAPTIONS.md each run. They
# describe what each shot's pixels actually show — keep them in sync with
# the shot code above, not with aspirations.
CAPTIONS: dict[str, str] = {
    "01-turn-vocabulary.png": (
        "One turn, the whole vocabulary: arrival cue → working ticks → "
        "message → braille cells → end-of-message close, live in the "
        "dev-band wire log — while two later messages announce themselves "
        "mid-turn and queue instead of interrupting."
    ),
    "02-badge-queue3.png": (
        "The queue badge in its healthy state — queue 3/8 · reminders 0/64 "
        "— polled live from the relay's health endpoint while the current "
        "turn plays."
    ),
    "02-badge-refusing.png": (
        "Queue full: the badge reads refusing — queue full (8/8), the sender "
        "gets HTTP 429 with a plain-language busy note, and the refused "
        "message arms its redial. A loud no, never a silent drop."
    ),
    "03-redial-dead-end.png": (
        "The redial's loud dead end: three tries, three refusals — the red "
        "note stays on screen until the wearer acts, and the log records "
        "the give-up."
    ),
    "03-redial-lifecycle.png": (
        "Recovery on the same screen: manual send → the note clears → "
        "POST ok. The redial fires on the close frame the wearer feels, "
        "not on a timing guess."
    ),
    "04-reminder-turn.png": (
        "An agent turn, unprompted: a scheduled reminder fires as its own "
        "full turn — reminder: pills, the Z-I-V name mark spelled in cells, "
        "the triple-pulse tail."
    ),
    "05-health-json.png": (
        "The operator view: GET /api/ziv/health, top to bottom — gate queue "
        "and cap, rejection telemetry, schedule depth, turn history — the "
        "same numbers the badge renders."
    ),
    "06-test-proof.png": (
        "Every claim reproducible: the hermetic pytest suite's summary line "
        "beside the firmware bench suite's — both counts on screen, both green."
    ),
    "07-fire-while-away.png": (
        "Fire-while-away: with no band attached the relay stores the "
        "message (inbox:stored); on reattach the hello reports the pending "
        "count and each replay arrives as a self-naming turn — mark first, "
        "content after."
    ),
}


# ---------------------------------------------------------------------------
# tiny HTTP helpers (plain urllib — usable before/during/after Playwright)
# ---------------------------------------------------------------------------


def http_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def spawn_fill(base: str, word: str) -> subprocess.Popen:
    """One queue-filling POST, fired in a child interpreter and not waited
    on — record_beat.py's fill_via_http, kept verbatim in spirit."""
    return subprocess.Popen(
        [
            sys.executable, "-c",
            "import urllib.request;"
            "req=urllib.request.Request("
            f"'{base}/api/ziv/message',"
            "data=b'{\"text\": \"" + word + "\"}',"
            "headers={'Content-Type':'application/json'});"
            "urllib.request.urlopen(req, timeout=120)",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def wait_for(pred, timeout_s: float, what: str):
    deadline = time.time() + timeout_s
    last: object = None
    while time.time() < deadline:
        try:
            got = pred()
        except Exception as exc:  # a refused poll is still progress information
            got, last = False, exc
        if got is not None and got is not False:
            return got
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}"
                         + (f" (last: {last!r})" if last is not None else ""))


# ---------------------------------------------------------------------------
# the real relay, live in-process (the e2e fixtures' shape)
# ---------------------------------------------------------------------------


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _health_up(base: str) -> bool:
    try:
        return httpx.get(f"{base}/api/ziv/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


@contextmanager
def live_relay():
    """The real app in a daemon thread on an ephemeral port, isolated the
    way the e2e fixtures isolate: a temp data dir + a short fake model,
    module state restored afterwards so nothing leaks into later runs."""
    import importlib

    import ziv_store
    import ziv_server

    tmp_data = HERE / "ziv_data_gallery_tmp"
    if tmp_data.exists():  # a crashed earlier run must not leak in
        shutil.rmtree(tmp_data)
    original_data_dir = ziv_store.DATA_DIR
    original_fake = ziv_server.FAKE_MODEL_SECONDS
    original_env = os.environ.get("ZIV_FAKE_MODEL_SECONDS")
    ziv_store.DATA_DIR = tmp_data
    os.environ["ZIV_FAKE_MODEL_SECONDS"] = FAKE_MODEL_SECONDS
    importlib.reload(ziv_server)

    port = free_port()
    import uvicorn

    config = uvicorn.Config(ziv_server.app, host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        wait_for(lambda: _health_up(base), 15, "the relay to start")
        yield SimpleNamespace(base=base, port=port)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        ziv_store.DATA_DIR = original_data_dir
        ziv_server.FAKE_MODEL_SECONDS = original_fake
        if original_env is None:
            os.environ.pop("ZIV_FAKE_MODEL_SECONDS", None)
        else:
            os.environ["ZIV_FAKE_MODEL_SECONDS"] = original_env
        importlib.reload(ziv_server)  # pristine module state, like the e2e


# ---------------------------------------------------------------------------
# the dev band page (sync Playwright, the record_beat.py shape)
# ---------------------------------------------------------------------------


def _present_for_capture(page) -> None:
    """The checklist's readability zoom + one presentational tweak: hide the
    PWA's long instructional paragraph (the 'Mic records → …' blurb) so
    badge, note, cells and wire log share one 3:2 frame. Everything the
    shots prove is untouched."""
    page.evaluate(
        """() => {
          const panel = document.querySelector('#cells').closest('.panel');
          for (const p of panel.querySelectorAll('p.cap')) {
            if (p.textContent.startsWith('Mic records')) p.style.display = 'none';
          }
          // The wire log prepends newest-first, so no locator's
          // scroll-into-view needs to move the WINDOW — freeze it at the
          // top so the badge/note header is in every frame.
          document.documentElement.style.overflow = 'hidden';
          document.body.style.overflow = 'hidden';
          document.body.style.zoom = '%s';
        }"""
        % ZOOM
    )


@contextmanager
def open_band(pw, base: str):
    """One fresh 3:2 context on the dev band: attached (badge visible, WS
    connected) and unlocked — the state every wire-level shot assumes."""
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": VW, "height": VH},
        device_scale_factor=2,  # 2520×1680 PNGs — text stays crisp on Devpost
    )
    page = context.new_page()
    page.goto(f"{base}/ziv_client/index.html", wait_until="domcontentloaded")
    page.locator("#queueBadge").wait_for(state="visible", timeout=10000)
    page.locator("#state").filter(has_text="connected").wait_for(timeout=10000)
    page.locator("#btnUnlock").click()
    _present_for_capture(page)
    try:
        yield SimpleNamespace(browser=browser, context=context, page=page)
    finally:
        browser.close()


def snap(page, name: str) -> Path:
    # wait_log's auto-scroll pulls the wire log to the viewport top, which
    # pushes the badge/note header out of frame — pin the scroll back up,
    # refresh the badge, and let the paint settle before the shutter.
    page.evaluate(
        "() => { window.scrollTo(0, 0);"
        " if (typeof pollQueueBadge === 'function') pollQueueBadge(); }"
    )
    page.wait_for_timeout(150)
    out = OUT_DIR / name
    page.screenshot(path=str(out))  # full viewport = 3:2 by construction
    return out


def wait_log(page, text: str, timeout_s: float = 10) -> None:
    page.locator("#log div").filter(has_text=text).first.wait_for(
        timeout=timeout_s * 1000)


def ensure_cells(page, minimum: int = 3) -> None:
    wait_for(
        lambda: page.locator("#cells .cell").count() >= minimum,
        5, f"the cells box to fill with {minimum}+ letters",
    )


def force_badge_poll(page) -> None:
    """Poll the badge now instead of waiting for the next 2 s tick."""
    page.evaluate("pollQueueBadge()")


def wait_channel_settled(d, base: str, quiet_s: float = 7.0,
                         timeout_s: float = 240.0) -> None:
    """Wait until the haptic channel is TRULY idle before the next shot.

    Residue is what made the give-up arc mushy on the first run: the badge
    reads `queue 0/8` the instant the drain STARTS (the gate pops the whole
    queue at the main close), while the replays keep playing under the turn
    lock — and any POST landing mid-drain is admitted as its own standalone
    turn once the lock frees. So settling means: gate queue empty, no armed
    redial, no turn in flight, and no close frame landing for quiet_s (a
    drain replays back-to-back ~5 s apart, so 7 s of silence means done).
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            depth = http_json("GET", f"{base}/api/ziv/health")["gate_queue"]
        except Exception:
            depth = -1
        note_hidden = d.page.locator("#redialNote").is_hidden()
        state_txt = d.page.locator("#state").inner_text()
        busy = "busy" in state_txt or state_txt.startswith("working")
        closes = d.page.locator("#log div").filter(
            has_text="end-of-message").count()
        d.page.wait_for_timeout(quiet_s * 1000)
        closes_after = d.page.locator("#log div").filter(
            has_text="end-of-message").count()
        if depth == 0 and note_hidden and not busy and closes == closes_after:
            return
    raise AssertionError("the haptic channel never settled")


# ---------------------------------------------------------------------------
# shot 1 — the whole turn vocabulary in one frame
# ---------------------------------------------------------------------------


def shot_turn_vocabulary(d, base: str) -> None:
    # A solo turn first, all the way to its close — so the log holds the
    # full vocabulary: kind cue → processing ticks → message text frame →
    # the cells (lit live in the box) → end-of-message close.
    d.page.locator("#msg").fill(STARTER)
    d.page.locator("#btnSend").click()
    d.page.wait_for_selector(f"text=message: {STARTER}", timeout=12000)
    fills = [spawn_fill(base, w) for w in ("alpha", "bravo", "charlie")]
    try:
        wait_log(d.page, "(queued)", 10)  # a fill announced itself mid-turn
    finally:
        for p in fills:
            p.wait(timeout=120)
    wait_log(d.page, "end-of-message", 60)   # the close, on the record
    wait_channel_settled(d, base)

    # A second, short message so the frame also shows a FRESH turn's cue
    # and cells mid-playback (the box lighting up as each cell lands).
    d.page.locator("#msg").fill("hi")
    d.page.locator("#btnSend").click()
    d.page.wait_for_selector("text=message: hi", timeout=12000)
    wait_for(
        lambda: d.page.locator("#cells .cell.on").count() >= 1,
        8, "a lit cell (playback made visible)",
    )
    snap(d.page, "01-turn-vocabulary.png")
    wait_channel_settled(d, base)


# ---------------------------------------------------------------------------
# shot 2 — the badge in its two states (two files)
# ---------------------------------------------------------------------------


def shot_badge_states(d, base: str) -> None:
    warm = "warm up the queue"  # 14 letters ≈ 7 s of playback — fill window
    d.page.locator("#msg").fill(warm)
    d.page.locator("#btnSend").click()
    d.page.wait_for_selector(f"text=message: {warm}", timeout=12000)

    # State A, exactly as the checklist names it: queue 3/8 · reminders 0/64.
    fills = [spawn_fill(base, w) for w in ("alpha", "bravo", "charlie")]
    try:
        wait_for(
            lambda: http_json("GET", f"{base}/api/ziv/health")["gate_queue"] == 3,
            15, "the queue to reach 3/8",
        )
        force_badge_poll(d.page)
        wait_for(
            lambda: d.page.locator("#queueBadge")
            .filter(has_text="queue 3/8").is_visible(),
            6, "queue 3/8 to render on the badge",
        )
        ensure_cells(d.page, 2)
        snap(d.page, "02-badge-queue3.png")
    finally:
        for p in fills:
            p.wait(timeout=120)

    # State B: fill to the cap while the turn still plays (parallel spawns —
    # sequential spawns may land after the turn's playback window closes),
    # then a real click for the victim — the refusal renders loud.
    sps = [spawn_fill(base, w)
           for w in ("delta", "echo", "foxtrot", "golf", "hotel")]
    for p in sps:
        p.wait(timeout=120)
    force_badge_poll(d.page)
    wait_for(
        lambda: d.page.locator("#queueBadge")
        .filter(has_text="refusing — queue full (8/8)").is_visible(),
        10, "the badge to show the full queue",
    )
    d.page.locator("#msg").fill("nine")
    d.page.locator("#btnSend").click()
    d.page.locator("#state").filter(has_text="wrist is busy").wait_for(
        timeout=8000)
    d.page.locator("#redialNote").wait_for(state="visible", timeout=5000)
    wait_log(d.page, "✋ refused", 5)
    snap(d.page, "02-badge-refusing.png")

    # The dismissal comes free: the armed redial resends "nine" on the
    # freeing close — the same mechanics shot 03 documents.
    wait_log(d.page, "POST ok", 90)
    wait_for(
        lambda: d.page.locator("#queueBadge")
        .filter(has_text="queue 0/8").is_visible(),
        120, "the queue to drain",
    )
    # The drain KEEPS playing after the badge empties (the gate pops the
    # whole queue at the main close); settle before the next shot.
    wait_channel_settled(d, base)


# ---------------------------------------------------------------------------
# shot 3 — the redial lifecycle: three tries → red dead end → manual send ok
# ---------------------------------------------------------------------------


def shot_redial(d, base: str) -> None:
    # The give-up e2e's deterministic arc: every POST the PAGE makes is
    # refused (routed 429s), while server-side starters supply the free
    # closes that trigger the redials. Three chances, three refusals,
    # dead end. The route arms BEFORE the victim's click, so the victim
    # is refused too and the note arms with a full 3-chance budget.
    def refuse_page_posts(route):
        route.fulfill(
            status=429,
            content_type="application/json",
            body=json.dumps({"detail":
                             "message rejected: the replay queue is full "
                             "(8 queued) — the wearer releases it after the "
                             "current turn; try again later"}),
        )

    d.page.route("**/api/ziv/message", refuse_page_posts)
    victim = "call me back"
    d.page.locator("#msg").fill(victim)
    d.page.locator("#btnSend").click()
    note = d.page.locator("#redialNote")
    note.wait_for(state="visible", timeout=5000)
    d.page.locator("#state").filter(has_text="wrist is busy").wait_for(
        timeout=8000)
    try:
        for turn in range(3):
            r = http_json("POST", f"{base}/api/ziv/message",
                          {"text": f"starter{turn}"})
            assert r.get("event") == "turn_complete", r
            if turn < 2:
                # Positive transition: wait for the note to SAY the
                # next-lower budget (a note stuck at the previous budget
                # would pass a bare "chances left" check).
                expected = 2 - turn
                wait_for(
                    lambda: victim in note.inner_text()
                    and f"({expected} chances left)" in note.inner_text(),
                    10, f"the redial to re-arm with {expected} chances",
                )
        wait_for(lambda: "gave up after 3 tries" in note.inner_text(),
                 10, "the dead-end note")
        wait_log(d.page, "↹ redial gave up", 5)
        snap(d.page, "03-redial-dead-end.png")
    finally:
        d.page.unroute("**/api/ziv/message")

    # The recovery, on the same screen: the wearer sends manually (the
    # note's own advice) and the log walks give-up → cancelled → POST ok.
    # wait_log("POST ok") would match the STALE ok lines earlier shots left
    # in the 60-entry log — count the lines and wait for a NEW one.
    oks_before = d.page.locator("#log div").filter(
        has_text="POST ok").count()
    d.page.locator("#btnSend").click()
    note.wait_for(state="hidden", timeout=10000)
    wait_for(
        lambda: d.page.locator("#log div").filter(
            has_text="POST ok").count() > oks_before,
        30, "the manual send's own POST ok line",
    )
    d.page.wait_for_timeout(400)  # let the log paint the whole arc
    snap(d.page, "03-redial-lifecycle.png")
    wait_channel_settled(d, base)


# ---------------------------------------------------------------------------
# shot 4 — a reminder arriving unprompted
# ---------------------------------------------------------------------------


def shot_reminder(d, base: str) -> None:
    fire_at = int(time.time()) + 6
    r = http_json("POST", f"{base}/api/ziv/schedule",
                  {"fire_at": fire_at, "text": "pills"})
    assert r.get("scheduled") is True, r
    wait_log(d.page, "reminder: pills", 20)      # the mark's text frame
    ensure_cells(d.page, 3)                       # Z-I-V in the cells box
    # Snap the instant the tail lands — waiting longer lets anything queued
    # behind the reminder flood the log top and bury its narration line.
    wait_log(d.page, "triple-pulse", 15)
    snap(d.page, "04-reminder-turn.png")
    http_json("DELETE", f"{base}/api/ziv/schedule")
    wait_channel_settled(d, base)


# ---------------------------------------------------------------------------
# shot 5 — the operator view (health JSON, rendered and framed 3:2)
# ---------------------------------------------------------------------------


def shot_health(pw, base: str) -> None:
    # One pending reminder on the board (a future fire — not a race), so
    # schedule_pending/schedule_cap render with real, non-zero depth.
    http_json("POST", f"{base}/api/ziv/schedule",
              {"fire_at": int(time.time()) + 300, "text": "demo reminder"})
    body = http_json("GET", f"{base}/api/ziv/health")
    pretty = json.dumps(body, indent=2)
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_context(
            viewport={"width": VW, "height": VH}, device_scale_factor=2,
        ).new_page()
        page.set_content(
            """<html><head><meta charset="utf-8"><style>
                 body { margin: 0; background: #0e1116; color: #e8edf4;
                        font: 11px/1.25 Consolas, 'Cascadia Mono', monospace; }
                 pre { white-space: pre; color: #e8edf4;
                       padding: 22px 0 0 28px; }
               </style></head><body><pre id="health"></pre></body></html>"""
        )
        page.evaluate(
            "text => document.getElementById('health').textContent = text",
            pretty,
        )
        page.wait_for_timeout(150)
        snap(page, "05-health-json.png")
    finally:
        browser.close()
    http_json("DELETE", f"{base}/api/ziv/schedule")


# ---------------------------------------------------------------------------
# shot 6 — the proof stack: pytest tail beside the firmware bench line
# ---------------------------------------------------------------------------


def shot_proof(pw) -> None:
    # One line per column — the summary lines themselves. A multi-line
    # pytest tail drags in DeprecationWarning text; and the bench column
    # wants the counts line the C binary prints, not just "bench suite:
    # PASS". (Both children may print non-ASCII; pin their pipes UTF-8 —
    # the same trap the CI suite hit.)
    pytest_line = "(pytest produced no summary line)"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "not e2e", "-q", "--no-header"],
            cwd=HERE, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900,
        )
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        summary = next(
            (ln for ln in reversed(lines) if re.search(r"\d+ passed", ln)), None)
        pytest_line = summary or (lines[-1] if lines else pytest_line)
    except Exception as exc:
        pytest_line = f"(pytest failed to run: {exc})"

    bench_counts = "(bench counts not found)"
    bench_pass = ""
    runner = HERE.parent / "firmware" / "haptic_out" / "run_tests.py"
    if runner.is_file():
        try:
            proc = subprocess.run(
                [sys.executable, str(runner)],
                cwd=str(runner.parent), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=900,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            counts = re.search(r"\d+ checks, \d+ failures", out)
            if counts:
                bench_counts = counts.group(0)
            passed = re.search(r"^bench suite: .*$", out, re.M)
            if passed:
                bench_pass = passed.group(0).strip()
        except Exception as exc:
            bench_counts = f"(bench suite failed to run: {exc})"

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_context(
            viewport={"width": VW, "height": VH}, device_scale_factor=2,
        ).new_page()
        page.set_content(
            """<html><head><meta charset="utf-8"><style>
                 * { box-sizing: border-box; }
                 html, body { height: 100%; }
                 body { margin: 0; background: #0e1116; color: #e8edf4;
                        font: 22px/2.0 Consolas, 'Cascadia Mono', monospace;
                        display: flex; }
                 .col { flex: 1 1 50%; min-width: 0; padding: 24px 30px;
                        border-right: 1px solid #263041;
                        display: flex; flex-direction: column;
                        justify-content: center; }
                 .col:last-child { border-right: none; }
                 h2 { font: 600 15px system-ui, sans-serif; color: #8b98ab;
                      letter-spacing: 1px; margin: 0 0 18px; }
                 pre { white-space: pre-wrap; margin: 0; }
               </style></head><body>
                 <div class="col"><h2>AGENT — PYTEST (HERMETIC SUITE)</h2><pre>"""
            + esc(pytest_line)
            + """</pre></div>
                 <div class="col"><h2>FIRMWARE — HAPTIC_OUT BENCH SUITE</h2><pre>"""
            + esc(bench_counts + ("\n" + bench_pass if bench_pass else ""))
            + """</pre></div>
               </body></html>"""
        )
        page.wait_for_timeout(150)
        snap(page, "06-test-proof.png")
    finally:
        browser.close()


# ---------------------------------------------------------------------------
# shot 7 — fire-while-away: inbox:stored → reattach → the self-naming replay
# ---------------------------------------------------------------------------


def shot_fire_while_away(pw, base: str) -> None:
    # The band must be OFF the wire for the store to engage: no context is
    # open here, so hub.count == 0 and the relay stores instead of playing.
    # Leftovers from earlier shots would replay first and muddy the frame,
    # so the inbox starts empty.
    try:
        http_json("DELETE", f"{base}/api/ziv/inbox")
    except urllib.error.HTTPError:
        pass
    for msg in ("stored while away", "who is calling"):
        r = http_json("POST", f"{base}/api/ziv/message", {"text": msg})
        assert r.get("event") == "inbox:stored", (msg, r)

    # Reattach: the hello reports the pending count and each replay arrives
    # as a self-naming turn — mark first (Z-I-V cells), content after.
    with open_band(pw, base) as d:
        wait_log(d.page, "relay hello", 10)
        wait_log(d.page, "stored while away", 30)
        wait_log(d.page, "end-of-message", 60)
        ensure_cells(d.page, 3)
        d.page.wait_for_timeout(300)
        snap(d.page, "07-fire-while-away.png")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def write_captions() -> Path:
    """Emit the per-image captions beside the shots (Devpost's gallery has
    a caption field per image)."""
    lines = [
        "# Gallery captions — paste one per image into Devpost's caption field",
        "#",
        "# Project details → Image gallery → each uploaded image gets a caption",
        "# box. Regenerated by record_gallery.py — edit CAPTIONS there, not here.",
        "",
    ]
    for name in sorted(CAPTIONS):
        lines += [f"## {name}", "", CAPTIONS[name], ""]
    out = OUT_DIR / "CAPTIONS.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing — "
              "pip install playwright && playwright install chromium")
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        with live_relay() as relay:
            base = relay.base
            # A fresh wearer: a crashed earlier run's store must not leak
            # stale reminders into the badge or the health payload.
            for path in ("api/ziv/schedule", "api/ziv/inbox"):
                try:
                    http_json("DELETE", f"{base}/{path}")
                except urllib.error.HTTPError:
                    pass
            # The wearer's fastest pace (structure universal, parameters
            # personal) — the same move as the e2e suite.
            http_json("POST", f"{base}/api/ziv/prefs",
                      {"cell_gap_ms": CELL_GAP_MS})

            with open_band(pw, base) as d:
                shot_turn_vocabulary(d, base)
                shot_badge_states(d, base)
                shot_redial(d, base)
                shot_reminder(d, base)
            # The reminder's full turn must finish before shot 5 freezes
            # the telemetry numbers (the reminder is still playing during
            # the shot-4 dwell — it lands in health a moment later).
            with open_band(pw, base) as d:
                wait_channel_settled(d, base)
            shot_health(pw, base)
            shot_fire_while_away(pw, base)
        # The proof shot runs against the restored tree (the relay context
        # is closed): real `pytest -m "not e2e"` + the firmware bench line.
        shot_proof(pw)

    names = sorted(p.name for p in OUT_DIR.glob("*.png"))
    print("gallery recorded:")
    for n in names:
        print("  ", OUT_DIR / n)
    print(f"{len(names)} shots in {OUT_DIR}")
    print(f"captions: {write_captions()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
