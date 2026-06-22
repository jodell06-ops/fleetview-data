@echo off
REM ── One-click REAL NOAA East Coast AIS pull (run on THIS Windows PC) ──
REM Downloads the latest NOAA daily file, filters to East Coast yacht traffic,
REM and drops a small CSV in automation\incoming\ for the tracker to ingest.
cd /d "%~dp0"
where python >nul 2>nul || (echo [X] Python 3 not found. Install from https://python.org then double-click this again. & pause & exit /b)
echo Installing requests (one time)...
python -m pip install --quiet requests
echo Pulling + filtering real NOAA East Coast AIS (this can take several minutes)...
python fetch_noaa.py
echo.
echo Done. A real AIS file should now be in automation\incoming\.
echo Tell Claude "process the new data" or wait for the Monday refresh.
pause
