@echo off
REM ===========================================================================
REM  load_to_sql.bat -- push the two source files into SQL Server.
REM
REM  Run this yourself whenever the VPN is stable. It is SAFE TO RE-RUN: each
REM  table is dropped and recreated from the file, so a half-finished run caused
REM  by a dropped VPN just gets fixed by running it again.
REM
REM  Usage:
REM     load_to_sql.bat                 load both files
REM     load_to_sql.bat --check         only report row counts + mapping coverage
REM     load_to_sql.bat --dry-run       parse the files and print the schema, no DB writes
REM
REM  WHAT IT LOADS  (paths come from backend\config.json)
REM     file1.csv                       -> dbo.Input_To_ML_P1     (the RCA dataset)
REM     CQN and FC mapping (1).xlsx     -> dbo.CQN_Mapping        (Sheet1, flat + dimensions)
REM                                     -> dbo.CQN_Forecast_Pair  (Sheet3 Data Pair)
REM
REM  WHAT IT DOES NOT TOUCH
REM     dbo.Input_To_ML -- the original 66,612-row table is LEFT ALONE, by request.
REM     Nothing here drops or edits it. To point the app back at it, change
REM     sql.table in backend\config.json.
REM ===========================================================================
setlocal
cd /d "%~dp0backend"

set "MODE="
if /i "%~1"=="--check"   set "MODE=check"
if /i "%~1"=="--dry-run" set "MODE=dry"

echo ===========================================================================
echo   Load source files into SQL Server
echo   %DATE% %TIME%
echo ===========================================================================

REM ---- prerequisites -------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 ( echo ERROR: Python is not on PATH. & goto :fail )
if not exist "config.json" ( echo ERROR: backend\config.json is missing. & goto :fail )

REM ---- is the SQL host reachable? (this is the bit the VPN breaks) ---------
REM  Skipped for --dry-run: that path only parses the files and prints the schema, so it has
REM  no business demanding a database connection.
if "%MODE%"=="dry" (
  echo.
  echo [1/4] Skipping the SQL reachability check ^(--dry-run writes nothing^)
  goto :aftercheck
)
echo.
echo [1/4] Checking the SQL host is reachable
powershell -NoProfile -Command "$c=(Get-Content 'config.json' -Raw | ConvertFrom-Json).sql; if(Test-NetConnection $c.server -Port 1433 -InformationLevel Quiet -WarningAction SilentlyContinue){ Write-Host ('   '+$c.server+':1433 reachable'); exit 0 } else { Write-Host ('   '+$c.server+':1433 NOT reachable'); exit 1 }"
if errorlevel 1 (
  echo.
  echo    The SQL host is not reachable. Connect the VPN and run this again.
  echo    Nothing was written, so re-running is safe.
  goto :fail
)

:aftercheck
if "%MODE%"=="check" goto :checkonly

REM ---- 1) the RCA dataset --------------------------------------------------
echo.
echo [2/4] Loading file1.csv into dbo.Input_To_ML_P1
echo        --min-week 0 --max-week 999999 keeps FY2024 history: the config filter was set
echo        for the old FY2025-2027 truncation and would silently drop 2,184 of 7,350 rows.
if "%MODE%"=="dry" (
  python upload_excel_to_sql.py --dry-run --table dbo.Input_To_ML_P1 --min-week 0 --max-week 999999
) else (
  python upload_excel_to_sql.py --table dbo.Input_To_ML_P1 --min-week 0 --max-week 999999
)
if errorlevel 1 ( echo    FAILED -- see the error above. Safe to re-run. & goto :fail )

REM ---- 2) the CQN mapping -------------------------------------------------
echo.
echo [3/4] Loading the CQN mapping into dbo.CQN_Mapping + dbo.CQN_Forecast_Pair
if "%MODE%"=="dry" (
  python upload_cqn_mapping.py --dry-run
) else (
  python upload_cqn_mapping.py --pairs
)
if errorlevel 1 ( echo    FAILED -- see the error above. Safe to re-run. & goto :fail )

if "%MODE%"=="dry" (
  echo.
  echo [dry-run] nothing was written to the database.
  goto :done
)

:checkonly
REM ---- 3) verify ----------------------------------------------------------
echo.
echo [4/4] Verifying
python -c "import sys; sys.path.insert(0,'.'); from sql_backend import load_config, connect; cfg=load_config(); conn=connect(cfg); cur=conn.cursor(); [ (cur.execute('SELECT COUNT(*) FROM '+t), print('   %-24s %8s rows' % (t, format(cur.fetchone()[0],',')))) for t in ('dbo.Input_To_ML','dbo.Input_To_ML_P1','dbo.CQN_Mapping','dbo.CQN_Forecast_Pair') ]; conn.close()"
echo.
python upload_cqn_mapping.py --coverage
if errorlevel 1 echo    NOTE: some queues are unmapped -- see the list above.

:done
echo.
echo ===========================================================================
echo   Done.  The app reads whichever table is set as sql.table in
echo   backend\config.json  (currently the P1 dataset).
echo   Restart the backend afterwards so it picks up any change:
echo       run.bat            ^(or restart uvicorn^)
echo ===========================================================================
endlocal
exit /b 0

:fail
echo.
echo ===========================================================================
echo   Stopped. Nothing was left half-written -- each table is recreated from
echo   its file, so simply run this again once the VPN is back.
echo ===========================================================================
endlocal
exit /b 1
