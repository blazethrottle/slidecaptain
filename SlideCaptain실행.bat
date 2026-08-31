@echo off
rem Slide Captain 실행: 서버를 켜고 브라우저를 연다. 서버 창("Slide Captain server")을 닫으면 앱이 꺼진다.
cd /d "%~dp0backend"
set "URL=http://127.0.0.1:8765"
set "CURL=%SystemRoot%\System32\curl.exe"

rem 이미 서버가 떠 있으면(두 번 실행 등) 새로 켜지 않고 브라우저만 연다.
"%CURL%" -s -o NUL --max-time 1 %URL%/ && goto open

rem cmd /k: 서버가 오류로 바로 죽어도 창이 남아 오류 메시지를 읽을 수 있게 한다.
echo Slide Captain 서버를 켜는 중입니다. 잠시 기다려 주세요.
start "Slide Captain server" cmd /k .venv\Scripts\python.exe -m slidecaptain serve

rem 서버가 응답할 때까지 최대 30회 확인한다(회당 1~2초: curl 최대 1초 + ping 1초, 합쳐서 최대 1분 남짓). 응답하면 브라우저를 연다.
rem (종전의 고정 3초 대기는 첫 기동이 느린 상황에서 브라우저가 먼저 열려 빈 화면이 뜰 수 있었다. 2026-08-31 보강)
rem 1초 대기는 ping으로 한다: timeout 명령은 입력이 리다이렉트된 환경에서 즉시 종료되기 때문이다.
set /a tries=0
:wait
"%CURL%" -s -o NUL --max-time 1 %URL%/ && goto open
set /a tries+=1
echo 서버 응답 대기 중... (%tries%/30)
if %tries% geq 30 goto fail
ping -n 2 127.0.0.1 >nul
goto wait

:open
start "" %URL%
exit /b 0

:fail
echo 서버가 응답하지 않아 브라우저를 열지 않았습니다. "Slide Captain server" 창에 표시된 오류를 확인해 주세요.
echo 두 창을 모두 닫고 다시 실행해 보고, 같은 오류가 반복되면 그 오류 문구를 관찰지(기록 2)에 그대로 적어 주세요.
pause
exit /b 1
