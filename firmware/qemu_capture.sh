#!/usr/bin/env bash
# firmware/qemu_capture.sh — boot a built ESP-IDF project under Espressif QEMU
# for a bounded time and capture UART0 to a file (docs/QEMU_SIMULATION_LADDER.md
# rungs 1-2; used by .github/workflows/ci.yml and the docs).
#
#   firmware/qemu_capture.sh <project_dir> <out_log> [seconds=240] [extra qemu args...]
#
# <seconds> is the hard cap.  QEMU_UNTIL=<regex> (with QEMU_UNTIL_COUNT=<n>,
# default 1) stops the capture 2 s after the regex has matched n lines of the
# output — e.g. the bench log's last line for the rung-2 demo, or the band's
# "transport: connect failed" with a count for its backoff.
#
# Needs the IDF environment (. $IDF_PATH/export.sh) and qemu-system-xtensa on
# PATH (python $IDF_PATH/tools/idf_tools.py install qemu-xtensa; the tool is
# optional, so export.sh does not add it — see docs/QEMU_WINDOWS_INSTALL.md).
#
# Same images and machine arguments as `idf.py qemu` (tools/idf_py_actions/
# qemu_ext.py): the flash image merged from flash_args at the configured size,
# the default efuse image, the esp32s3 machine, the open_eth NIC.  Two
# differences, both deliberate:
#   -serial file:<out_log>   UART0 goes to the file; `timeout` then stops QEMU
#                            itself (an `idf.py qemu` wrapper under timeout
#                            would leave QEMU running).
#   -icount shift=5,sleep=off  deterministic virtual time: the guest clock
#                            advances by instruction count and idle time is
#                            warped, so timestamps do not depend on host load.
#                            Measured on the rung-2 demo: exact match with the
#                            bench, versus +84 ms (quiet host) to +1039 ms
#                            (loaded host) of accumulated drift in wall-clock
#                            mode.  The price: the ROM's start-up polling
#                            loop costs ~35 s of HOST time at shift=5 (it is
#                            ~1.2 s of virtual time; every MMIO poll exits
#                            the translation block), after which bootloader,
#                            app and the whole 7.3 s demo take ~4 s.  Smaller
#                            shifts spend proportionally longer in that loop
#                            (shift<=3 never got past it in 20 s); larger ones
#                            make each guest instruction cost more virtual
#                            time, so a printed HAP line starts to shift the
#                            next beat.  Set QEMU_ICOUNT= (empty) for
#                            wall-clock mode (boots in 0.3 s; timing depends
#                            on the host).
set -euo pipefail
proj=${1:?project dir}; out=${2:?output log}; secs=${3:-240}
shift $(( $# < 3 ? $# : 3 ))
build="$proj/build"
flash_size=$(sed -n 's/^CONFIG_ESPTOOLPY_FLASHSIZE="\(.*\)"/\1/p' "$proj/sdkconfig")
: "${flash_size:?CONFIG_ESPTOOLPY_FLASHSIZE not found in $proj/sdkconfig — build the project first}"
(cd "$build" && python -m esptool --chip=esp32s3 merge_bin --output=qemu_flash.bin \
    --fill-flash-size="$flash_size" @flash_args >/dev/null)
python - "$build/qemu_efuse.bin" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["IDF_PATH"], "tools"))
from idf_py_actions.qemu_ext import QEMU_TARGETS
open(sys.argv[1], "wb").write(QEMU_TARGETS["esp32s3"].default_efuse)
PY
icount=${QEMU_ICOUNT-shift=5,sleep=off}
icount_args=()
[ -n "$icount" ] && icount_args=(-icount "$icount")
rm -f "$out"
set +e
timeout "$secs" qemu-system-xtensa -M esp32s3 \
    -drive "file=$build/qemu_flash.bin,if=mtd,format=raw" \
    -drive "file=$build/qemu_efuse.bin,if=none,format=raw,id=efuse" \
    -global driver=nvram.esp32c3.efuse,property=drive,value=efuse \
    -global driver=timer.esp32s3.timg,property=wdt_disable,value=true \
    -nic user,model=open_eth -nographic -monitor none \
    "${icount_args[@]}" -serial "file:$out" "$@" &
qpid=$!
t0=$SECONDS; stopped=
until_re=${QEMU_UNTIL-}; until_n=${QEMU_UNTIL_COUNT:-1}
while kill -0 "$qpid" 2>/dev/null; do
    sleep 1
    if [ -n "$until_re" ] && [ -f "$out" ] && [ "$(grep -cE -- "$until_re" "$out" || true)" -ge "$until_n" ]; then
        sleep 2                      # let the guest finish the lines after the match
        kill "$qpid" 2>/dev/null; stopped="after the sentinel"
        break
    fi
done
wait "$qpid"; rc=$?
set -e
# 124 = the hard cap, 143 = our kill after the sentinel; anything else is QEMU failing
if [ "$rc" -ne 124 ] && [ "$rc" -ne 143 ] && [ "$rc" -ne 0 ]; then echo "qemu_capture: qemu exited $rc" >&2; exit "$rc"; fi
echo "qemu_capture: $(wc -l < "$out") lines, $(grep -c '^HAP ' "$out" || true) HAP, $((SECONDS - t0)) s${stopped:+ ($stopped)} -> $out"
