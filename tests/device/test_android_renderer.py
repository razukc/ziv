"""The real relay, over TCP, driven by the native Android renderer on an emulator
(docs/ARCHITECTURE.md §10, tier 4: a device program under its own runtime).

A relay under uvicorn on an ephemeral loopback port, as ``tests/relay_live.py``
boots it; the debug APK (``android/app/build/outputs/apk/debug/app-debug.apk``)
installed over adb on the first attached emulator, where the host's loopback is
``10.0.2.2``; the app launched with the relay URL and a fresh enroll code as
intent extras (a debug-build affordance). The test then submits utterances over
HTTP and waits for the relay to see ``played`` — the emulator has no motor to
feel, so ``silent_ok`` lets the device play on its clock; the test is about the
protocol. ``adb logcat`` (the app's tag only) is attached to every failure.

Marked ``device``: deselected by default (pyproject ``addopts``); run with
``.venv/bin/python -m pytest -m device tests/device``. Skips cleanly, naming the
reason, when adb, the APK or a booted emulator is missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from relay_live import LiveRelay, wait_until

pytestmark = pytest.mark.device

REPO_ROOT = Path(__file__).resolve().parents[2]
APK = REPO_ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
PACKAGE = "ziv.android"
ACTIVITY = f"{PACKAGE}/.MainActivity"
LOG_TAG = "ZivRenderer"
CONNECT_TIMEOUT_S = 90.0
PLAY_TIMEOUT_S = 90.0


def find_adb() -> str | None:
    for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), str(Path.home() / "android-sdk")):
        if root and (Path(root) / "platform-tools" / "adb").is_file():
            return str(Path(root) / "platform-tools" / "adb")
    return shutil.which("adb")


ADB = find_adb()


class Adb:
    """One attached device, every call bounded by a timeout."""

    def __init__(self, serial: str) -> None:
        assert ADB is not None
        self.serial = serial

    def run(self, *args: str, timeout: float = 60.0, check: bool = True) -> subprocess.CompletedProcess[str]:
        r = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            raise AssertionError(f"adb {' '.join(args)} failed ({r.returncode}): {r.stdout[-800:]} {r.stderr[-800:]}")
        return r

    def shell(self, *args: str, timeout: float = 60.0, check: bool = True) -> str:
        return self.run("shell", *args, timeout=timeout, check=check).stdout.strip()

    def logcat(self, lines: int = 80) -> str:
        r = self.run("logcat", "-d", "-v", "time", "-s", f"{LOG_TAG}:D", "AndroidRuntime:E", "ActivityManager:W", timeout=30, check=False)
        return "\n".join(r.stdout.splitlines()[-lines:])

    @property
    def is_emulator(self) -> bool:
        return self.serial.startswith("emulator-")


def attached_devices() -> list[str]:
    if ADB is None:
        return []
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out


@pytest.fixture(scope="session")
def adb() -> Adb:
    if ADB is None:
        pytest.skip("adb not found (set ANDROID_HOME, or put platform-tools on PATH)")
    if not APK.is_file():
        pytest.skip(f"debug APK not built at {APK}; run: cd android && ./gradlew :app:assembleDebug")
    serials = attached_devices()
    if not serials:
        pytest.skip("no Android emulator or device attached (adb devices lists none in state 'device')")
    serial = os.environ.get("ZIV_ANDROID_SERIAL") or serials[0]
    dev = Adb(serial)
    if not dev.is_emulator and not os.environ.get("ZIV_RELAY_HOST"):
        pytest.skip("a physical phone needs ZIV_RELAY_HOST (this machine's LAN address) and a relay bound to it; the "
                    "in-process relay here binds loopback, which only an emulator reaches (as 10.0.2.2)")
    wait_until(lambda: dev.shell("getprop", "sys.boot_completed", check=False) == "1", "the emulator to finish booting", timeout=180, every=2.0)
    dev.run("install", "-r", "-g", str(APK), timeout=180)
    dev.shell("pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS", check=False)
    return dev


@pytest.fixture()
def relay(tmp_path, adb):
    with LiveRelay(tmp_path) as live:
        yield live


def relay_host(adb: Adb) -> str:
    return "10.0.2.2" if adb.is_emulator else os.environ["ZIV_RELAY_HOST"]


def launch(adb: Adb, relay: LiveRelay, *, enroll_code: str | None, fresh: bool = True) -> None:
    """Start the app. With ``fresh`` its data is cleared first, so it enrolls anew with ``enroll_code``;
    without, it comes back with the saved relay, key and queue (no extras)."""
    adb.shell("am", "force-stop", PACKAGE, check=False)
    if fresh:
        adb.shell("pm", "clear", PACKAGE, check=False)
        # pm clear resets runtime grants; without this the notification-permission dialog sits on
        # top of the task and a later relaunch never recreates the activity underneath it
        adb.shell("pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS", check=False)
    adb.run("logcat", "-c", check=False)
    args = ["am", "start", "-W", "-n", ACTIVITY]
    if enroll_code is not None:
        url = f"http://{relay_host(adb)}:{relay.port}"
        args += ["--es", "relay_url", url, "--es", "enroll_code", enroll_code, "--es", "profile", "single_actuator",
                 "--ez", "silent_ok", "true"]
    adb.shell(*args, timeout=60)


def wait_with_logcat(adb: Adb, pred: Callable[[], bool], what: str, timeout: float) -> None:
    try:
        wait_until(pred, what, timeout=timeout, every=0.25)
    except AssertionError as exc:
        raise AssertionError(f"{exc}\n--- adb logcat ({LOG_TAG}) ---\n{adb.logcat()}") from None


def connected_device(relay: LiveRelay, adb: Adb) -> dict:
    found: dict = {}

    def check() -> bool:
        nonlocal found
        devices = relay.get("/devices").json()
        connected = [d for d in devices if d["connected"]]
        if connected:
            found = connected[0]
            return True
        return False

    wait_with_logcat(adb, check, "the app to enroll and say hello (GET /devices shows it connected)", CONNECT_TIMEOUT_S)
    return found


def wait_played(relay: LiveRelay, adb: Adb, uid: str) -> dict:
    last: dict = {}

    def done() -> bool:
        nonlocal last
        last = relay.view(uid)
        return last["state"] in ("played", "failed", "expired", "cancelled")

    wait_with_logcat(adb, done, f"utterance {uid} to be played (last: {last.get('state')} {last.get('reason')})", PLAY_TIMEOUT_S)
    assert last["state"] == "played", f"{last}\n--- adb logcat ---\n{adb.logcat()}"
    return last


def test_the_app_enrolls_by_code_connects_and_plays_a_message_to_played(relay: LiveRelay, adb: Adb):
    launch(adb, relay, enroll_code=relay.enroll_code)
    device = connected_device(relay, adb)
    assert device["profile"] == "single_actuator" and device["primary"] is True
    assert relay.client.get("/health").json()["devices_connected"] == 1

    r = relay.post("/utterances", {"text": "Go now!", "label": "mum"})
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["words"] == ["go", "now"]
    final = wait_played(relay, adb, view["id"])
    assert final["device"] == device["device"] and final["reason"] is None
    # the app's own account of it: a hello, the open, progress at cue / each word / close, then played — never the words
    log = adb.logcat(400)
    assert "→ hello profile=single_actuator" in log, log
    assert f"progress id={view['id']} close" in log and f"played id={view['id']}" in log, log
    assert "go" not in [token for line in log.splitlines() if "utterance.open" in line for token in line.split()], "no words in the wire log"


def test_a_compose_reaches_the_app_as_body_pending_then_plays_the_echoed_words(relay: LiveRelay, adb: Adb):
    launch(adb, relay, enroll_code=relay.enroll_code)
    connected_device(relay, adb)
    r = relay.post("/compose", {"intent": "Meds now", "label": "agent"})
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["words"] == ["meds", "now"] and view["source"] == "echo" and view["kind"] == "reminder"
    final = wait_played(relay, adb, view["id"])
    assert final["words"] == ["meds", "now"] and final["source"] == "echo"
    log = adb.logcat(400)
    assert f"utterance.open id={view['id']} kind=reminder words=0 body_pending" in log, log
    assert f"utterance.body id={view['id']} words=2" in log, log


def test_a_process_restart_comes_back_with_the_saved_key_and_last_acked(relay: LiveRelay, adb: Adb):
    launch(adb, relay, enroll_code=relay.enroll_code)
    device = connected_device(relay, adb)
    first = relay.post("/utterances", {"text": "one"}).json()
    wait_played(relay, adb, first["id"])

    # kill the process; the activity relaunch carries no extras, so everything comes from private storage and SQLite
    launch(adb, relay, enroll_code=None, fresh=False)
    wait_with_logcat(adb, lambda: f"last_acked={first['id']}" in adb.logcat(200), "a fresh hello carrying last_acked", CONNECT_TIMEOUT_S)
    again = connected_device(relay, adb)
    assert again["device"] == device["device"], "the same enrolled device, not a second enrollment"
    assert len(relay.get("/devices").json()) == 1

    second = relay.post("/utterances", {"text": "two"}).json()
    wait_played(relay, adb, second["id"])
    time.sleep(0.2)
    assert relay.client.get("/health").json()["outbox"]["played"] == 2
