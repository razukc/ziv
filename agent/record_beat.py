"""Record the 0:20–1:10 beat of the demo video, scripted and timed like the e2e.

Uses the same in-process timing trick the e2e suite proved: fills are fired
the instant the starter's cells frame appears (zero human/tool latency), so
the gate is reliably full when the victim's real click lands.

Run (server already up on :8787, FAKE_MODEL_SECONDS=8, cell_gap 250):
    python record_beat.py
Output: demo_beat.webm (+ demo_beat_trace.zip on failure)
"""

import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8787"
OUT = Path("demo_beat.webm")

FILLS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]


def fill_via_http():
    """Fire the 8 queue-filling POSTs in parallel, no waiting."""
    procs = [
        subprocess.Popen(
            [
                sys.executable, "-c",
                "import urllib.request,sys;"
                "req=urllib.request.Request("
                f"'{BASE}/api/ziv/message',"
                "data=b'{\"text\": \"" + w + "\"}',"
                "headers={'Content-Type':'application/json'});"
                "urllib.request.urlopen(req, timeout=120)",
            ]
        )
        for w in FILLS
    ]
    return procs


def main() -> int:
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

        # Beat 1: the starter turn via a real click.
        page.locator("#msg").fill("hold that thought")
        page.locator("#btnSend").click()
        # In-process sync point: the instant playback begins, fill the queue.
        page.wait_for_selector("text=message: hold that thought", timeout=12000)
        procs = fill_via_http()
        for p in procs:
            p.wait(timeout=120)

        # The victim: a real click, now that the gate is provably full.
        page.locator("#msg").fill("nine")
        page.locator("#btnSend").click()
        page.locator("#state").filter(has_text="wrist is busy").wait_for(timeout=8000)
        note = page.locator("#redialNote")
        note.wait_for(state="visible", timeout=5000)
        assert "nine" in note.inner_text() and "3 chances left" in note.inner_text()

        # The redial: fires on the freeing close, on camera.
        page.locator("#log div").filter(
            has_text="↻ redial — resending"
        ).first.wait_for(timeout=60000)
        page.locator("#log div").filter(has_text="POST ok").first.wait_for(timeout=60000)
        # Badge drains back to empty (all eight replays complete).
        page.locator("#queueBadge").filter(has_text="queue 0/8").wait_for(timeout=120000)

        time.sleep(1.0)  # settle the final frame
        video = page.video
        context.close()  # flush the recording
        path = video.path() if video else None
        browser.close()

    if path:
        Path(path).rename(OUT)
        print("saved:", OUT.resolve())
    print("beat recorded: starter -> 8 fills -> refusal -> redial -> drained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
