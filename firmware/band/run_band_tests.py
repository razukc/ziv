#!/usr/bin/env python3
"""run_band_tests.py — build and run the band module's host proofs.

Four steps, in order, each a gate (the first failure stops the run):

  1. band_tests          the C unit tests: the utterance decoder, the queue
                         and its file store, the turn's compiled timelines
                         against expectations hand-derived from haptic_timing.h
                         on both profiles, the beat mode, the controls, and the
                         transport protocol against a scripted frame adapter
  2. host_player         the conformance player, built to
                         firmware/app/ziv_qemu/host_player (the path
                         conformance/README.md names), then held to the
                         reference renderer on BOTH profiles by
                         conformance/run.py (12/12 each)
  3. host_transport_test the transport over real loopback TCP against
                         host/fake_relay.py, which validates every up frame
                         against the wire models and asserts the frame order

Same compiler discipline as the other runners (cc/gcc/clang/tcc, `zig cc`,
the ziglang pip package, then WSL; -std=c11 -Wall -Wextra -Werror).  The
conformance and fake-relay steps import `ziv`, so they run with the agent
venv's interpreter (agent/venv/bin/python); plain python3 runs this script.

Exit codes: 0 all green; 1 a build or a check failed; 2 the environment is
missing (no C compiler, or no venv interpreter for the ziv-importing steps).
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FW = REPO / "firmware"
HAPTIC_OUT = FW / "haptic_out"
CJSON = FW / "third_party" / "cJSON"
HOST = HERE / "host"
PLAYER_OUT = FW / "app" / "ziv_qemu" / ("host_player.exe" if sys.platform == "win32" else "host_player")
EXE = ".exe" if sys.platform == "win32" else ""
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
INCLUDES = ["-I", str(HAPTIC_OUT), "-I", str(HERE), "-I", str(HOST), "-I", str(CJSON)]

CORE = [HAPTIC_OUT / "haptic_out.c", HAPTIC_OUT / "drv2605.c", HAPTIC_OUT / "mock_drv2605.c",
        CJSON / "cJSON.c", HERE / "utterance.c", HERE / "turn.c"]
BAND = [HERE / "queue.c", HERE / "transport.c"]

VENV_PY = REPO / "agent" / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
PROFILES = ("six_actuator", "single_actuator")


def find_cc():
    for tool in ("cc", "gcc", "clang", "tcc"):
        path = shutil.which(tool)
        if path:
            return [path]
    if shutil.which("zig"):
        return ["zig", "cc"]
    probe = subprocess.run([sys.executable, "-m", "ziglang", "version"], capture_output=True, text=True, timeout=120)
    if probe.returncode == 0 and probe.stdout.strip():
        return [sys.executable, "-m", "ziglang", "cc"]
    return None


def build(cc, out: Path, srcs) -> bool:
    argv = [*cc, *CFLAGS, *INCLUDES, "-o", str(out), *[str(s) for s in srcs]]
    print("+", " ".join(argv))
    return subprocess.run(argv, cwd=REPO).returncode == 0


def main() -> int:
    cc = find_cc()
    if cc is None:
        print("no C compiler found (tried cc/gcc/clang/tcc/zig). install one, e.g. 'sudo apt install gcc'.")
        return 2
    venv_py = VENV_PY if VENV_PY.exists() else None
    if venv_py is None:
        print(f"no venv interpreter at {VENV_PY}: the conformance and fake-relay steps import ziv and need it.")
        return 2

    # 1. the C unit tests
    tests_bin = HOST / f"band_tests{EXE}"
    if not build(cc, tests_bin, [*CORE, *BAND, HOST / "queue_file_host.c", HOST / "test_band.c"]):
        print("band tests: build failed")
        return 1
    env = dict(os.environ, BAND_TEST_QUEUE_FILE=str(HOST / "band_test_queue.bin"))
    r = subprocess.run([str(tests_bin)], cwd=HOST, env=env)
    if r.returncode != 0:
        print("band tests: FAIL (exit %d)" % r.returncode)
        return 1
    print("band tests: PASS")

    # 2. the conformance player, on both profiles
    if not build(cc, PLAYER_OUT, [*CORE, HOST / "host_player.c"]):
        print("host_player: build failed")
        return 1
    for profile in PROFILES:
        argv = [str(venv_py), str(REPO / "conformance" / "run.py"), "--player",
                os.path.relpath(PLAYER_OUT, REPO), "--profile", profile]
        print("+", " ".join(argv))
        r = subprocess.run(argv, cwd=REPO)
        if r.returncode != 0:
            print(f"conformance {profile}: FAIL (exit {r.returncode})")
            return 1
    print("conformance: PASS on both profiles")

    # 3. the transport over loopback against the fake relay
    tt_bin = HOST / f"host_transport_test{EXE}"
    if not build(cc, tt_bin, [*CORE, *BAND, HOST / "frame_tcp_host.c", HOST / "host_transport_test.c"]):
        print("host_transport_test: build failed")
        return 1
    relay = subprocess.Popen([str(venv_py), str(HOST / "fake_relay.py")], cwd=REPO,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    first = relay.stdout.readline().strip()
    if not first.startswith("port "):
        print("fake relay did not start:", first, relay.stdout.read())
        relay.kill()
        return 1
    port = first.split()[1]
    print(f"+ fake_relay.py on 127.0.0.1:{port}")
    t0 = time.monotonic()
    ct = subprocess.run([str(tt_bin), "--port", port], cwd=REPO, timeout=120)
    try:
        relay_out, _ = relay.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        relay.kill()
        relay_out, _ = relay.communicate()
        print("fake relay: killed after a timeout")
        return 1
    print(relay_out.rstrip())
    if ct.returncode != 0 or relay.returncode != 0:
        print(f"transport test: FAIL (C exit {ct.returncode}, relay exit {relay.returncode})")
        return 1
    print("transport test: PASS (%.1f s wall)" % (time.monotonic() - t0))
    print("band suite: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
