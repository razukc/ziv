import subprocess, time, sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
caddy_exe = repo_root / 'agent' / 'venv_for_judge_repro_wirecheck' / 'Lib' / 'site-packages' / 'caddy_offline_windows_amd64' / 'caddy.exe'
caddyfile = repo_root / 'agent' / 'Caddyfile'
public_root = repo_root / 'agent' / 'public'

if not caddy_exe.is_file():
    print('ERROR: caddy executable missing at', caddyfile, file=sys.stderr)
    sys.exit(2)
if not caddyfile.is_file():
    print('ERROR: Caddyfile missing at', caddyfile, file=sys.stderr)
    sys.exit(2)
if not public_root.is_file() and not (public_root / 'index.html').is_file():
    print('WARNING: public/index.html not found at', public_root / 'index.html', file=sys.stderr)

# leave a clean slate
subprocess.run(['taskkill', '/F', '/IM', 'caddy.exe'], capture_output=True, text=True, timeout=10)
time.sleep(1)

env = subprocess.os.environ.copy()
env['CADDY_ROOT'] = str(public_root)

proc = subprocess.Popen(
    [str(caddy_exe), 'run', '--config', str(caddyfile), '--adapter', 'caddyfile'],
    cwd=str(repo_root),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.STDOUT,
    env=env,
    creationflags=subprocess.CREATE_NO_WINDOW,
)

print('Caddy pid:', proc.pid, flush=True)
print('Serving static files from:', public_root, flush=True)
print('Local preview URL: http://127.0.0.1:8788/', flush=True)
print('Caddy is running in the background; stop it with: taskkill /F /IM caddy.exe', flush=True)

try:
    proc.wait()
    print('Caddy exited with code:', proc.returncode, flush=True)
except KeyboardInterrupt:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
