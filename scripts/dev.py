"""Local WSL launcher. Docker is used only for PostgreSQL during development."""

import argparse
import os
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".local"
RUNTIME.mkdir(exist_ok=True)
COMMANDS = {
    "api": [
        str(ROOT / ".venv/bin/uvicorn"),
        "catalogforge.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8188",
    ],
    "worker": [str(ROOT / ".venv/bin/python"), "-m", "catalogforge.worker"],
    "web": ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
}


def stop(name):
    path = RUNTIME / f"{name}.pid"
    if not path.exists():
        return
    pid = int(path.read_text())
    try:
        process_cwd = Path(f"/proc/{pid}/cwd").resolve()
        if not process_cwd.is_relative_to(ROOT):
            raise RuntimeError("PID no longer belongs to CatalogForge")
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    path.unlink(missing_ok=True)


def start(name):
    path = RUNTIME / f"{name}.pid"
    if path.exists() and Path(f"/proc/{path.read_text().strip()}").exists():
        print(f"{name} already running")
        return
    cwd = ROOT / "apps/web" if name == "web" else ROOT
    with (RUNTIME / f"{name}.log").open("ab") as output:
        proc = subprocess.Popen(
            COMMANDS[name],
            cwd=cwd,
            stdout=output,
            stderr=output,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    path.write_text(str(proc.pid))
    print(f"Started {name}: {proc.pid}")


parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["start", "stop", "restart"])
parser.add_argument("service", choices=[*COMMANDS, "all"], default="all", nargs="?")
args = parser.parse_args()
for name in COMMANDS if args.service == "all" else [args.service]:
    if args.action in {"stop", "restart"}:
        stop(name)
    if args.action in {"start", "restart"}:
        start(name)
