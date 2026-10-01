@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0backend"

echo SlideCaptain: prepare an isolated PowerPoint review, with no AI calls.
echo Close the previous review server window before running this again.
where node >nul 2>nul
if errorlevel 1 goto missing_node
where npm >nul 2>nul
if errorlevel 1 goto missing_node
node -e "if(process.arch!=='x64'||Number(process.versions.node.split('.')[0])<22)process.exit(1)"
if errorlevel 1 goto missing_node

if exist "backend\.venv\Scripts\python.exe" goto check_python
py -3.13 -m venv "backend\.venv"
if not errorlevel 1 goto check_python
python -m venv "backend\.venv"
if errorlevel 1 goto missing_python
:check_python
"backend\.venv\Scripts\python.exe" -c "import sys;sys.exit(0 if sys.version_info>=(3,13) else 1)"
if errorlevel 1 goto missing_python
"backend\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); code=s.connect_ex(('127.0.0.1',8870)); s.close(); raise SystemExit(1 if code==0 else 0)"
if errorlevel 1 goto busy_port

echo Installing this checkout's backend and building the frontend...
"backend\.venv\Scripts\python.exe" -m pip --version >nul 2>nul
if errorlevel 1 goto use_uv
"backend\.venv\Scripts\python.exe" -m pip install -e "./backend[dev]"
if errorlevel 1 goto failed
goto frontend
:use_uv
where uv >nul 2>nul
if errorlevel 1 goto missing_pip
uv pip install --python "backend\.venv\Scripts\python.exe" -e "./backend[dev]"
if errorlevel 1 goto failed
:frontend
pushd frontend
call npm ci
if errorlevel 1 goto frontend_failed
call npm run build
if errorlevel 1 goto frontend_failed
popd

"backend\.venv\Scripts\python.exe" scripts\prepare_windows_review.py
if errorlevel 1 goto failed
set /p REVIEW_RUN=<"projects\windows-review\latest-run.txt"
start "" "%REVIEW_RUN%\index.html"
start "" "%REVIEW_RUN%"
start "SlideCaptain review server" cmd /k ""%~dp0backend\.venv\Scripts\python.exe" -m slidecaptain serve --data-dir "%REVIEW_RUN%\store" --port 8870"
set /a review_tries=0
:wait
"backend\.venv\Scripts\python.exe" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8870/api/status',timeout=1)" >nul 2>nul
if not errorlevel 1 goto ready
set /a review_tries+=1
if %review_tries% geq 30 goto server_failed
ping -n 2 127.0.0.1 >nul
goto wait
:ready
start "" "http://127.0.0.1:8870"
echo Ready. Save the feedback JSON from the form before closing it.
echo The samples and earlier feedback are preserved under projects\windows-review.
pause
exit /b 0

:frontend_failed
popd
goto failed
:missing_python
echo Python 3.13 or later is required. Ask the agent to repair the local setup.
goto failed
:missing_node
echo 64-bit Node.js 22 or later and npm are required. Ask the agent to check the local setup.
goto failed
:missing_pip
echo The existing virtual environment has neither pip nor an available uv installer.
goto failed
:busy_port
echo Port 8870 is already in use. Close the previous review server, then try again.
goto failed
:server_failed
echo The review server did not become ready. Check the SlideCaptain review server window.
goto failed
:failed
echo Preparation stopped. Existing projects and completed review folders were preserved.
echo Keep this error output and show it to the agent. Do not reset or delete the checkout.
pause
exit /b 1
