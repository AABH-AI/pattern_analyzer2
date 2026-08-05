#!/usr/bin/env python3
"""One-command run for the Demand Pattern RCA Console (pattern_analyzer2).

    python run.py

Does everything by hand that this session did manually, every time:
  1. Frees port 8010 if a previous run is still holding it (the exact bug that caused
     "why is it showing old/wrong output" earlier -- a stale process answering requests
     while a fresh one sat unreachable).
  2. Installs backend deps quietly.
  3. Starts the backend (serves the UI too) on http://localhost:8010.
  4. Waits for /api/health to actually respond before opening the browser.
"""
import http.client
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
PORT = 8010


def free_port(port):
    """Kill whatever is listening on `port`, if anything (Windows-only netstat parse)."""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and f":{port}" in parts[1] and parts[-1].isdigit():
            pids.add(parts[-1])
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    if pids:
        print(f"Freed port {port} (killed PID(s): {', '.join(sorted(pids))})")
        time.sleep(1)


def wait_for_health(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=2)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            if resp.status == 200:
                return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            pass
        time.sleep(0.5)
    return False


def main():
    print("== Demand Pattern RCA Console (pattern_analyzer2) ==")

    free_port(PORT)

    print("Installing backend dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r",
                    str(BACKEND / "requirements.txt")], check=True)

    if not (BACKEND / "config.json").exists():
        print()
        print("backend/config.json is missing.")
        print("Copy backend/config.example.json to backend/config.json and fill in the SQL details,")
        print("then re-run this script. You can still use 'Upload weekly file' in the UI without it.")
        print()

    print(f"Starting backend on http://localhost:{PORT}  (Ctrl+C to stop)")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "sql_backend:app",
                              "--host", "0.0.0.0", "--port", str(PORT)], cwd=str(BACKEND))

    if wait_for_health(PORT):
        webbrowser.open(f"http://localhost:{PORT}/rca_console.html")
    else:
        print("Server did not become healthy in time -- check the terminal output above.")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
