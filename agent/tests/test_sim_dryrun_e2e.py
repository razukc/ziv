"""End-to-end: the simulation dry-run panel replays a pipeline with verdicts.

The dry-run (frontend "▶ sim dry-run" next to edit/variation) replays a
composed pipeline step-by-step with real pacing and simulated pass/fail. Two
properties matter and are asserted here:

1. Determinism — same plan + same seed = the same outcome. The panel's
   "↻ replay" re-runs the identical scenario, so both runs must produce the
   exact same summary while the seed chip stays unchanged.
2. Structural checks — a step that violates skill metadata fails the same way
   every time, regardless of seed. This test reorders the mock pipeline with
   the human edit controls (validation ahead of every training step) and the
   replay must halt at step 1 with the "no trained policy to validate" reason.

Both checks run against the real UI in mock mode — no backend compose, no
credits. The replay also exercises its pause control mid-run to prove the
elapsed clock really freezes.

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m \"not e2e\"`` — run it explicitly with ``pytest -m e2e``.
"""
import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


def test_sim_dryrun_replay_is_deterministic_and_catches_bad_ordering():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)

        # --- Compose a mock pipeline (unitree-g1 default) --------------------
        page.locator("textarea").fill("Pick up the red block and place it on the blue platform")
        page.get_by_role("button", name="compose", exact=True).click()
        page.get_by_role("button", name=">>> compose another").wait_for(timeout=25000)

        # --- Run #1: open the dry-run and watch it complete ------------------
        page.get_by_test_id("open-sim").click()
        page.locator('[data-testid="dryrun-panel"]').wait_for(timeout=5000)
        preflight = page.locator('[data-testid="dryrun-preflight"]').inner_text()
        assert "preflight ok" in preflight, preflight

        # Pause mid-run: the elapsed clock must freeze while paused.
        pause = page.get_by_test_id("dryrun-pause")
        pause.wait_for(timeout=5000)
        page.wait_for_timeout(1800)  # let a few steps run first
        pause.click()
        elapsed = page.get_by_test_id("dryrun-elapsed")
        frozen = elapsed.inner_text()
        assert "paused" in frozen, frozen
        page.wait_for_timeout(1600)
        still = elapsed.inner_text()
        print(f"paused elapsed: {frozen.strip()} -> {still.strip()}")
        assert still == frozen, f"elapsed must freeze while paused: {frozen} vs {still}"
        pause.click()  # resume

        summary = page.locator('[data-testid="dryrun-summary"]')
        summary.wait_for(timeout=40000)
        run1 = summary.inner_text().strip()
        seed1 = page.get_by_test_id("dryrun-seed").inner_text().strip()
        print(f"run #1: {run1}")
        if "passed" in run1:
            assert "6/6 steps passed" in run1, run1
        else:
            assert "halted at step" in run1, run1

        # --- Replay: same seed must reproduce the identical outcome ----------
        page.get_by_test_id("dryrun-replay").click()
        # The old summary unmounts while the rerun replays, then re-mounts.
        page.wait_for_function(
            "document.querySelector('[data-testid=dryrun-summary]') === null",
            timeout=5000,
        )
        summary.wait_for(timeout=40000)
        run2 = summary.inner_text().strip()
        seed2 = page.get_by_test_id("dryrun-seed").inner_text().strip()
        print(f"run #2: {run2}")
        assert run2 == run1, f"deterministic replay must match: {run1} vs {run2}"
        assert seed2 == seed1, "replay must keep the same seed"

        # --- Reorder with the edit controls so validation runs first --------
        # Moving policy-validation (step 5) above every training step makes the
        # dry-run halt at step 1: structurally, there is nothing to validate.
        page.get_by_test_id("dryrun-panel").get_by_role("button", name="✕", exact=True).click()
        page.get_by_role("button", name="edit steps", exact=False).click()
        row = page.get_by_test_id("step-row-policy-validation")
        for _ in range(4):
            row.get_by_title("move up").click()
        page.get_by_role("button", name="done", exact=True).click()

        # --- Run #3: the structural check must halt at step 1 instantly ------
        page.get_by_test_id("open-sim").click()
        pf3 = page.locator('[data-testid="dryrun-preflight"]').inner_text()
        print(f"preflight (edited): {pf3.strip()}")
        assert "preflight" in pf3 and "no trained policy" in pf3, pf3

        summary3 = page.locator('[data-testid="dryrun-summary"]')
        summary3.wait_for(timeout=15000)  # structural halt at step 1 ~ instant
        run3 = summary3.inner_text().strip()
        print(f"run #3: {run3}")
        assert "halted at step 1" in run3, run3
        assert "no trained policy" in run3, run3
        # The blocked step carries the structural verdict regardless of seed.
        verdict1 = page.get_by_test_id("dryrun-verdict-1").inner_text()
        assert verdict1 == "FAIL", verdict1


def test_sim_dryrun_verdict_persists_and_renders_on_reopen():
    """The last dry-run verdict lands on the history card, and reopening the
    pipeline renders it instantly (no 14s replay) with the same seed chip."""
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)

        # --- Compose a mock pipeline and run the dry-run to completion ------
        page.locator("textarea").fill("Pick up the red block and place it on the blue platform")
        page.get_by_role("button", name="compose", exact=True).click()
        page.get_by_role("button", name=">>> compose another").wait_for(timeout=25000)
        page.get_by_test_id("open-sim").click()
        summary = page.locator('[data-testid="dryrun-summary"]')
        summary.wait_for(timeout=40000)
        run1 = summary.inner_text().strip()
        seed1 = page.get_by_test_id("dryrun-seed").inner_text().strip()
        assert "passed" in run1 or "halted" in run1, run1

        # --- The newest history card carries the verdict badge --------------
        badge = page.get_by_test_id("history-dryrun").first
        badge.wait_for(timeout=5000)
        badge_text = badge.inner_text().strip()
        print(f"card badge: {badge_text}")
        assert "pass" in badge_text or "fail" in badge_text, badge_text
        assert seed1.replace("seed ", "") in badge_text, f"badge must show the seed: {badge_text}"

        # --- Reopen from history: stored verdict renders instantly -----------
        page.get_by_test_id("dryrun-panel").get_by_role("button", name="✕", exact=True).click()
        # Accessible name carries the "↪" glyph, so match the label substring.
        page.get_by_role("button", name="open in editor").first.click()
        page.get_by_test_id("open-sim").wait_for(timeout=8000)
        page.get_by_test_id("open-sim").click()
        summary2 = page.locator('[data-testid="dryrun-summary"]')
        summary2.wait_for(timeout=3000)  # instant — no replay of the 14s run
        run2 = summary2.inner_text().strip()
        elapsed2 = page.get_by_test_id("dryrun-elapsed").inner_text().strip()
        seed2 = page.get_by_test_id("dryrun-seed").inner_text().strip()
        print(f"reopened: {run2} | {elapsed2} | {seed2}")
        assert run2 == run1, f"reopen must show the stored verdict: {run1} vs {run2}"
        assert seed2 == seed1, "reopen must keep the stored seed"
        assert "last run" in elapsed2, elapsed2

        # --- Replaying from the stored state reproduces the outcome ----------
        page.get_by_test_id("dryrun-replay").click()
        page.wait_for_function(
            "document.querySelector('[data-testid=dryrun-summary]') === null",
            timeout=5000,
        )
        summary.wait_for(timeout=40000)
        run3 = summary.inner_text().strip()
        seed3 = page.get_by_test_id("dryrun-seed").inner_text().strip()
        print(f"replay after reopen: {run3} | {seed3}")
        assert run3 == run1, f"replay from stored state must match: {run1} vs {run3}"
        assert seed3 == seed1, "replay from stored state must keep the seed"
