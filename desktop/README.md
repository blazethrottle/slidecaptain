# 독립 앱 D1 실행 기반

승인된 개정판의 선행 기술 검증이다. 기존 제품 화면을 독립 창에서 실행한다.
새 10종 대표 페이지와 직접 수정 UI는 `docs/design/2026-10-02-revision-wireframe.html`의
승인 시안이며 제품 연결은 D3 후속이다.

Python 3.13과 Node 22.17.1 이상이 개발에 필요하다. 배포 서비스에는 Python/UI가
포함되지만 공식 Claude Code/Codex CLI와 로그인 정보는 포함하지 않는다.

저장소 루트에서 백엔드 가상환경을 준비하고 `backend[dev,desktop]`을 설치한 뒤:

```sh
cd frontend
npm ci
npm run build
cd ../desktop
npm ci
npm test
npm run dev
```

개발 서비스 기본 Python은 `backend/.venv/bin/python`(Windows는 `Scripts/python.exe`)이다.
다른 위치는 `SLIDECAPTAIN_PYTHON`으로 지정한다. 자료 기본 위치는 기존
`~/slidecaptain-projects`이며 `SLIDECAPTAIN_DATA_DIR`로 변경할 수 있다.
설치 폴더와 분리해서 재설치 시 자료를 보존한다.

현재 호스트 OS용 패키징 예시(출력은 체크아웃 밖의 **새** 폴더):

```sh
backend/.venv/bin/python scripts/build_desktop_service.py --out-dir /tmp/slidecaptain-service-proof
node desktop/scripts/smoke-service.cjs /tmp/slidecaptain-service-proof/slidecaptain-service/slidecaptain-service
cd desktop
SLIDECAPTAIN_BACKEND_RESOURCE=/tmp/slidecaptain-service-proof/slidecaptain-service \
SLIDECAPTAIN_DESKTOP_OUTPUT=/tmp/slidecaptain-app-proof npm run dist -- --dir
```

Windows에서는 가상환경 Python과 frozen 서비스의 `.exe` 경로를 쓰고 PowerShell
환경 변수 문법으로 두 출력 경로를 지정한다. macOS/Windows는 각각 해당 OS에서
빌드한다. `--dir`는 미서명 검증 패키지이며 사용자 배포용 서명·공증·설치 프로그램
검증은 완료하지 않았다. CI의 두 호스트에 빌드/동일 smoke를 추가했으며 실제 CI
실행 결과 없이 양 OS 통과를 주장하지 않는다.

서비스는 자신의 127.0.0.1 포트와 매번 다른 인증 세션을 생성한다. 세션은 main과
서비스만 보유한다. renderer는 정해진 API와 main이 선택한 문서의 바이트만
사용한다. AI 동의·ETag는 기존 API 계약을 유지한다. HTTP 취소는 기존 웹과 같이
연결을 끊으며, 서버의 취소 지원 범위는 해당 API 계약을 따른다.

문서 선택 IPC와 폴더 IPC는 기반만 구현했다. 개정판 파일/폴더 선택 버튼,
내보내기 저장 대화상자, 프로필 관리 화면은 후속 연결 대상이다. HWP 확장자
선택 허용은 실제 내용 추출 지원 완료를 뜻하지 않는다.
