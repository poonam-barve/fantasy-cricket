@echo off
setlocal
echo ============================================
echo   Fantasy Cricket - Starting Servers
echo ============================================
echo.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo.
echo   Press Ctrl+C in each window to stop.
echo ============================================
echo.

set "PYTHON_EXE=python"
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
set "SKIP_DB_SEED=1"

echo Checking backend dependencies...
"%PYTHON_EXE%" -c "import fastapi, uvicorn, psycopg2" >nul 2>nul
if errorlevel 1 (
    echo Installing backend dependencies into the local Python environment...
    "%PYTHON_EXE%" -m pip install -r "%~dp0backend\requirements.txt"
    if errorlevel 1 (
        echo Failed to install backend dependencies.
        pause
        exit /b 1
    )
)

echo Bootstrapping local PostgreSQL database...
"%PYTHON_EXE%" -m backend.scripts.bootstrap_local_postgres
if errorlevel 1 (
    echo Local database bootstrap failed. Aborting startup.
    pause
    exit /b 1
)

:: Start backend in a new window
start "Fantasy Cricket - Backend" cmd /k "cd /d %~dp0 && %PYTHON_EXE% -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

:: Wait a moment for backend to start
timeout /t 3 /nobreak >nul

:: Start frontend in a new window
start "Fantasy Cricket - Frontend" cmd /k "cd /d %~dp0\frontend && npx vite --host 0.0.0.0 --port 5173"

:: Wait and open browser
timeout /t 5 /nobreak >nul
start http://localhost:5173

echo Both servers started. Browser opening...
endlocal
