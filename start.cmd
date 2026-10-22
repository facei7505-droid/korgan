@echo off
rem Qorgan: one double-click start on Windows (needs Docker Desktop running).
cd /d "%~dp0"
where docker >nul 2>nul || (echo [Qorgan] Docker not found. Install Docker Desktop. & pause & exit /b 1)
docker info >nul 2>nul || (echo [Qorgan] Docker Desktop is not running. Start it and try again. & pause & exit /b 1)
if exist .git (git pull --ff-only)
echo [Qorgan] Building and starting containers, first run takes 3-5 minutes...
docker compose up --build -d || (echo [Qorgan] Build failed, see the log above. & pause & exit /b 1)
echo [Qorgan] Waiting for the API...
powershell -NoProfile -Command "for($i=0;$i -lt 90;$i++){try{Invoke-RestMethod http://localhost:8000/health -TimeoutSec 2 | Out-Null; exit 0}catch{Start-Sleep 2}}; exit 1"
if errorlevel 1 (echo [Qorgan] API did not start. Last log lines: & docker compose logs api --tail 60 & pause & exit /b 1)
start "" http://localhost:5173/stage
echo.
echo [Qorgan] Ready:
echo   Stage (demo for judges): http://localhost:5173/stage
echo   Bank console:            http://localhost:5173/console
echo   API docs:                http://localhost:8000/docs
echo   Stop:                    docker compose down
pause
