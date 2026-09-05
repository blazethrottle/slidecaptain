#!/bin/bash
# Slide Captain 실행: 서버를 켜고 브라우저를 연다. 이 창이 서버 창이며,
# 창을 닫거나 Ctrl+C 를 누르면 서버가 멈춘다.

cd "$(dirname "$0")/backend" || exit 1
BACKEND_DIR="$(pwd)"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
URL="http://127.0.0.1:8765"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "가상환경을 찾을 수 없습니다. README 의 macOS 개발 환경 구성을 먼저 해 주세요."
  exit 1
fi

# 이미 서버가 떠 있으면(두 번 실행 등) 새로 켜지 않고 브라우저만 연다.
if curl -s -o /dev/null --max-time 1 "$URL/"; then
  open "$URL" || echo "브라우저를 자동으로 열지 못했습니다. 브라우저에서 $URL 을 직접 열어 주세요."
  exit 0
fi

echo "Slide Captain 서버를 켜는 중입니다. 잠시 기다려 주세요."
"$PYTHON_BIN" -m slidecaptain serve &
SERVER_PID=$!

# 스크립트가 어떤 경로로 끝나든 배경 서버를 직접 정리한다. Ctrl+C(INT), 창 닫기(HUP), 종료 요청(TERM)
# 각각 명시적으로 종료 코드를 내며 끝낸다. 아래에서 블로킹 wait 대신 1초 주기의 생존 확인 루프를 쓰는
# 이유: macOS 기본 bash 3.2 는 wait 로 블로킹 중일 때 INT 트랩을 실행하지 못한다(D2-3 리뷰 실측).
stop_server() {
  kill "$SERVER_PID" 2>/dev/null
}
trap 'stop_server' EXIT
trap 'stop_server; exit 130' INT
trap 'stop_server; exit 143' TERM
trap 'stop_server; exit 129' HUP

# 서버가 응답할 때까지 최대 30회(회당 1초) 확인한다. 응답하면 브라우저를 연다.
tries=0
while [ "$tries" -lt 30 ]; do
  if curl -s -o /dev/null --max-time 1 "$URL/"; then
    echo "이 창이 서버 창입니다. 창을 닫거나 Ctrl+C 를 누르면 서버가 멈춥니다."
    open "$URL" || echo "브라우저를 자동으로 열지 못했습니다. 브라우저에서 $URL 을 직접 열어 주세요."
    while kill -0 "$SERVER_PID" 2>/dev/null; do
      sleep 1
    done
    echo "서버가 종료되었습니다."
    exit 0
  fi
  tries=$((tries + 1))
  echo "서버 시작 대기 중... ($tries/30)"
  sleep 1
done

echo "서버가 응답하지 않아 브라우저를 열지 않았습니다. 위에 표시된 오류를 확인해 주세요."
exit 1
