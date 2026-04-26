@echo off
setlocal
echo ============================================
echo   Fantasy Cricket - Setup
echo ============================================
echo.

set "PYTHON_EXE=python"
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"

echo [1/3] Installing backend dependencies...
%PYTHON_EXE% -m pip install -r backend\requirements.txt
if errorlevel 1 (echo FAILED: pip install & exit /b 1)
echo.

echo [2/3] Installing frontend dependencies...
cd frontend
call npm install
if errorlevel 1 (echo FAILED: npm install & exit /b 1)
cd ..
echo.

echo [3/3] Seeding database...
%PYTHON_EXE% -m backend.scripts.seed_db
if errorlevel 1 (echo FAILED: seed_db & exit /b 1)
echo.

echo ============================================
echo   Setup complete!
echo   Run 'start.bat' to launch the app.
echo ============================================
endlocal
