#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One command to run the Demand Pattern RCA Console (spec-v2-refactor).

    python run.py                 deps -> checks -> backend -> browser
    python run.py --test          also run the module smoke test first
    python run.py --check         run the pre-flight checks only, start nothing
    python run.py --port 8010     serve on a different port
    python run.py --no-browser    start the server, do not open a browser

Adapted from the `UI` branch's run.py. Two differences, both deliberate:

PORT 8000, NOT 8010. Every launcher and document on THIS branch says 8000 -- run.bat, run.sh,
CLAUDE.md and AGENTS.md. The UI branch moved to 8010 and then needed a follow-up commit ("Fix stale
port 8000 references to match run.py's actual port") to chase the references it had orphaned. Matching
the branch avoids repeating that; --port is there when you want something else.

A HOLIDAY-MASTER PRE-FLIGHT CHECK. This branch's engine reads
`backend/wfm/context_repository/holiday_master.json`, built from FC_RCA_Holiday_Master_Production.xlsx
by `backend/load_holiday_master.py`. `.gitignore` excludes *.xlsx, so the source never travels with
the repo -- only the generated JSON does. If that JSON is missing or truncated, holiday reasoning
degrades silently: the engine keeps working and simply reports "no holiday", which looks like a
correct answer rather than a missing input. The check makes that visible before you investigate
anything.
"""
import argparse
import http.client
import json
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# The Windows console defaults to cp1252, which cannot encode the em-dash and similar characters --
# they print as a replacement glyph and make a launcher look broken before it has done anything.
# Force UTF-8 with replacement so output is always readable, whatever it contains.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
HOLIDAY_JSON = BACKEND / "wfm" / "context_repository" / "holiday_master.json"
DEFAULT_PORT = 8000

OK, WARN, BAD = "  [ok]  ", "  [--]  ", "  [!!]  "


def free_port(port):
    """Free `port` if a previous run is still holding it.

    A stale process answering requests while the fresh one cannot bind is the single most
    time-wasting failure in this project: the app looks up, serves the OLD code, and the symptom
    reads as "why is it showing old output". Kill it up front rather than debug it later.
    """
    pids = set()
    if sys.platform.startswith("win"):
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                 timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return
        for line in out.splitlines():
            parts = line.split()
            # LISTENING lines look like:  TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  1234
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[-1].isdigit():
                pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    else:
        try:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True,
                                 text=True, timeout=15).stdout
            pids = {p for p in out.split() if p.isdigit()}
        except (OSError, subprocess.SubprocessError):
            return
        for pid in pids:
            subprocess.run(["kill", "-9", pid], capture_output=True)
    if pids:
        print(f"{OK}freed port {port} (killed PID {', '.join(sorted(pids))})")
        time.sleep(1)
    else:
        print(f"{OK}port {port} is free")


def check_config():
    """config.json is gitignored, so a fresh worktree or clone will not have one."""
    cfg = BACKEND / "config.json"
    if not cfg.exists():
        print(f"{WARN}backend/config.json is missing -- SQL features will be unavailable.")
        print("        Copy backend/config.example.json to backend/config.json and fill it in.")
        print("        'Upload weekly file' in the UI still works without it.")
        return False
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{BAD}backend/config.json is not valid JSON: {exc}")
        return False
    sql = data.get("sql") or {}
    server = str(sql.get("server") or "")
    if not server or server.startswith("YOUR_"):
        print(f"{WARN}backend/config.json has no SQL server set (still a placeholder).")
        return False
    print(f"{OK}config.json -> {server} / {sql.get('table')}")
    return True


def check_holiday_master():
    """The holiday calendar is a generated artifact and can go missing without any error.

    Confirms the file is present, parses, and reports the row counts the loader recorded, so a
    truncated or half-written JSON is caught here rather than showing up as "no holiday" on every
    report. Uses the engine's own loader when it imports, so this checks the real path the RCA
    takes -- not a second implementation that could agree with itself while the engine fails.
    """
    if not HOLIDAY_JSON.exists():
        print(f"{BAD}holiday_master.json is MISSING -- holiday root causes will silently")
        print("        report 'no holiday' for every queue. Rebuild it with:")
        print('        python backend/load_holiday_master.py "<path>/FC_RCA_Holiday_Master_Production.xlsx"')
        return False
    try:
        sys.path.insert(0, str(BACKEND))
        from wfm.context_repository import loaded          # noqa: PLC0415
        state = loaded()
    except Exception as exc:                               # noqa: BLE001
        print(f"{BAD}holiday calendar failed to load: {type(exc).__name__}: {exc}")
        return False
    finally:
        if str(BACKEND) in sys.path:
            sys.path.remove(str(BACKEND))

    if not state.get("available"):
        print(f"{BAD}holiday calendar unavailable: {state.get('reason')}")
        return False
    print(f"{OK}holiday master -> {state.get('active_rows'):,} rows, "
          f"{state.get('country_weeks'):,} country-weeks  (from {state.get('source')})")
    return True


def install_deps():
    req = BACKEND / "requirements.txt"
    if not req.exists():
        print(f"{WARN}backend/requirements.txt not found -- skipping dependency install")
        return
    print("  ...   installing backend dependencies")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)])
    print(f"{OK if r.returncode == 0 else BAD}dependencies "
          f"{'installed' if r.returncode == 0 else 'FAILED -- see the output above'}")


def run_smoke_test():
    """The module smoke test. Returns True on pass so --test can gate the launch."""
    script = ROOT / "results" / "smoke_test_modules.py"
    if not script.exists():
        print(f"{WARN}results/smoke_test_modules.py not found -- skipping")
        return True
    print("  ...   running the module smoke test")
    r = subprocess.run([sys.executable, str(script)], cwd=str(ROOT))
    print(f"{OK if r.returncode == 0 else BAD}smoke test "
          f"{'passed' if r.returncode == 0 else 'FAILED'}")
    return r.returncode == 0


def wait_for_health(port, timeout=45):
    """Poll /api/health until it answers.

    Opening the browser on a socket that is merely bound gives a blank page or a connection error,
    and the natural next move is to reload and blame the app. Wait for a real 200 first.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=2)
            conn.request("GET", "/api/health")
            if conn.getresponse().status == 200:
                return True
        except (ConnectionRefusedError, OSError, socket.timeout, http.client.HTTPException):
            pass
        finally:
            try:
                conn.close()
            except Exception:                              # noqa: BLE001
                pass
        time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser(description="Run the Demand Pattern RCA Console.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port to serve on (default {DEFAULT_PORT}, matching run.bat and the docs)")
    ap.add_argument("--test", action="store_true", help="run the module smoke test before starting")
    ap.add_argument("--check", action="store_true", help="run the pre-flight checks and exit")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = ap.parse_args()

    print("=" * 74)
    print("  Demand Pattern RCA Console - spec-v2-refactor")
    print("=" * 74)

    print("\n[1/5] pre-flight")
    check_config()
    holidays_ok = check_holiday_master()

    if args.check:
        print("\n--check: nothing was started.")
        return 0 if holidays_ok else 1

    print("\n[2/5] dependencies")
    install_deps()

    if args.test:
        print("\n[3/5] tests")
        if not run_smoke_test():
            print("\nStopping: the smoke test failed, so the app would be started on known-broken "
                  "code. Re-run without --test to start it anyway.")
            return 1
    else:
        print("\n[3/5] tests   (skipped — pass --test to run them)")

    print("\n[4/5] server")
    free_port(args.port)
    print(f"{OK}starting uvicorn on http://localhost:{args.port}   (Ctrl+C to stop)")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "sql_backend:app",
         "--host", "0.0.0.0", "--port", str(args.port)],
        cwd=str(BACKEND))

    print("\n[5/5] waiting for /api/health")
    if wait_for_health(args.port):
        url = f"http://localhost:{args.port}/rca_console.html"
        print(f"{OK}healthy - {url}")
        print(f"\n  The canonical 15-step engine on this branch is reached with "
              f"?mode=spec on\n  POST /api/rca-investigate  (?mode=wfm is the default, "
              f"mode=legacy the original).")
        if not args.no_browser:
            webbrowser.open(url)
    else:
        print(f"{BAD}the server did not become healthy in time - see the output above.")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nstopping…")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
