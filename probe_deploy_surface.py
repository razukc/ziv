#!/usr/bin/env python3
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

def present(label: str, value: str | None) -> None:
    print(f"{label}: {value or '(not found)'}")

def run(argv: list[str], timeout: int = 30) -> str:
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        return f"RC={p.returncode} stdout={out!r} stderr={err!r}"
    except FileNotFoundError:
        return "NOT_INSTALLED"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"

print("== interpreter ==")
present("python", shutil.which("python") or shutil.which("python3"))
present("git", shutil.which("git"))
present("gh", shutil.which("gh"))
present("node", shutil.which("node"))
present("npm", shutil.which("npm"))
present("wrangler", shutil.which("wrangler"))

print("\n== notable env ==")
for key in sorted(os.environ):
    if key.startswith(("GITHUB_", "FREEBUFF_", "CLOUDFLARE_", "NEBIUS_", "ZIV_", "OPENAI_", "ANTHROPIC_", "HF_")):
        print(f"{key}={os.environ[key]!r}")

print("\n== repo tree sanity ==")
for p in [
    HERE / "agent" / "ziv_server.py",
    HERE / "agent" / "requirements.txt",
    HERE / "agent" / "ziv_client" / "index.html",
    HERE / "tools" / "haptic_timing_gen.py",
    HERE / ".gitignore",
]:
    print(f"{p.relative_to(HERE)}: exists={p.exists()} size={p.stat().st_size if p.exists() else 'NA'}")

print("\n== do-not-run probes ==")
print("git remote:", run(["git", "remote", "-v"]))
print("gh auth:", run(["gh", "auth", "status"]))
print("git status:", run(["git", "status", "--short"]))
print("node version:", run(["node", "--version"]))
print("npm version:", run(["npm", "--version"]))
print("wrangler version:", run(["wrangler", "--version"]))
