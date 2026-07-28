@echo off
REM ===========================================================================
REM  run.bat -- one-shot setup and run for the Demand Pattern RCA Console.
REM
REM  Usage:
REM     run.bat                 setup + VPN check + start backend + open the app
REM     run.bat --smoke         ...and run the per-module smoke test (12 modules)
REM     run.bat --validate      ...and run the SQL cross-check suite (5 queues)
REM     run.bat --llm           ...and run the LLM ranking verification (3 queues)
REM     run.bat --all           ...run all three test suites
REM     run.bat --no-vpn        skip the VPN step entirely
REM     run.bat --no-browser    do not open the browser
REM     run.bat --tests-only    run the tests against an already-running backend
REM
REM  What it does, in order:
REM     1. Python check
REM     2. install backend dependencies
REM     3. ensure backend\config.json exists (copied from the example if missing)
REM     4. VPN: check Cisco Secure Client, and try to connect if it is down
REM     5. verify the SQL host is reachable on its port
REM     6. free port 8000 if something is squatting on it
REM     7. start the backend and wait for /api/health
REM     8. optionally run the test suites
REM     9. open the console in the browser
REM ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "RUN_SMOKE="
set "RUN_VALIDATE="
set "RUN_LLM="
set "SKIP_VPN="
set "SKIP_BROWSER="
set "TESTS_ONLY="
:parseargs
if "%~1"=="" goto endargs
if /i "%~1"=="--smoke"      set "RUN_SMOKE=1"
if /i "%~1"=="--validate"   set "RUN_VALIDATE=1"
if /i "%~1"=="--llm"        set "RUN_LLM=1"
if /i "%~1"=="--all"        ( set "RUN_SMOKE=1" & set "RUN_VALIDATE=1" & set "RUN_LLM=1" )
if /i "%~1"=="--no-vpn"     set "SKIP_VPN=1"
if /i "%~1"=="--no-browser" set "SKIP_BROWSER=1"
if /i "%~1"=="--tests-only" set "TESTS_ONLY=1"
shift
goto parseargs
:endargs

echo ===========================================================================
echo   Demand Pattern RCA Console -- setup and run
echo   %DATE% %TIME%
echo ===========================================================================
echo.

REM --------------------------------------------------------------- 1. Python
echo [1/9] Python
where python >nul 2>&1
if errorlevel 1 (
  echo    ERROR: Python is not on PATH. Install Python 3.11+ from https://python.org
  echo    then re-run this script.
  goto fail
)
for /f "delims=" %%v in ('python --version 2^>^&1') do echo    %%v

REM --------------------------------------------------- 2. dependencies
if defined TESTS_ONLY goto skipdeps
echo.
echo [2/9] Installing backend dependencies (quiet)
python -m pip install --quiet -r "backend\requirements.txt"
if errorlevel 1 (
  echo    ERROR: dependency install failed. Scroll up for pip output.
  goto fail
)
echo    ok
goto afterdeps
:skipdeps
echo.
echo [2/9] Skipped dependency install (--tests-only)
:afterdeps

REM --------------------------------------------------------- 3. config.json
echo.
echo [3/9] Backend config
if exist "backend\config.json" (
  echo    backend\config.json present
) else (
  if exist "backend\config.example.json" (
    copy /y "backend\config.example.json" "backend\config.json" >nul
    echo    Created backend\config.json from the example.
    echo    ^>^> OPEN IT AND FILL IN: server, database, table, username, password, driver
    echo    ^>^> Then re-run this script. ^(config.json is gitignored -- never commit it.^)
    goto fail
  ) else (
    echo    ERROR: neither backend\config.json nor backend\config.example.json exists.
    goto fail
  )
)

REM ------------------------------------------------------------------ 4. VPN
echo.
if defined SKIP_VPN (
  echo [4/9] VPN check skipped ^(--no-vpn^)
  goto aftervpn
)
echo [4/9] VPN ^(SQL Server is on the internal network^)
set "VPNCLI=C:\Program Files (x86)\Cisco\Cisco Secure Client\vpncli.exe"
if not exist "!VPNCLI!" set "VPNCLI=C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe"
if not exist "!VPNCLI!" (
  echo    No Cisco Secure Client found. Skipping automated VPN start.
  echo    If SQL is unreachable below, connect your VPN manually and re-run.
  goto aftervpn
)
"!VPNCLI!" status 2>nul | findstr /i /c:"state: Connected" >nul
if not errorlevel 1 (
  echo    Already connected.
  goto aftervpn
)
echo    Not connected. Attempting to connect to aavpn.alignedautomation.com ...
echo    ^(you will be prompted for credentials; MFA may require the desktop app^)
"!VPNCLI!" connect aavpn.alignedautomation.com
"!VPNCLI!" status 2>nul | findstr /i /c:"state: Connected" >nul
if not errorlevel 1 (
  echo    Connected.
) else (
  echo    CLI connect did not complete -- launching the Cisco Secure Client UI so you
  echo    can sign in ^(SAML/MFA logins cannot be completed from the command line^).
  start "" "C:\Program Files (x86)\Cisco\Cisco Secure Client\csc_ui.exe" 2>nul
  echo    Waiting up to 90s for the tunnel ...
  powershell -NoProfile -Command "$d=(Get-Content 'backend\config.json' -Raw | ConvertFrom-Json).sql; for($i=0;$i -lt 30;$i++){ if(Test-NetConnection $d.server -Port 1433 -InformationLevel Quiet -WarningAction SilentlyContinue){exit 0}; Start-Sleep 3 }; exit 1"
  if errorlevel 1 (
    echo    Still no route to the SQL host. Connect the VPN and re-run,
    echo    or use the file-upload mode in the console ^(no SQL needed^).
  ) else (
    echo    Tunnel is up.
  )
)
:aftervpn

REM ------------------------------------------------------ 5. SQL reachability
echo.
echo [5/9] SQL host reachability
powershell -NoProfile -Command "$c=(Get-Content 'backend\config.json' -Raw | ConvertFrom-Json).sql; $s=$c.server; if(-not $s -or $s -like 'YOUR_*'){ Write-Host ('   config.json has no real server yet: '+$s); exit 2 }; if(Test-NetConnection $s -Port 1433 -InformationLevel Quiet -WarningAction SilentlyContinue){ Write-Host ('   '+$s+':1433 reachable'); exit 0 } else { Write-Host ('   '+$s+':1433 NOT reachable'); exit 1 }"
if errorlevel 2 (
  echo    Fill in backend\config.json before using live SQL.
  echo    You can still use the console's "Upload weekly file" mode.
) else if errorlevel 1 (
  echo    Live SQL will fail until the VPN is up. The UI and file-upload mode still work.
)

REM ------------------------------------------------------------- 6. free port
echo.
echo [6/9] Port 8000
if defined TESTS_ONLY (
  echo    Leaving the running backend alone ^(--tests-only^)
  goto afterport
)
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if($c){ foreach($x in $c){ Write-Host ('   stopping PID '+$x.OwningProcess+' already on :8000'); try{ Stop-Process -Id $x.OwningProcess -Force -ErrorAction Stop }catch{} } Start-Sleep -Milliseconds 1200 } else { Write-Host '   free' }"
:afterport

REM --------------------------------------------------------- 7. start backend
echo.
if defined TESTS_ONLY (
  echo [7/9] Using the already-running backend
  goto afterstart
)
echo [7/9] Starting backend on http://localhost:8000
start "RCA backend" /min cmd /c "cd /d "%~dp0backend" && python -m uvicorn sql_backend:app --host 0.0.0.0 --port 8000"
echo    waiting for /api/health ...
powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){ try{ $r=Invoke-RestMethod http://localhost:8000/api/health -TimeoutSec 4; Write-Host ('   health: status='+$r.status+' configured='+$r.configured+' table='+$r.table); exit 0 }catch{ Start-Sleep 2 } }; exit 1"
if errorlevel 1 (
  echo    ERROR: backend did not answer within ~60s. Check the "RCA backend" window.
  goto fail
)
:afterstart

REM ------------------------------------------------------------- 8. test suites
echo.
echo [8/9] Test suites
if not defined RUN_SMOKE if not defined RUN_VALIDATE if not defined RUN_LLM (
  echo    none requested ^(use --smoke / --validate / --llm / --all^)
)
if defined RUN_SMOKE (
  echo.
  echo    --- per-module smoke test ^(12 modules, no SQL/LLM needed^) ---
  pushd backend & python "..\results\smoke_test_modules.py" & set "RC=!errorlevel!" & popd
  if not "!RC!"=="0" echo    SMOKE TEST FAILED ^(exit !RC!^)
)
if defined RUN_VALIDATE (
  echo.
  echo    --- SQL cross-check suite ^(5 queues x 8 checks, needs VPN^) ---
  pushd backend & python "..\results\run_validation.py" & set "RC=!errorlevel!" & popd
  if not "!RC!"=="0" echo    VALIDATION FAILED ^(exit !RC!^)
)
if defined RUN_LLM (
  echo.
  echo    --- LLM ranking verification ^(3 queues, needs VPN + an LLM key^) ---
  echo        NVIDIA takes 45-100s per investigation; this is not hung.
  pushd backend & python "..\results\run_llm_ranking.py" & set "RC=!errorlevel!" & popd
  if not "!RC!"=="0" echo    LLM RANKING RUN FAILED ^(exit !RC!^)
)

REM ---------------------------------------------------------------- 9. browser
echo.
echo [9/9] Console
if defined SKIP_BROWSER (
  echo    not opening a browser ^(--no-browser^)
) else (
  start "" "http://localhost:8000/rca_console.html"
  echo    opened http://localhost:8000/rca_console.html
)

echo.
echo ===========================================================================
echo   Ready.  http://localhost:8000/rca_console.html
echo.
echo   Notes
echo     * Pick an NVIDIA model in the RCA model picker. Groq is fast but has a
echo       100,000 token/DAY cap -- once spent, every call 429s and the engine
echo       falls back to its deterministic finding ^(honest, but not the LLM^).
echo     * An NVIDIA investigation takes 45-100s. That is normal, not a hang.
echo     * The WFM engine is opt-in per request:
echo         POST /api/rca-investigate?mode=wfm
echo       See IMP_DOCS\wfm-rca-engine.md
echo     * Evidence and audit trail live in results\ ^(start with audit-log.md^).
echo     * Backend runs in the minimised "RCA backend" window -- close it to stop.
echo ===========================================================================
goto end

:fail
echo.
echo ===========================================================================
echo   Setup stopped. Fix the item above and re-run.
echo   Offline fallback: open rca_console.html directly and use
echo   "Upload weekly file" -- no backend and no SQL required.
echo ===========================================================================
exit /b 1

:end
endlocal
exit /b 0
