import subprocess, sys, time, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"
os.environ.setdefault("ZIV_PORT", "8787")
os.environ.setdefault("ZIV_FAKE_MODEL_SECONDS", "0.05")

print("starting ziv relay on port 8787", flush=True)
proc = subprocess.Popen(
    [sys.executable, str(AGENT / "ziv_server.py")],
    cwd=str(AGENT),
    env=os.environ,
    stdin=subprocess.DEVNULL,
)
try:
    for _ in range(120):
        time.sleep(0.25)
        if proc.poll() is not None:
            print("relay exited with", proc.returncode, file=sys.stderr)
            break
    print("relay running; open http://localhost:8787/ziv_client/index.html", flush=True)
    print("PID", proc.pid, flush=True)
    proc.wait()
except KeyboardInterrupt:
    proc.send_signal(subprocess.signal.CTRL_BREAK_EVENT if os.name == "nt" else subprocess.signal.SIGINT)
    proc.wait(timeout=5)
