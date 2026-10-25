#!/usr/bin/env python3
"""run_tests.py — build and run the haptic_out bench tests.

The sequencer and driver are host-portable (no ESP-IDF), so the exact code
that will run on the band can be compiled and driven on a laptop against
the mock DRV2605L.  Detects a host C compiler (cc/gcc/clang/tcc/zig in PATH,
or a real WSL install) and maps the test exit code.

No compiler found -> exits 2 with an install hint.  On Windows without a
toolchain: "winget install w64devkit" (portable gcc), or
"sudo apt install gcc" inside WSL, then re-run.

Sources build with -Wall -Wextra -Werror -std=c11 for zero-warning
discipline; the module headers carry no dependencies, so the same sources
compile under ESP-IDF later with the real I2C bus swapped in.

Compiler detection order: cc/gcc/clang/tcc in PATH, `zig cc`, the
`ziglang` pip package in the running interpreter (`pip install ziglang`),
then a real WSL install.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRCS = ["haptic_out.c", "drv2605.c", "mock_drv2605.c", "test_haptic_out.c"]
OUT = HERE / ("test_haptic_out.exe" if sys.platform == "win32" else "test_haptic_out")
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]


def wsl_path(p: Path) -> str:
    s = str(p).replace("\\", "/")
    s = re.sub(r"^([A-Za-z]):", lambda m: "/mnt/" + m.group(1).lower(), s)
    return s


def wsl_cc():
    """Return a compiler argv that runs inside WSL, or None."""
    wsl = shutil.which("wsl")
    if not wsl:
        return None
    probe = subprocess.run(
        [wsl, "sh", "-lc", "command -v gcc cc clang 2>/dev/null | head -1"],
        capture_output=True, text=True, timeout=20,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        return None
    return [wsl, "sh", "-lc", probe.stdout.strip()]


def find_cc():
    for tool in ("cc", "gcc", "clang", "tcc"):
        path = shutil.which(tool)
        if path:
            return [path]
    if shutil.which("zig"):
        return ["zig", "cc"]   # zig cc is a drop-in C compiler
    # ziglang pip package (e.g. installed into a project venv):
    #   pip install ziglang  ->  python -m ziglang cc ...
    probe = subprocess.run(
        [sys.executable, "-m", "ziglang", "version"],
        capture_output=True, text=True, timeout=120,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return [sys.executable, "-m", "ziglang", "cc"]
    return wsl_cc()


def main():
    cc = find_cc()
    if cc is None:
        print("no C compiler found (tried cc/gcc/clang/tcc/zig, then WSL).")
        print("install one to run the bench tests, e.g. 'winget install w64devkit'")
        print("or 'sudo apt install gcc' inside WSL, then re-run.")
        return 2

    in_wsl = cc[0].endswith("wsl") or "wsl" in cc[0]
    here = wsl_path(HERE) if in_wsl else str(HERE)
    # WSL writes the plain name; a native Windows build needs the .exe suffix.
    out_name = "test_haptic_out" if in_wsl else ("test_haptic_out.exe" if sys.platform == "win32" else "test_haptic_out")
    out = wsl_path(HERE / out_name) if in_wsl else str(HERE / out_name)
    srcs = [wsl_path(HERE / s) if in_wsl else str(HERE / s) for s in SRCS]

    def run(argv):
        print("+", " ".join(argv))
        return subprocess.run(argv, cwd=HERE)

    build = run([*cc, *CFLAGS, "-I", here, "-o", out, *srcs])
    if build.returncode != 0:
        print("build failed")
        return 1

    test = run([out])
    if test.returncode == 0:
        print("bench suite: PASS")
    else:
        print("bench suite: FAIL (exit %d)" % test.returncode)
    return test.returncode


if __name__ == "__main__":
    sys.exit(main())