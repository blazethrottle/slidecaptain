# 파일럿 소형 개선 묶음 계획서 (2026-09-01)

> 실전 파일럿 첫 실행(2026-09-01)에서 사용자가 관찰한 5건 중, 사용자 결정(A안, 2026-09-01)으로 "파일럿 완주 후 즉시 반영"하기로 한 소형 4건의 구현 계획이다.
> 나머지(PDF와 Word 추출, 밀도 3단계와 표 중심 체크, 설정 페이지, 차트 템플릿)는 [로드맵](2026-08-27-mvp-roadmap.md) 이월표에 단계 5 항목으로 등재했다.
> 브랜치: `feature/pilot-fixes-bundle` (실행 스크립트 브랜치 `feature/pilot-launcher-wait` 위에서 분기. 머지는 두 브랜치를 순서대로 main에 넣는다).
> 적대 리뷰 1회(2026-09-01, 수정 후 승인) 반영본. 반영 내역은 문서 끝 "리뷰 반영" 절.

## 범위와 원칙

| 태스크 | 내용 | 관찰 출처 |
|---|---|---|
| 1 | 구조안 폼 배치: 목표 장수와 지시사항을 각각 한 줄로, 지시사항 입력란 확대 | 관찰 2, 3 |
| 2 | 자료 파일 업로드 API: 텍스트 파일(.md, .txt, .csv)을 원시 바이트 본문으로 받아 인코딩 폴백 후 UTF-8로 저장 | 관찰 1 |
| 3 | 자료 화면 업로드 UI: 끌어다 놓기 영역 + 파일 선택, 같은 이름은 확인 후 덮어쓰기 | 관찰 1 |
| 4 | AI 연결 상태 한 줄: 프로젝트 목록 상단에 로그인 여부(`claude auth status`)와 마지막 생성 성공 시각 | 관찰 5 |

원칙: 기존 관례 유지(TDD, 태스크 단위 커밋, 태스크별 독립 리뷰, 브랜치 최종 리뷰). 진행 중인 파일럿을 건드리지 않기 위해 `frontend/dist` 교체와 8765 서버 재시작은 사용자가 파일럿 종료를 알릴 때까지 하지 않는다. 관통 검증은 별도 포트(8766)와 임시 데이터 폴더, 임시 빌드 폴더로 한다.

범위 밖(이월표 참조): PDF와 Word 추출, 밀도 선택, 설정 페이지, 연결 확인 실호출 버튼, 자료 화면 안내 문구의 성공과 오류 완전 분리(이번에는 업로드 결과 안내만 성공용 문구 영역을 새로 둔다).

## 태스크 1: 구조안 폼 배치

현재 `StructureScreen.tsx:148-158`의 `label` 두 개와 버튼이 스타일 없이 한 줄에 흐르고, `textarea`에 줄 수가 없어 브라우저 기본 2줄이다.

변경:
- 각 `label`을 `.field` 클래스 `div`로 감싸 세로 배치. 지시사항 `textarea`는 `rows={5}`.
- `styles.css`에 규칙 추가: `.structure-screen .field { display: grid; gap: 4px; max-width: 640px; margin: 8px 0; }`, `.structure-screen textarea { width: 100%; min-height: 110px; font: inherit; }`, `.structure-screen input[type="number"] { width: 8em; }`, 버튼 행 `.structure-screen .actions { margin-top: 8px; }`.
- 라벨 문구는 유지한다("목표 장수 (비우면 AI가 정함)", "지시사항"). 기존 테스트가 `getByLabelText`로 찾으므로 aria-label도 유지.

테스트(`StructureScreen.test.tsx`): 지시사항 `textarea`의 `rows`가 5인지, 목표 장수 입력과 지시사항 입력의 가장 가까운 `.field` 조상이 서로 다른 요소인지 단언한다(한 줄 배치로 회귀하면 실패하도록 구조를 고정).

## 태스크 2: 자료 파일 업로드 API

인터페이스:
- `POST /api/projects/{name}/sources/{filename}/upload?overwrite=false`. 본문은 파일의 원시 바이트(Content-Type 무관, 멀티파트 아님). 응답 `UploadResult { filename: str, chars: int }`.
- 멀티파트 대신 원시 본문을 쓰는 이유(리뷰 발견 1): 멀티파트 파싱은 `python-multipart`가 필요한데 `pyproject.toml`에 선언되어 있지 않고, 이 앱은 파일 1개씩만 받으므로 원시 본문이면 의존성 없이 충분하다. 파일명은 기존 자료 API처럼 경로 인자로 받아 같은 인코딩 관례(`encodeURIComponent`)를 탄다.
- 판정 순서: ① 확장자를 소문자로 정규화한 뒤 `.md`, `.txt`, `.csv`가 아니면 422("지원하지 않는 형식입니다. 지금은 .md, .txt, .csv 텍스트 파일만 넣을 수 있고, PDF와 Word는 아직 지원하지 않습니다") ② 본문이 5MB를 넘으면 422("파일이 너무 큽니다(5MB 한도)") ③ 파일명은 `Path(filename).name`으로 경로 부분을 제거한 뒤 기존 이름 규칙(`_validate_name`)을 통과해야 함(실패 시 기존 `InvalidName` 422) ④ 같은 이름이 있고 `overwrite=false`면 409("같은 이름의 자료가 이미 있습니다") ⑤ 디코딩은 기존 순서(utf-8-sig, cp949) 실패 시 기존 `InvalidSourceEncoding` 422 ⑥ `write_source`로 UTF-8 저장(저장 시점에 UTF-8로 정규화).

구현:
- `file_store.py`: `read_source`의 인코딩 폴백을 `decode_source_bytes(data, filename) -> str` 헬퍼로 추출하고(`read_bytes` + `decode`는 `read_text`와 동일한 strict 디코딩이라 동작 불변), `source_exists(name, filename) -> bool`을 추가한다. 업로드 저장은 기존 `write_source`를 그대로 쓴다.
- `app.py`: 라우트 추가(`async def`, `await request.body()`). 확장자와 크기 판정은 라우트에서 `HTTPException(422)`로, 이름과 인코딩은 저장소 예외 매핑을 그대로 탄다. 409는 `HTTPException(409)`.
- OpenAPI 스키마 덤프와 TS 타입 재생성(`scripts/dump_openapi.py`, `npm run generate-types`)을 태스크 4 백엔드와 함께 1회 수행해 커밋한다.

테스트(`tests/test_api_upload.py`, 기존 `store`, `client` 픽스처 방식): UTF-8 파일 업로드 후 목록과 본문 확인 / cp949 바이트 업로드가 한글로 복원됨 / `.pdf` 422와 안내 문구 / 대문자 확장자 `.MD` 200(리뷰 발견 4) / 5MB 초과 422 / 같은 이름 409 후 `overwrite=true` 200 / 경로가 섞인 파일명은 `name` 부분만 쓰되 규칙 위반(`..md` 같은 것)이면 422 / 바이너리 쓰레기 422 / 빈 파일 200(0자) / 없는 프로젝트 404 / `decode_source_bytes` 추출 후 기존 `read_source` 테스트가 그대로 통과.

## 태스크 3: 자료 화면 업로드 UI

`client.ts`:
- `uploadSource(name, file: File, overwrite: boolean) => Promise<UploadResult>`: `fetch`에 `body: file`을 그대로 넘기고 JSON `Content-Type`을 붙이지 않는다. 오류 처리는 `request()`의 실패 분기를 `throwIfFailed(r)` 헬퍼로 분리해 공유한다(기존 동작 불변).

`SourcesScreen.tsx` 자료 목록 아래:
- 끌어다 놓기 영역 `<div className="drop-zone" onDragOver={막기} onDrop={받기}>`에 안내 문구("파일을 여기에 끌어다 놓거나 아래에서 선택하세요. 지금은 .md, .txt, .csv만 되고, 생성 시 자료 합계 10만 자 한도가 적용됩니다")와 `<input type="file" multiple accept=".md,.txt,.csv" aria-label="자료 파일 선택">`. `onDragOver`에서 `preventDefault`를 해야 drop 이벤트가 발생한다.
- 처리 `importFiles(files)`: 순서대로 업로드. 409면 `window.confirm("같은 이름의 자료 X가 있습니다. 덮어쓸까요?")` 후 승낙 시 `overwrite=true`로 재시도, 거절 시 건너뜀. 끝나면 목록을 다시 불러오고 마지막으로 올린 파일을 연다. 결과 안내는 성공용 `info` 영역(`<p className="info">`, role=alert 아님)에 "N개 자료를 추가했습니다"로, 실패한 파일은 기존 `notice`(role=alert)에 파일명과 서버 문구를 그대로 표시한다. 성공 집계와 실패 안내는 서로 덮어쓰지 않는다.

테스트:
- `client.test.ts`(리뷰 발견 6): `uploadSource` 호출 시 `fetch`의 `body`가 넘긴 `File` 객체이고, `headers`에 `Content-Type`이 없으며, URL에 인코딩된 파일명과 `overwrite` 쿼리가 들어가는지 단언.
- `SourcesScreen.test.tsx`: 파일 선택 입력에 `userEvent.upload`로 파일 2개를 올리면 `uploadSource`가 순서대로 호출되고 목록을 다시 불러오며 info에 "2개"가 보임 / `fireEvent.drop`(dataTransfer.files)으로도 호출됨 / 첫 호출이 409 `ApiError`를 던지면 `confirm` 승낙 시 `overwrite=true`로 재호출, 거절 시 재호출 없음 / 2개 중 둘째가 422로 실패하면 info에 "1개", role=alert 영역에 둘째 파일명과 서버 문구가 함께 표시됨(리뷰 발견 7).

## 태스크 4: AI 연결 상태 한 줄

백엔드 `pipeline/auth_status.py`(신규):
- `resolve_cli_path() -> Path | None`: 환경 변수 `SLIDECAPTAIN_CLAUDE_CLI` → SDK 동봉 CLI(`claude_agent_sdk/_bundled/claude.exe` 또는 `claude`) → `shutil.which("claude.exe")`(Windows) → `shutil.which("claude")` 순서. `which` 결과가 `.cmd`나 `.bat`이면 채택하지 않는다(리뷰 발견 2. 근거 정정 2026-09-01: 배치 파일도 `shell=False`로 실행은 되지만, SDK는 인자가 cmd.exe에서 재해석되는 위험 때문에 이를 거부하므로, 표시용이 생성 파이프라인과 다른 CLI를 채택해 "로그인됨인데 생성은 실패"하는 불일치가 생기지 않도록 같은 기준을 따른다). 생성 파이프라인이 실제로 쓰는 것이 동봉 CLI이므로 동봉을 먼저 본다.
- `check_login(timeout_sec=10) -> LoginStatus`: `[cli, "auth", "status"]`를 `subprocess.run`으로 실행해 표준 출력의 JSON(`loggedIn`, `authMethod`, `email`)을 읽는다. `LoginStatus { logged_in: bool | None, auth_method: str | None, account: str | None, cli_version: str | None, error: str | None }`. CLI 부재, 실행 실패(`OSError` 전반), 시간 초과, JSON 해석 실패, JSON에 `loggedIn` 불리언이 없는 경우는 모두 `logged_in=None`과 한국어 `error`로 보고한다(예외로 서버를 멈추지 않는다. 2026-09-01 구현 리뷰 반영: 종료 코드가 0이 아니어도 JSON이 있으면 해석한다. 로그아웃 상태가 0이 아닌 코드로 끝날 수 있기 때문이다. `loggedIn` 키 부재를 "로그인 안 됨"으로 읽으면 사용자에게 불필요한 재로그인을 지시하게 되므로 "확인 불가"로 보낸다). `account`는 `mask_email`로 가린다(앞 2자 + `***` + `@도메인`).
- 자격 증명 파일은 읽지 않는다(토큰이 들어 있다). CLI 출력의 위 3개 필드 외에는 전달하지 않는다.

`app.py`:
- `create_app(..., login_checker: Callable[[], LoginStatus] | None = None)`: 기본은 `check_login`. 결과는 60초 캐시(연속 새로고침마다 프로세스를 띄우지 않기 위해).
- `GET /api/status`(동기 `def`로 선언해 스레드풀에서 실행. `subprocess.run`이 이벤트 루프를 막지 않게) → `AppStatus { provider: "subscription" | "none", login: LoginStatus, model: str | None, last_generation_at: str | None, checked_at: str }`. `model`은 `getattr(provider, "model", None)`. `last_generation_at`은 구조안 생성, 장별 생성, 축약(condense)의 세 라우트가 `status == "ok"`로 끝날 때 갱신하는 앱 상태(리뷰 발견 3. 프로세스 메모리, 재시작 시 초기화. 파일에 남기지 않는다).

프런트 `ProjectList.tsx`: 마운트 시 `api.getStatus()` 호출. `<p className="ai-status">` 한 줄:
- 로그인됨: "AI 연결: 로그인됨 (claude.ai, co***@example.com). 마지막 생성 성공: 2026-09-01 09:52" (성공 이력 없으면 "아직 없음")
- 로그인 안 됨: "AI 연결: 로그인되지 않았습니다. 터미널에서 claude 명령으로 로그인한 뒤 서버 창을 닫고 SlideCaptain실행.bat을 다시 실행해 주세요."
- 확인 불가: "AI 연결: 확인하지 못했습니다 (서버 오류 문구, CLI 버전)".
상태 조회 실패는 목록 표시를 막지 않는다(별도 문구, role=alert 아님).

테스트: `tests/test_auth_status.py`(`mask_email`, `.cmd` 배제, 가짜 `subprocess.run`으로 JSON 해석, CLI 부재와 `OSError` 시 error) / `tests/test_api_status.py`(가짜 `login_checker`로 200 본문, 가짜 프로바이더로 생성과 축약 성공 후 `last_generation_at`이 채워짐, 캐시 60초 안에는 checker 1회 호출) / `ProjectList.test.tsx`(세 문구 분기. 기존 3개 테스트의 `vi.mock` 팩토리에 `getStatus: vi.fn()`과 기본 응답을 추가한다: 리뷰 발견 5).

## 실행 순서와 검증

1. 태스크 1 → 2 → 4(백엔드) → 타입 재생성 커밋 → 3 → 4(프런트). 태스크마다 커밋과 독립 리뷰.
2. 브랜치 최종 리뷰 후 관통 검증: `vite build --outDir <임시 폴더>`로 화면을 빌드하고, `create_app(store, provider, static_dir=<임시 폴더>)`를 8766 포트로 띄우는 스크래치 스크립트로 업로드(UTF-8, cp949, 한글 파일명, 중복 409)와 상태 한 줄을 브라우저에서 확인한다. 8765의 파일럿 서버와 `frontend/dist`는 건드리지 않는다.
3. 사용자가 파일럿 종료를 알리면: 머지 선택 → `npm run build` → 서버 재시작 안내.

## 이 계획이 틀렸을 가능성

- 경로 인자의 한글 파일명: 기존 `writeSource`가 같은 방식으로 한글 이름을 이미 다루고 있어 새 위험은 아니지만, 관통 검증에서 한글 파일명 1건을 반드시 포함한다.
- `claude auth status`의 출력 형식은 CLI 버전에 따라 바뀔 수 있다(이 PC의 2.1.251과 동봉 2.1.247에서 JSON 확인). 해석 실패는 "확인하지 못했습니다"로 떨어지므로 서버는 멈추지 않지만 표시는 무의미해진다. 해석 실패 문구에 CLI 버전을 함께 보여 사용자가 알아차리게 한다.
- 60초 캐시는 사용자가 방금 로그인한 직후 최대 60초 동안 옛 상태를 보여준다. 로그인 절차가 서버 재시작을 포함하므로 실사용에서는 드러나지 않는다.
- 업로드 5MB 상한과 생성 시 합계 10만 자 상한은 크게 어긋난다. 업로드는 되는데 생성에서 막히는 경험을 줄이기 위해 끌어다 놓기 영역 안내에 10만 자 한도를 적어 둔다.

## 리뷰 반영 (2026-09-01, 적대 리뷰 발견 7건)

| 발견 | 반영 |
|---|---|
| 1 `python-multipart` 미선언 | 멀티파트를 버리고 원시 바이트 본문 업로드로 변경(의존성 추가 없음) |
| 2 CLI 탐색 순서가 `.cmd` 셰도를 못 막음 | 동봉 CLI 우선, `which` 결과의 `.cmd`와 `.bat` 배제, `OSError` 전반을 "확인 불가"로 처리 (배제 근거 문장은 2026-09-01 구현 리뷰에서 정정: 위 태스크 4 본문) |
| 3 축약 라우트가 성공 시각 갱신에서 빠짐 | 세 라우트 모두 갱신 |
| 4 확장자 대소문자 | 소문자 정규화, `.MD` 테스트 추가 |
| 5 목록 화면 기존 테스트의 모의 누락 | `getStatus` 모의를 기존 테스트에 추가 |
| 6 `uploadSource` 전송 형태의 단위 테스트 부재 | `client.test.ts`에 케이스 추가 |
| 7 다중 파일 부분 실패 테스트 부재 | `SourcesScreen.test.tsx`에 케이스 추가 |
