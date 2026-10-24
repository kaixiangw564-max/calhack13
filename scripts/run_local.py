"""Start the whole PlainPath demo locally: FastAPI backend (:8000), Next.js website (:3000) and the four agents
(Bureau :8001, connected to Agentverse through mailboxes). Ctrl+C stops everything.

Usage (from repo root, after the setup steps in README.md):
    python scripts/run_local.py            # all three
    python scripts/run_local.py api web    # pick components
"""
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(VENV_PY if VENV_PY.exists() else sys.executable)
NPM = shutil.which("npm") or "npm"

COMPONENTS = {
    "api": [PY, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"), "--port", "8000"],
    "agents": [PY, str(ROOT / "agents" / "run_all.py")],
    "web": [NPM, "--prefix", str(ROOT / "web"), "run", "dev"],
}


def stream(name: str, proc: subprocess.Popen) -> None:
    for line in iter(proc.stdout.readline, b""):
        sys.stdout.buffer.write(f"[{name}] ".encode() + line)
        sys.stdout.flush()


def main() -> None:
    wanted = sys.argv[1:] or list(COMPONENTS)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "BACKEND_URL": os.environ.get("BACKEND_URL", "http://localhost:8000")}
    procs = {}
    for name in wanted:
        procs[name] = subprocess.Popen(COMPONENTS[name], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=stream, args=(name, procs[name]), daemon=True).start()
    print("PlainPath running: website http://localhost:3000 | API http://localhost:8000/health | agents on Agentverse")
    try:
        while all(p.poll() is None for p in procs.values()):
            threading.Event().wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        exited = {n: p.poll() for n, p in procs.items() if p.poll() not in (None, 0)}
        if exited:
            print("exited with errors:", exited)


if __name__ == "__main__":
    main()
