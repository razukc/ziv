# ESP-IDF + Espressif QEMU on this Windows machine — install + smoke test

**Goal:** run `idf.py qemu monitor` on [firmware/app/ziv_qemu](../firmware/app/ziv_qemu/)
so the real Ziv firmware boots in Espressif's QEMU fork and plays the scripted
demo's `HAP` timeline on the emulated UART — ladder rung 1's boot
([QEMU_SIMULATION_LADDER.md](./QEMU_SIMULATION_LADDER.md)). Written for this
machine: Windows, Git Bash, system Python 3.14, project at
`C:\code\playground\nebius`. One-time setup; every step has a check.

> Nothing here touches hardware, drivers, or admin rights — QEMU is a user-space
> program and the install goes under your user directory (default
> `C:\Espressif`). No USB drivers are needed for simulation.

## 0. Know before you install

| Fact | Consequence |
|---|---|
| System Python here is **3.14** | Newer than some IDF tooling expects. The Windows installer can install its own suitable Python — let it (see step 1). If you use the zip route and `idf.py` complains about the Python version, install Python 3.12 side-by-side and point `IDF_TOOLS_PYTHON` at it. ⚠ verify at install |
| The repo's shell is **Git Bash** | IDF's environment script is `.bat`/`.ps1`. Use the **"ESP-IDF PowerShell"** shortcut the installer creates, or from Git Bash: `cmd /c "C:\Espressif\idf-cmd\export.bat && idf.py …"`. ⚠ path per install |
| Keep `IDF_PATH` **short** (`C:\Espressif\idf\v6.1`) | Windows MAX_PATH bites long IDF + project paths. Project already sits at `C:\code\playground\nebius` — fine. If a build fails with path errors, enable Windows long paths (`git config --global core.longpaths true` + the OS registry switch) |
| QEMU binaries come **from Espressif's fork** (prebuilt x86_64 Windows) via `idf_tools.py install qemu-xtensa` | Do not use upstream QEMU — it has no ESP32-S3 machine |

## 1. Install ESP-IDF (one-time)

Recommended: the **Windows installer** (below) or the **VS Code ESP-IDF
extension**, which wraps the same steps. Current stable at the time of the
ladder doc: **v6.1** ⚠ (take the newest stable the
[Espressif downloads page](https://dl.espressif.com/dl/esp-idf/) offers;
the QEMU guide cited in the ladder doc is the v6.1 manual).

1. Download and run the ESP-IDF Windows installer (or the offline installer).
2. When asked about Python, accept the installer's **bundled/managed Python** —
   do not bind it to the system 3.14 unless it explicitly accepts it.
3. Install into `C:\Espressif\idf\v6.1` (short path, per the table above).
4. Components: defaults are fine; **do** keep "QEMU" / tools options if the
   installer offers them (later versions bundle the QEMU fork).

Check (from the new "ESP-IDF PowerShell" shortcut):

```powershell
idf.py --version          # prints the IDF version
echo $env:IDF_PATH        # C:\Espressif\idf\v6.1
```

(The shortcut just runs `export.bat`; reopen it any time — or from Git Bash:
`cmd /c "<IDF_PATH>\export.bat && idf.py --version"`.)

## 2. Install the Espressif QEMU fork (one-time, small download)

From an IDF environment:

```powershell
python $env:IDF_PATH\tools\idf_tools.py install qemu-xtensa
. $env:IDF_PATH\export.ps1        # or reopen the ESP-IDF PowerShell
```

Check:

```powershell
qemu-system-xtensa.exe --version
# qemu-system-xtensa version 8.x (Espressif fork) — must mention the fork or
# an esp32s3 machine must exist (next step is the real check)
```

No ESP32-S3 machine in `qemu-system-xtensa.exe --machine help | findstr esp32`
→ you are talking to upstream QEMU; the fork's binary wasn't put on PATH by
`export.ps1` — rerun the export and recheck.

## 3. Smoke test — boot ziv_qemu

From an IDF environment:

```powershell
cd C:\code\playground\nebius\firmware\app\ziv_qemu
idf.py set-target esp32s3     # once; creates sdkconfig
idf.py build                  # first build is the long one
idf.py qemu monitor
```

**Pass criteria — in order:**

1. IDF boot banner (`ESP-ROM:esp32s3...`, `Hello world`-style IDF startup,
   `cpu_start` lines) — the emulated S3 came up.
2. The app's **27 HAP lines** for the scripted demo, same order and values as
   `host_demo.c`'s fixture (`firmware/app/ziv_qemu/main/host_demo.c`):

   ```
   HAP 0 START PATTERN ramp-up
   HAP 0 BUZZ PATTERN ramp-up 00 50 90 0
   HAP 140 BUZZ PATTERN ramp-up 00 90 120 1
   ...                                  (27 lines total)
   HAP 7310 END
   ```

   `at_ms` values will be **wall-clock** here — near 0 at boot, but whatever
   the emulated timer reports; the *deltas* are the assertion. Compare by eye
   until rung 2 lands: `tools/qemu_timeline.py` (speced in the ladder doc)
   will do the diff mechanically against the bench log.
3. The console stays alive at an idle poll (the task's 50 ms idle loop) —
   Ctrl-] exits the monitor.

Demo replays: type nothing — it runs once per boot; `idf.py qemu monitor`
again (or reset in QEMU with Ctrl-A x, restart) replays it.

## 4. First troubleshooting moves

| Symptom | First move |
|---|---|
| `idf.py: command not found` | You are not in an IDF environment — open the ESP-IDF PowerShell shortcut (or run `export.bat`) |
| `qemu-system-xtensa: machine 'esp32s3' not found` | Upstream QEMU shadows the fork — check PATH order after `export.ps1`; reinstall `qemu-xtensa` per step 2 |
| Build errors in `mock_drv2605.c` / `ziv_app.c` | These compile on the host with `-Wall -Wextra -Werror -std=c11` (run `python run_ziv_tests.py` in the app dir — it must PASS before any IDF build); if it passes but IDF fails, check the IDF include dirs in `main/CMakeLists.txt` |
| `python` version errors during idf.py | Bind the IDF env to its managed Python (step 0/1) — do not repoint the repo's agent venv |
| Boot hangs, no HAP lines | `idf.py qemu monitor` without `--graphics` is fine; check the app actually built in (`idf.py flash` is NOT needed — QEMU boots `qemu_flash.bin` straight from the build); add `--qemu-extra-args="-d guest_errors"` ⚠ |
| Everything works, no `HAP` lines | stdout buffering — the sink prints via `printf`; if a later IDF log-level setting swallows app stdout, set `Component config → Log settings` down or flush |

## 5. After the boot works

- **Promote the CI job**: the ladder's `qemu-boot` GitHub Actions job (Linux
  prebuilt QEMU, ~30 s headless boot, assert the 27-line sequence) goes from
  `continue-on-error` to blocking once green — same promote-a-check discipline
  as the drift guard.
- **Rung 2**: `tools/qemu_timeline.py <bench.log> <qemu.log>` — capture the
  monitor output to a file (`idf.py qemu | tee qemu.log`) and the bench side
  via the harness's HAP emitter (speced; next ladder item).

*Every version number, path, and QEMU flag here is marked or implied ⚠ per
repo discipline: verify against the installer and the Espressif QEMU README at
install time — this guide is the map, not the territory.*
