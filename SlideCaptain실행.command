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
  open "$URL"
  exit 0
fi

echo "Slide Captain 서버를 켜는 중입니다. 잠시 기다려 주세요."
"$PYTHON_BIN" -m slidecaptain serve &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' EXIT INT TERM HUP

# 서버가 응답할 때까지 최대 30회(회당 1초) 확인한다. 응답하면 브라우저를 연다.
tries=0
while [ "$tries" -lt 30 ]; do
  if curl -s -o /dev/null --max-time 1 "$URL/"; then
    echo "이 창이 서버 창입니다. 창을 닫거나 Ctrl+C 를 누르면 서버가 멈춥니다."
    open "$URL"
    wait "$SERVER_PID"
    exit 0
  fi
  tries=$((tries + 1))
  echo "서버 시작 대기 중... ($tries/30)"
  sleep 1
done

echo "서버가 응답하지 않아 브라우저를 열지 않았습니다. 위에 표시된 오류를 확인해 주세요."
exit 1
