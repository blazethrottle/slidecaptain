# SlideCaptain의 Codex 진입 지침

프로젝트 정본은 `CLAUDE.md`와 거기 연결된 문서다. 아래 기준으로 현재 요청에 필요한 절만 읽고, 본문이 요구하는 관련 명세·검증은 생략하지 않는다. Claude 전용 import·훅·스킬이 Codex에서도 실행된다고 가정하지 않는다.

- 상태 확인·작업 재개: `CLAUDE.md`의 「진본 문서」에서 해당 작업의 최신 인계와 로드맵을 찾고 실제 브랜치·구현과 대조한다. 과거 조사 전체를 반복하지 않는다.
- 기능·코드 변경: 「관례」와 해당 기능의 설계·계획을 읽는다. 상태 변경 API, AI 동의, 생성 모델·OpenAPI·프런트 타입 동기화 규약을 유지한다. 기존 사용자 변경을 보존한다.
- 테스트·빌드: 「명령」을 읽고 변경 영향에 맞게 검증한다. 작업 트리에서 공유 가상환경을 사용하면 `PYTHONPATH=<현재 작업 트리>/backend`로 현재 코드를 검증한다.
- 커밋·푸시·리뷰: 「관례」와 「푸시 전 검증과 CI」를 읽는다. 독립 리뷰가 필요한 단계는 실제 제공되는 리뷰 경로로 수행하고, 미수행을 완료로 표시하지 않는다.
- 단순 문구 수정·경로 확인: 관련 파일과 해당 제약만 확인한다. 전체 설계·개발 절차를 자동 시작하지 않는다.
- 범용 개발 교훈: 코드를 바꾸기 전에 `~/.agents/instructions/llm-wiki/engineering.md`를 읽는다(`CLAUDE.md` 「관례」의 범용 개발 교훈 줄).
- 기기에서 처음 개발할 때 점검(2026-10-18): ① `git commit`이 되는지 확인한다. 샌드박스가 `.git` 쓰기를 막으면 우회하지 말고 멈춰 보고한다. ② `npm install`과 `gh run watch`처럼 네트워크가 필요한 명령이 되는지 확인한다. ③ 시작 문서는 `CLAUDE.md` 「진본 문서」 맨 위의 최신 인계 줄이다.

AI는 보고 논리와 표현을 설계하고 코드는 배치를 계산한다. 생성 성공·템플릿 수·테스트 통과는 실제 보고서 품질이나 PowerPoint 표시 검증을 대신하지 않는다. 승인된 작업 단위까지 구현·검증하고 완료·미완료·실제 AI 및 화면 검증 여부를 구분해 인계한다. 다음 단계로 자동 확장하지 않는다.

## Cursor Cloud specific instructions

- 이 이미지의 기본 Python은 3.12다. 앱은 3.13만 받는다. `install`이 `uv`로 3.13을 두고 `backend/.venv`에 개발 의존성(`[dev,desktop]`, `requirements-release.txt` 제약)을 설치한다. 테스트는 `backend`에서 `PYTHONUTF8=1 .venv/bin/python -m pytest tests -q`다. 시스템 `python3`로 pytest를 돌리지 않는다.
- Node는 이미지의 22.23.4다. `frontend/package.json`의 `engines`(`>=22.17.1`)를 만족한다. CI가 쓰는 정확한 판은 `.nvmrc`의 22.17.1이다. 프런트는 `frontend`에서 `npm ci`, `npm test`, `npm run build`. 독립 앱 런타임 테스트는 `desktop`에서 `npm test`다.
- `start`는 두 tmux 세션을 켠다. `slidecaptain-api`는 `http://127.0.0.1:8765`(API, `frontend/dist`가 있으면 빌드된 화면). `slidecaptain-web`은 `http://127.0.0.1:5173`(Vite, `/api`는 8765로 프록시). 8765에서 화면을 보려면 `frontend`에서 `npm run build`를 한 번 실행한다. 자료 폴더는 `~/.slidecaptain-cloud/data`다. `~/slidecaptain-projects`는 쓰지 않는다.
- 프로젝트 만들기와 초안 내보내기는 AI 로그인 없이 된다. 환경 확인에서 실제 Claude/ChatGPT 호출을 하지 않는다.
