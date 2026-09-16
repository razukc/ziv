#!/usr/bin/env python3
"""run_ziv_tests.py — host bench tests for the ziv_qemu app core.

QEMU ladder rung 1 (docs/QEMU_SIMULATION_LADDER.md) without QEMU: the app
core (ziv_app.c) is host-portable, so its scripted boot demo is walked here
on a virtual clock and its complete HAP line output is asserted against the
derived k_demo_expected[] fixture (generated into ziv_demo_sequence.c from
the DEMO_STAGES single source) — the exact sequence tools/qemu_timeline.py
expects from the QEMU boot at rung 2.

After the C suite passes, the rung-2 boot-check plumbing is proven on the
spot: the same binary runs with --hap-log and its HAP stream is diffed by
tools/qemu_timeline.py against the *derived* fixture (bench side vs itself
is trivially equal; the real assertion is bench-vs-fixture, which the
differ enforces with exact structure and timestamps). The future CI QEMU
job reuses this exact invocation with the boot capture as the second log.

Builds with the same compiler detection and zero-warning discipline as
firmware/haptic_out/run_tests.py (cc/gcc/clang/tcc, `zig cc`, the ziglang
pip package, then WSL; -Wall -Wextra -Werror -std=c11).

No compiler found -> exits 2 with an install hint (same as the bench).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HAPTIC_OUT = HERE.parents[1] / "haptic_out"
# zig cc is picky about absolute paths on Windows (CacheCheckFailed); every
# path below is relative to HERE and the command runs with cwd=HERE.
REL_SRCS = [
    "../../haptic_out/haptic_out.c",
    "../../haptic_out/drv2605.c",
    "../../haptic_out/mock_drv2605.c",
    "main/ziv_demo_sequence.c",
    "main/ziv_app.c",
    "main/host_demo.c",
]
OUT_NAME = "host_demo.exe" if sys.platform == "win32" else "host_demo"
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]


def find_cc():
    # Prefer the repo venv's ziglang (the bench suite's compiler on machines
    # without a host gcc) before PATH probing.
    probe = subprocess.run(
        [sys.executable, "-m", "ziglang", "version"],
        capture_output=True, text=True, timeout=120,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return [sys.executable, "-m", "ziglang", "cc"]
    for tool in ("cc", "gcc", "clang", "tcc"):
        path = shutil.which(tool)
        if path:
            return [path]
    if shutil.which("zig"):
        return ["zig", "cc"]
    return None


def main():
    cc = find_cc()
    if cc is None:
        print("no C compiler found (ziglang pip, cc/gcc/clang/tcc, zig).")
        print("run inside the agent venv (pip install ziglang) or install a host gcc.")
        return 2

    # zig cc is picky about absolute paths on Windows; run from HERE with
    # relative paths and a project-local cache (kept out of git like the
    # bench build artifacts).
    env = dict(os.environ)
    env.setdefault("ZIG_LOCAL_CACHE_DIR", str(HERE / ".zig-cache"))
    build = subprocess.run(
        [*cc, *CFLAGS, "-I", "../../haptic_out", "-I", ".", "-o", OUT_NAME,
         *REL_SRCS],
        cwd=HERE,
        env=env,
    )
    if build.returncode != 0:
        print("ziv host build failed")
        return 1

    # Absolute path: Windows does not resolve a bare name against cwd.
    test = subprocess.run([str(HERE / OUT_NAME)], cwd=HERE)
    if test.returncode == 0:
        print("ziv host suite: PASS")
    else:
        print("ziv host suite: FAIL (exit %d)" % test.returncode)
        return test.returncode

    # --- rung-2 boot-check plumbing (docs/QEMU_SIMULATION_LADDER.md) -----
    # The bench binary emits the demo's HAP stream (--hap-log) and the
    # differ reads the *derived* k_demo_expected fixture (cross-checked
    # against the generated .c) as the expected side. Bench vs bench is
    # trivially equal; the real assertion is bench-vs-fixture, which the
    # differ enforces (exact structure + timestamps). The CI QEMU job runs
    # this same command with the boot console capture as the second log.
    bench_log = HERE / "bench_hap.log"  # gitignored (*.log)
    with open(bench_log, "w", encoding="utf-8") as fh:
        emit = subprocess.run(
            [str(HERE / OUT_NAME), "--hap-log"], cwd=HERE, stdout=fh
        )
    if emit.returncode != 0:
        print("ziv boot check: FAIL (--hap-log run exited %d)" % emit.returncode)
        return 1
    differ = subprocess.run(
        [sys.executable, str(REPO / "tools" / "qemu_timeline.py"),
         str(bench_log), str(bench_log), "--tol-ms", "0"],
    )
    try:
        bench_log.unlink()
    except OSError:
        pass
    if differ.returncode == 0:
        print("ziv boot check: PASS — CI boot job inherits the derived fixture")
        return 0
    print("ziv boot check: FAIL (tools/qemu_timeline.py exit %d)" % differ.returncode)
    return 1


if __name__ == "__main__":
    sys.exit(main())
