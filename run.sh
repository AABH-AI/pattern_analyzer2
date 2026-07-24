#!/usr/bin/env bash
# One-command setup & run — Linux / macOS.
#   chmod +x run.sh && ./run.sh
# Installs Python deps, ensures backend/config.json, then starts the backend + serves the app.
set -e
cd "$(dirname "$0")"
echo "== Demand Pattern RCA Console — setup & run =="

command -v python3 >/dev/null 2>&1 || { echo "Python 3.11+ required (python3 not found)."; exit 1; }
python3 --version

echo "Installing backend dependencies..."
python3 -m pip install -r backend/requirements.txt

if [ ! -f backend/config.json ]; then
  cp backend/config.example.json backend/config.json
  echo ""
  echo ">> Created backend/config.json — fill in server/database/table/auth/username/password/driver, then re-run."
  echo ">> You also need the Microsoft ODBC Driver 17/18 for SQL Server installed (or use Docker: see DEPLOY.md)."
fi

# One-time data load (uncomment): python3 backend/upload_excel_to_sql.py   # try --dry-run first
echo ""
echo "Starting backend on http://localhost:8000  (Ctrl+C to stop)"
echo "Open: http://localhost:8000/rca_console.html"
cd backend
python3 -m uvicorn sql_backend:app --host 0.0.0.0 --port 8000
