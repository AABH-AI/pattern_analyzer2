# One-command setup and run -- Windows (PowerShell).
#   Run with:  powershell -ExecutionPolicy Bypass -File run.ps1
# Installs Python deps, ensures backend\config.json, then starts the backend and opens the app.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
Write-Host "== Demand Pattern RCA Console - setup and run ==" -ForegroundColor Cyan

# 1) Python
try { $pv = (python --version) 2>&1 } catch { throw "Python 3.11+ is required and was not found on PATH. Install from https://python.org and re-run." }
Write-Host "Python: $pv"

# 2) Dependencies
Write-Host "Installing backend dependencies..."
python -m pip install --quiet -r "backend\requirements.txt"

# 3) Config (holds your SQL server + login; gitignored)
if (-not (Test-Path "backend\config.json")) {
  Copy-Item "backend\config.example.json" "backend\config.json"
  Write-Host ""
  Write-Host "Created backend\config.json - open it and fill in:" -ForegroundColor Yellow
  Write-Host "   server, database, table, auth=sql, username, password, driver" -ForegroundColor Yellow
  Write-Host "Then re-run this script. (You also need the Microsoft ODBC Driver 17/18 for SQL Server installed.)" -ForegroundColor Yellow
  Write-Host "Tip: you can still use the app now via 'Upload weekly file' without SQL." -ForegroundColor DarkGray
}

# 4) (optional) one-time data load into SQL -- uncomment to run:
# python "backend\upload_excel_to_sql.py"          # try --dry-run first to verify parsing

# 5) Start backend (serves the UI too) and open the app
Write-Host ""
Write-Host "Starting backend on http://localhost:9000  (Ctrl+C to stop)" -ForegroundColor Green
Start-Process "http://localhost:9000/rca_console.html"
Set-Location "$root\backend"
python -m uvicorn sql_backend:app --host 0.0.0.0 --port 9000
