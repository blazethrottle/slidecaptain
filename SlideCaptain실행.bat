@echo off
rem Slide Captain 실행: 서버를 켜고 브라우저를 연다. 이 창(서버 창)을 닫으면 앱이 꺼진다.
cd /d "%~dp0backend"
start "Slide Captain server" .venv\Scripts\python.exe -m slidecaptain serve
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8765
