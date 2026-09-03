# 단계 5A 묶음 A: 저장과 로컬 API 안전성 계획서 (2026-09-03)

> 마스터 플랜 [2026-09-01-phase5a-master-plan.md](2026-09-01-phase5a-master-plan.md) 묶음 A 의 상세 계획. D1 완료(2026-09-03) 뒤 착수한다.
> 브랜치 `codex/phase-5a` 에서 태스크마다 커밋하고, 태스크별 독립 리뷰와 묶음 최종 리뷰를 거친 커밋을 `origin/codex/phase-5a` 에 push 한다. main 머지는 5A 전체 완료 후다(사용자 결정 2026-09-03).
> 리뷰 게이트: 계획서 적대 리뷰 1회(2026-09-03 완료, 세 관점 30건 반영. 아래 "적대 리뷰 반영" 절) → 태스크별 TDD 구현(태스크마다 커밋) → 커밋별 독립 리뷰 → 묶음 최종 리뷰 → push.

## 범위와 원인 묶음

마스터 플랜이 A 의 산출물로 정한 것 가운데 프런트 저장 직렬화와 화면 이탈 게이트는 저장 안전성 소형 묶음(2026-09-03, main 7e5852d)에서 먼저 처리했다. 남은 것을 원인별로 묶는다.

| 태스크 | 포함 이월표 항목 | 공통 원인 |
|---|---|---|
| A1. 저장소 잠금과 고유 임시 파일과 내용 ETag | 고정 임시 파일 공유(아키텍처 감사), 오래된 덱이 최신 덱을 덮음(ETag), 내보내기 번호 경합(재심), 프로젝트 생성 경합(적대 리뷰) | `FileProjectStore` 가 요청 사이의 순서를 보장하지 않고, 임시 파일 이름이 고정이며, 저장본을 식별할 값이 없다 |
| A2. API 의 조건부 저장과 상태 변경 요청 보호 | `If-Match` 로 저장과 복원 전제 확인, 외부 사이트의 단순 POST 차단(보안 감사), 동시 내보내기, 업로드의 확인 후 쓰기 경합(적대 리뷰) | 라우트가 저장본 식별값을 주고받지 않고, 업로드만 커스텀 헤더를 요구하며, 확인과 쓰기가 잠금 밖에서 쪼개져 있다 |
| A3. 프리셋과 표 레이아웃 안전 검증 | 프리셋 음수와 비유한 값, 표 열 폭 음수(안전성 감사) | 프리셋은 하한 몇 개만 검증하고, 열 폭 산식이 최소 폭 보정의 초과분을 한 열에서 빼서 음수를 만든다 |
| A4. 이름 안전: NFC 정규화와 대소문자 충돌 | macOS NFD 이름 422(Mac 실측), 대소문자만 다른 자료 PUT 이 조용히 덮어씀(Mac 실측) | 이름 검증이 NFC 만 받고, 대소문자 무시 파일 시스템을 고려하지 않는다 |
| A5. 프런트: 식별값 전달과 충돌 안내, 저장 재시도, 창 닫기 경고, 자료 탭 보고 정보 플러시 | 저장 실패 후 재시도 수단 없음, beforeunload 경고(FC-15), 보고 정보 저장 응답 전 탭 전환(FC-07), 보고 정보 미저장 이탈(FC-12) | 클라이언트가 식별값과 요청 표식을 보내지 않고, 저장 실패의 회복 경로가 다음 편집뿐이며, 자료 탭은 이탈 플러시 밖에 있다 |

이 묶음에 넣지 않는 것: 별도 프로세스 사이의 파일 잠금(재심 기록대로 후속), 충돌 병합 UI, 사용자 계정과 원격 접속(마스터 플랜 "만들지 않는 것"), `snapshotNext` 잔존(스냅샷 규칙 변경은 별도. 충돌 복구의 `reset` 은 `snapshotNext` 를 끄고 `firstSave` 를 켜서 이 경로에서는 새 변형이 생기지 않게 한다), FC-13 리듀서 밖 apply(호출자 없음, 리팩터 기회), 템플릿 전환 안내(5B), `preset_overrides` 의 키 순서 정규화(아래 가정 1).

## 가정 (적대 리뷰가 검증한 것)

1. **ETag 는 저장된 `deck.json` 바이트의 SHA-256 16진수** 다. 전형 필드의 직렬화는 결정적이라 같은 덱을 두 번 저장하면 같은 값이다(실증). 단 `preset_overrides` 는 임의 dict 라 의미가 같아도 키 순서가 다르면 다른 값이 된다. 재시도는 같은 바이트를 다시 보내므로 실질 영향이 없고, 정규화는 범위 밖이다. 저장소 함수는 따옴표 없는 순수 16진수를 다루고, HTTP 계층만 큰따옴표로 감싼다(아래 A2).
2. **`If-Match` 가 없는 요청은 검사하지 않는다.** 이 앱의 화면은 항상 보내고(적대 리뷰가 네 경로 전부에서 PUT 전에 GET 또는 복원 응답이 먼저 착지함을 확인), 외부 도구는 종전처럼 동작한다. 불일치는 412 와 한국어 안내다. 위협 모델은 "여러 탭"이고 그 탭은 전부 이 앱 화면이다.
3. **상태 변경 요청 보호는 커스텀 헤더 요구가 본체이고 Origin 확인은 안전망** 이다. `X-Requested-With: SlideCaptain` 을 모든 POST, PUT, DELETE 에 요구한다. 이 헤더는 브라우저의 단순 요청 허용 목록 밖이라 다른 Origin 의 페이지가 붙이면 사전 확인(OPTIONS)이 먼저 가고, 이 서버는 CORS 헤더를 내지 않으므로 본 요청이 나가지 않는다(적대 리뷰가 OPTIONS 405 와 CORS 헤더 부재를 확인). Origin 확인은 헤더 요구가 나중에 완화되거나 새 라우트가 우회할 때를 위한 안전망이며 단독으로는 독자 방어가 아니다. 이것은 1인 로컬 앱의 방어이지 인증이 아니다.
4. **잠금은 같은 프로세스 안의 프로젝트별 재진입 잠금** 이다. uvicorn 이 동기 라우트를 스레드풀에서 돌리므로 겹친 요청은 실재한다(적대 리뷰가 동시 요청 5건이 서로 다른 스레드에서 병렬 실행됨을 확인). 생성 3종(async)은 저장소를 읽기만 하므로 잠금을 쥐고 await 하지 않는다. 별도 프로세스는 범위 밖이다.
5. **자료 탭 보고 정보는 이탈 시 자동 저장한다.** "보고 정보 저장" 버튼은 남기되, 저장 버튼을 누르지 않고 탭을 바꾸면 편집기와 같은 방식으로 플러시하고 실패하면 떠나지 않는다. 창 닫기 경고도 편집기와 자료 탭 양쪽의 미저장 상태에 건다(비대칭이면 FC-12 를 탭 전환에서만 막게 된다).
6. **412 를 받은 편집기는 자동으로 덮어쓰지 않는다.** 안내 문구와 "서버 내용으로 되돌리기" 버튼을 보이고, 사용자가 누르면 서버 덱을 다시 읽어 되돌리기 이력을 비우고, **부모(ProjectView)의 덱도 함께 갱신**해 다른 탭이 낡은 덱으로 최신본을 덮지 않게 한다. 구조안, 자료, 복구 화면의 412 는 전용 UI 없이 ProjectView 배너의 "서버 내용 다시 읽기" 로 회복한다. 로컬 편집을 보존하는 병합은 범위 밖이다.

## 태스크 A1: 저장소 잠금과 고유 임시 파일과 내용 ETag

**재현 (적대 리뷰 실측 2026-09-03)**

- `_write_deck` 이 `deck.json.tmp` 고정 이름에 쓰고 `os.replace` 한다. 스레드 8개가 100회씩 동시에 `save_deck` 을 부르면 `FileNotFoundError` 458건이 난다(이미 옮겨진 임시 파일을 다시 `replace` 하려는 경합). `write_source` 의 `.tmp-<이름>` 과 `save_global_preset` 의 `preset.json.tmp` 도 같은 구조다.
- `save_deck` 은 스냅샷 복사와 덱 쓰기가 한 단위가 아니다. 겹치면 스냅샷이 두 번 찍히거나 한 번도 안 찍힌다.
- `_next_version_path` 는 스캔과 이동 사이에 다른 내보내기가 같은 번호를 잡는다. 스레드 4개가 동시에 내보내면 넷 다 `v001.pptx` 를 돌려주고 파일은 1개만 남아 결과 3개가 조용히 유실된다(실측).
- `create_project` 는 `exists` 확인 뒤 `mkdir` 라 같은 이름 두 요청이 겹치면 한쪽이 `StorageError` 가 아닌 `FileExistsError` 를 그대로 던져 500 이 된다(실측).
- 저장본을 식별할 값이 없어 오래된 탭의 PUT 이 최신 저장을 덮는다.

**변경 (`backend/slidecaptain/storage/file_store.py`, `backend/slidecaptain/export/exporter.py`)**

- `FileProjectStore` 에 프로젝트별 `threading.RLock` 레지스트리를 둔다(전역 잠금으로 레지스트리 접근을 보호). 공개 컨텍스트 매니저 `locked(name)` 을 두고 `save_deck`, `snapshot_now`, `restore_snapshot`, `write_source` 가 안에서 스냅샷과 쓰기를 한 단위로 수행한다. `create_project` 는 같은 레지스트리 잠금 안에서 `exists` 와 `mkdir` 를 수행하고, 그래도 나는 `FileExistsError` 는 `ProjectExists` 로 바꾼다. 재진입 가능하므로 라우트가 잠근 채 저장소 메서드를 불러도 된다. `ProjectStore` 프로토콜에 `locked` 를 추가한다.
- 임시 파일은 `tempfile.NamedTemporaryFile(dir=<같은 폴더>, prefix=".deck-", suffix=".tmp", delete=False)` 로 고유 이름으로 만들고, **`with` 블록으로 쓰기를 마쳐 닫은 뒤** `os.replace` 한다(Windows 는 자기 핸들이 열려 있어도 교체가 실패한다). 쓰기 도중 예외가 나면 임시 파일을 지우되 삭제 실패는 원래 예외를 가리지 않는다. 자료는 `.tmp-<무작위>-<이름>`, 전역 프리셋은 `.preset-<무작위>.tmp` 다. `list_sources` 의 점 접두 제외 규칙은 그대로다. `create_project` 가 막는 `preset.json.tmp` 이름은 구 임시 파일명과의 충돌 방지용으로 남기고 주석에 그 사유를 적는다.
- 내용 ETag: `deck_etag(name) -> str` 은 `deck.json` 바이트의 SHA-256 16진수(따옴표 없음)다. `load_deck_with_etag(name) -> tuple[Deck, str]` 을 추가한다. `save_deck(name, deck, snapshot=True, expected_etag: str | None = None) -> str` 은 잠금 안에서 현재 ETag 를 읽어 `expected_etag` 가 주어졌는데 다르면 `DeckConflict(StorageError)` 를 던지고, 성공하면 새 ETag 를 돌려준다. `restore_snapshot(name, snapshot_id, expected_etag=None) -> tuple[Deck, str]` 도 같다.
- 내보내기: `export_deck_data` 는 바꾸지 않고, 호출자가 `store.locked(name)` 안에서 부른다(라우트 A2). 잠금 안에서는 스캔과 이동이 겹치지 않는다.

**테스트 (실패부터, `backend/tests/test_file_store.py` 추가 + `backend/tests/test_exporter.py` 추가)**

- 동시 저장: 스레드 8개가 같은 프로젝트에 각각 다른 제목으로 `save_deck` 을 100회씩 부른다. 예외 0건, 마지막 `deck.json` 은 어느 한 호출의 완전한 내용이며 파싱된다, 임시 파일 잔재 0개, 스냅샷 수 == 저장 호출 수. (적대 리뷰 실측: 800회가 0.2초라 CI 부담 없음)
- 동시 생성: 스레드 5개가 같은 이름으로 `create_project` 를 부르면 정확히 1개가 성공하고 나머지는 `ProjectExists` 다. `FileExistsError` 가 새지 않는다.
- 고유 임시 파일: `os.replace` 를 monkeypatch 로 붙잡아 두 저장이 서로 다른 임시 경로를 쓰고 교체 시점에 닫혀 있는지 확인한다. 쓰기 예외 시 임시 파일이 남지 않는다.
- ETag: 같은 내용 두 번 저장은 같은 ETag, 내용이 바뀌면 다른 ETag. `expected_etag` 불일치면 `DeckConflict` 이고 파일과 스냅샷이 바뀌지 않는다. 일치하면 저장되고 새 ETag 를 돌려준다. `restore_snapshot` 도 같다.
- 동시 내보내기: 스레드 4개가 `store.locked(name)` 안에서 `export_deck_data` 를 부르면 파일 4개가 v001~v004 로 전부 생기고 각각 python-pptx 로 열린다.

## 태스크 A2: API 의 조건부 저장과 상태 변경 요청 보호

**재현 (코드 근거와 적대 리뷰 실측)**

- `PUT /deck` 과 `POST /restore` 가 저장본 식별값을 주고받지 않는다.
- 업로드만 `X-Requested-With` 를 요구한다. 본문이 없는 `POST /snapshots`, `POST /export`, `POST /restore` 는 다른 사이트의 페이지가 단순 요청으로 보낼 수 있다(적대 리뷰가 폼형 POST 로 재현). JSON 본문 라우트는 `Content-Type` 이 사전 확인을 유발해 실질 위험이 낮지만 규약이 라우트마다 다르다.
- `POST /export` 가 잠금 없이 `export_deck_data` 를 부른다. 업로드 라우트는 `source_exists` 확인과 `write_source` 가 잠금 밖에서 쪼개져 있어 같은 새 이름의 두 업로드가 둘 다 통과할 수 있다.

**변경 (`backend/slidecaptain/server/app.py`, `backend/tests/conftest.py` 신설)**

- `GET /deck` 응답에 `ETag` 헤더(순수 16진수를 큰따옴표로 감싼 값). `PUT /deck` 은 `If-Match` 헤더(선택)를 읽어 **앞뒤 큰따옴표를 벗긴 뒤** `store.save_deck(..., expected_etag=...)` 에 넘기고, 응답에 새 `ETag` 를 싣는다(`Response` 매개변수로 헤더를 넣는다. `OkResponse` 본문과 OpenAPI 스키마는 그대로다. 적대 리뷰가 이 방식이 동작함을 확인). `DeckConflict` 는 412 와 "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다. 화면을 새로고침한 뒤 다시 편집해 주세요." 로 매핑한다. **`_STATUS_BY_ERROR` 에는 `(StorageError, 400)` 보다 앞에 넣는다**(리스트는 첫 매치를 쓰므로 뒤에 넣으면 400 으로 샌다). `POST /restore` 도 같은 헤더 규약이며 응답 본문은 종전대로 덱, 헤더에 새 ETag.
- 상태 변경 요청 보호를 미들웨어 하나로 공통화한다: 메서드가 GET, HEAD, OPTIONS 가 아니고 경로가 `/api/` 로 시작하면 (a) `X-Requested-With: SlideCaptain` 이 없으면 403 "이 요청은 Slide Captain 화면에서만 보낼 수 있습니다." (b) `Origin` 헤더가 있으면 `urllib.parse.urlparse(origin).hostname` 이 정확히 `127.0.0.1` 또는 `localhost` 여야 하고 아니면 403(접두사 비교는 `127.0.0.1.evil.example` 에 뚫린다). **미들웨어 안에서는 `HTTPException` 을 던지지 않고 `JSONResponse(status_code=403, content={"detail": ...})` 를 직접 돌려준다**(사용자 미들웨어는 예외 처리기 바깥에 있어 던지면 500 이 된다. 적대 리뷰 실측). 업로드 라우트의 개별 헤더 검사는 미들웨어로 흡수하고 그 응답은 400 에서 403 으로 바뀐다(`test_api_upload.py` 의 해당 단언 1건 수정. 프런트는 상태 코드를 409 만 구분하므로 영향 없음). 미들웨어 등록 순서상 새 미들웨어가 `TrustedHostMiddleware` 보다 바깥이 되어 나쁜 Host 와 헤더 없음이 겹치면 403 이 먼저다(테스트에 명시).
- `POST /export` 는 `with store.locked(name):` 안에서 덱 읽기, 검증, 내보내기를 한다. 내보내기 동안 같은 프로젝트의 저장이 잠깐 대기한다(적대 리뷰 실측 20장 덱 약 40ms, 체감 없음). 업로드 라우트는 `with store.locked(name):` 안에서 `source_exists` 확인과 `write_source` 를 함께 수행한다.
- OpenAPI: `If-Match` 를 `Header()` 의존성으로 읽으면 스키마에 파라미터가 늘고, 업로드의 `x-requested-with` 파라미터는 미들웨어로 옮기며 스키마에서 사라진다. 둘 다 `backend/openapi.json` 과 `frontend/src/api/types.ts` 재생성에 반영한다(CI 무변경 확인 대상).
- 테스트 픽스처: `client` 픽스처가 4개 파일에 각각 있고 2개 파일은 자체 `TestClient` 를 만든다(호출 78곳). `backend/tests/conftest.py` 를 신설해 `client` 와 `store` 픽스처를 한 곳으로 모으고 `TestClient(..., headers={"X-Requested-With": "SlideCaptain"})` 로 기본 헤더를 준다. 각 파일의 중복 픽스처는 지운다. 보호 테스트는 헤더 없는 `TestClient` 를 따로 만든다.

**테스트 (실패부터, `backend/tests/test_api_projects.py`, `test_api_snapshots_sources.py`, `test_api_render_export.py`, `test_api_upload.py`, 신규 `test_api_protection.py`)**

- GET 덱은 큰따옴표로 감싼 `ETag` 를 주고, 그 값을 그대로 `If-Match` 로 보낸 PUT 은 200 과 새 ETag, 낡은 값을 보낸 PUT 은 412 와 안내 문구이며 파일은 바뀌지 않는다. `If-Match` 없는 PUT 은 200 이다. 복원도 같다.
- 보호: 헤더 없는 `POST /api/projects/p1/snapshots` 는 403(500 이 아니다), 헤더 있으면 201. `Origin: https://evil.example` 과 `Origin: http://127.0.0.1.evil.example` 은 403, `Origin: http://127.0.0.1:8765` 와 `http://localhost:5173` 은 통과. GET 은 헤더 없이도 200. 정적 파일 경로의 POST 는 종전대로 405.
- 동시 내보내기: 스레드 4개가 `POST /export` 를 부르면 경로 4개가 전부 다르고 파일이 존재한다. 동시 업로드: 같은 새 이름으로 `overwrite=false` 두 요청이 겹치면 하나만 200 이고 다른 하나는 409 다.

## 태스크 A3: 프리셋과 표 레이아웃 안전 검증

**재현 (실측 2026-09-03)**

- `Spacing`, `FontRoles`, `Preset` 의 float 필드는 pydantic 기본값상 `inf`, `nan`, 음수를 받는다. `title_height=1000` 을 넣으면 검증을 통과하지만 레이아웃 엔진의 내용 높이(`_content_geometry` 의 `content_bottom - content_top`)는 -578pt 가 되어 표와 카드와 불릿 영역에 음수 높이가 흘러 들어간다. `safety_ratio` 0 은 모든 줄바꿈을 무한히 쪼갠다.
- `_table_col_widths`: 기본 프리셋(내용 폭 860pt, 최소 폭 60pt)에서 열 이름 `열0`~`열n` 으로 실행하면 열 5개는 정상(최소 172pt), 열 15개는 최소 폭이 -2.7pt(적대 리뷰의 다른 열 이름으로는 2.95pt. 입력에 따라 다르며 어느 쪽이든 최소 폭 위반), 열 20개는 -280pt, 열 40개는 -1480pt 다. 이 숫자는 테스트 기댓값이 아니라 현상 재현이다.

**변경 (`backend/slidecaptain/models/preset.py`, `backend/slidecaptain/layout/templates.py`)**

- 프리셋: `ConfigDict(allow_inf_nan=False)` 를 각 모델에 두고(pydantic 2.13 에서 동작 확인), 크기 필드(`page_width_pt`, `page_height_pt`, 글자 크기, `title_height`, `footnote_height`, `box_height`, `card_heading_height`, `page_number_width`, `page_number_height`, `table_min_col_width`, `border_width_pt`)는 0 초과, 여백과 간격은 0 이상, `safety_ratio` 는 0 초과 1 이하, `line_spacing` 은 0.5 이상으로 검증한다. `Preset` 수준 검증으로 내용 폭(`page_width_pt - margin_left - margin_right`)과 **내용 높이(`_content_geometry` 와 같은 산식: `page_height_pt - margin_top - title_height - title_gap - margin_bottom - footnote_height - footnote_gap`)** 가 각각 100pt 이상임을 요구한다. 산식을 한 곳(예: `preset.py` 의 `content_box()`)에 두고 `_content_geometry` 가 그것을 쓰게 해 둘이 어긋나지 않게 한다. 오류 문구는 한국어다. 덱의 `preset_overrides` 는 `apply_overrides` 가 같은 검증을 타므로 PUT 덱, 실측, 내보내기, 렌더 계획이 전부 422 로 답한다(적대 리뷰가 네 라우트 전부 `_preset_for` 를 거침을 확인).
- 열 폭: 최소 폭을 `min(table_min_col_width, frame_w / n)` 으로 낮추고, 보정 뒤 합이 프레임 폭을 넘으면 초과분을 한 열이 아니라 최소 폭을 넘는 여유에 비례해 여러 열에서 회수한다(최소 폭 <= frame_w / n 이므로 회수량은 항상 여유 이하다. 적대 리뷰가 수식으로 확인). 불변조건: 모든 열 폭 > 0, 합 == 프레임 폭(허용 오차 1e-6). 기존 2열 테스트는 최소 폭이 60 그대로라 변화가 없다.

**테스트 (실패부터, `backend/tests/test_preset.py`, `test_layout_engine.py` 또는 `test_table_render.py`)**

- 프리셋: `nan`, `inf`, 음수 `page_width_pt`, `safety_ratio` 0, 내용 폭이 0 이 되는 여백 조합, **`title_height` 또는 `footnote_height` 를 키워 내용 높이가 0 이하가 되는 조합** 이 각각 `ValidationError` 이고 문구가 한국어다. 기본 프리셋과 기존 픽스처는 그대로 통과한다. API 로 `preset_overrides` 에 `inf` 를 넣은 덱을 PUT 하면 422 다.
- 열 폭: 열 5, 15, 20, 40개의 표에서 모든 열 폭이 양수이고 합이 프레임 폭과 같다. 기존 표 테스트(비례 배분, 최소 폭)는 그대로 통과한다. 렌더 계획을 pptx 로 써서 python-pptx 가 열 폭 음수로 죽지 않는다(회귀).

## 태스크 A4: 이름 안전: NFC 정규화와 대소문자 충돌

**재현 (Mac 실측 2026-09-02, 2026-09-03)**

- Finder 로 만든 한글 이름 폴더는 NFD 라 `_NAME_RE` 의 `[가-힣]` 에 걸리지 않아 목록에는 뜨고 열면 422 다. 자료 이름도 같다. 이 Mac 의 APFS 는 NFD 로 만든 폴더를 NFC 이름으로 열면 같은 폴더로 해석한다(`exists` 참, NFC 로 `mkdir` 하면 `FileExistsError`. 실측).
- macOS 와 Windows 는 대소문자 무시 파일 시스템이다. `PUT /sources/Report.md` 는 `report.md` 가 있어도 `write_source` 가 그대로 덮어쓴다(업로드는 `source_exists` 로 409 를 내지만 PUT 은 안 낸다). 결과 파일 이름의 대소문자는 기존 것이 남아 화면 목록과 어긋난다. 이 보호는 영문과 혼합 이름에만 의미가 있고 한글 이름에는 대소문자가 없다.

**변경 (`backend/slidecaptain/storage/file_store.py`, `backend/slidecaptain/server/app.py`)**

- 이름을 받는 모든 공개 메서드 진입에서 `unicodedata.normalize("NFC", name)` 을 적용한 뒤 검증한다. `list_projects` 와 `list_sources` 가 돌려주는 이름도 NFC 로 정규화한다(폴더 실제 이름이 NFD 여도 API 는 NFC 를 보고, 그 이름으로 다시 열면 macOS 파일 시스템이 같은 폴더로 해석한다).
- `write_source` 는 대소문자만 다른 기존 파일이 있으면 `SourceConflict(StorageError)` 를 던진다(409, "대소문자만 다른 자료가 이미 있습니다: report.md. 같은 이름으로 저장하거나 다른 이름을 써 주세요." `_STATUS_BY_ERROR` 에서 `(StorageError, 400)` 보다 앞). 정확히 같은 이름은 종전대로 덮어쓴다(자료 저장 버튼의 의미). 업로드의 `overwrite=True` 도 정확히 같은 이름에만 적용된다. 판정은 폴더 목록을 `casefold()` 로 비교한다(파일 시스템의 대소문자 구분 여부와 무관하게 같은 규칙. 자료 수백 개여도 밀리초 이하).

**테스트 (실패부터, `backend/tests/test_file_store.py`, `test_api_snapshots_sources.py`)**

- NFD 로 만든 프로젝트 이름과 자료 이름을 검증이 받아들이고, `list_projects` 의 이름이 NFC 다. 실제 NFD 폴더를 열어 덱을 읽는 검사는 macOS 에서만 실행한다(`sys.platform == "darwin"`. 이 저장소 CI 는 Windows 와 macOS 만 돌리고, Windows NTFS 는 NFD 와 NFC 를 다른 이름으로 보므로 그 시나리오가 생기지 않는다).
- `report.md` 가 있을 때 `Report.md` PUT 은 409 이고 원본이 그대로다. 같은 이름 PUT 은 200 이고 덮어쓴다. 업로드 `overwrite=true` 로 `Report.md` 를 올려도 409 다.

## 태스크 A5: 프런트: 식별값 전달과 충돌 안내, 저장 재시도, 창 닫기 경고, 자료 탭 보고 정보 플러시

**재현 (인계 폴더 FC-07, FC-12, FC-15, 이월표 "재시도 수단 없음")**

- FC-15: 편집 뒤 1.2초 안에 창을 닫으면 디바운스 저장이 발사되지 않아 마지막 편집이 사라진다. `beforeunload` 처리가 없다. 자료 탭 보고 정보는 자동 저장 자체가 없어 창을 닫으면 그대로 사라진다.
- 재시도: 저장 실패 뒤 화면에 남는 것은 문구뿐이고, 다시 저장하려면 무언가를 또 편집해야 한다.
- FC-12: 자료 탭 보고 정보는 "보고 정보 저장" 을 누르지 않고 탭을 바꾸면 입력이 사라진다. FC-07: 저장 버튼을 누른 직후 탭을 바꾸면 PUT 응답 전에 다음 화면이 낡은 덱으로 초기화된다.
- A2 뒤에는 `putDeck` 과 `restoreSnapshot` 을 부르는 모든 화면(편집, 구조안 승인 루프, 자료 탭, 복구)이 412 를 받을 수 있다.

**변경 (`frontend/src/api/client.ts`, `state/useDeckEditor.ts`, `state/deckStore.ts`, `screens/EditorScreen.tsx`, `screens/SourcesScreen.tsx`, `screens/StructureScreen.tsx`, `screens/RecoveryScreen.tsx`, `screens/ProjectView.tsx`)**

- `client.ts`: `request()` 가 모든 요청에 `X-Requested-With: SlideCaptain` 을 붙인다. `request()` 에 선택 옵션 `{ etagKey?: string }` 을 추가한다: 주어지면 응답의 `ETag` 헤더를 모듈 내부 `Map<string, string>` 에 그 키로 저장하고, 알고 있는 값이 있으면 `If-Match` 를 붙인다. `getDeck`, `putDeck`, `restoreSnapshot` 만 `etagKey: name` 을 넘기고 나머지 호출은 종전 그대로다(URL 파싱 없음). 테스트용 `resetEtags()` 를 내보내고, `client.test.ts` 는 `beforeEach` 에서 부른다(모듈 상태가 테스트 사이에 새기 때문. `vitest` 의 `clearMocks` 는 `Map` 을 비우지 않는다). 412 는 `ApiError(412, detail)` 그대로다.
- `deckStore`: `reset` 액션(present 교체, past 와 future 비움).
- `useDeckEditor`: `saveError` 와 별개로 `conflict: boolean` 을 돌려준다(412 를 받으면 참). 충돌 상태에서는 자동 저장을 멈추고 `flushSave` 는 false 를 돌려준다(이탈 게이트가 막고 배너를 띄운다). `reloadFromServer()` 는 `api.getDeck` 으로 서버 덱을 읽어 `reset` 하고 `savedDeck` 을 그 덱으로 놓고 `firstSave` 를 켜고 `snapshotNext` 를 끄고 '저장됨' 과 `conflict=false` 로 돌린 뒤, **`onDeckChange(serverDeck)` 을 불러 부모 덱을 갱신한다**(빠지면 다른 탭의 구조안 승인이 낡은 덱으로 최신본을 덮는다). `retrySave()` 는 `flushSave` 의 별칭이다.
- `EditorScreen`: 저장 실패면 "다시 저장" 버튼, 충돌이면 안내 문구와 "서버 내용으로 되돌리기" 버튼. `deck.structure.chapters` 가 바뀌어 현재 `chapterId` 가 목록에 없으면 첫 장으로 되돌리는 효과를 추가한다(되돌린 서버 덱에 그 장이 없을 수 있다). 미저장 여부(`saveState !== "저장됨"`)를 부모에 `onDirtyChange` 로 알린다.
- `SourcesScreen`: 보고 정보 입력이 저장본과 다르면(필드 비교) `onDirtyChange(true)`. 부모에 플러시 함수를 등록한다(`onScreenReady`, 편집기의 `onEditorReady` 와 같은 규약). 저장은 한 줄로 직렬화한다: 진행 중 프라미스를 하나 들고 버튼 저장과 플러시가 그 뒤에 이어 붙어, 버튼 직후 탭 전환이 같은 내용을 낡은 ETag 로 다시 보내지 않게 한다. 저장 중에는 버튼과 입력 필드를 잠근다(플러시 시작 뒤의 타이핑이 유실되지 않게). 플러시는 최신 입력을 ref 에서 읽는다.
- `StructureScreen`, `RecoveryScreen`: 412 를 잡으면 `onConflict()` 를 부른다. 승인 루프에서는 그 장을 실패로 표시하고 루프를 멈춘다(나머지 장은 시도하지 않는다. 낡은 덱 위에 생성 결과를 쌓는 것이 더 위험하다).
- `ProjectView`: `flushEditor` 를 `flushScreen` 으로 일반화하고 자료 탭과 편집 탭이 각각 등록한다. `leaveEditor` 는 `leaveScreen` 으로 바꾸고 동작은 같다. 자식이 `onDirtyChange(true)` 인 동안 `beforeunload` 에서 `preventDefault` 로 브라우저 확인 대화를 띄운다(편집기와 자료 탭 양쪽). 자식이 `onConflict()` 를 부르면 배너에 "다른 창이나 프로그램에서 먼저 저장되었습니다." 와 "서버 내용 다시 읽기" 버튼을 보이고, 누르면 복구 화면 복귀와 같은 방식(`setDeck(null)` 뒤 `getDeck`)으로 자식 화면을 최신 덱으로 다시 마운트한다. 편집 탭의 충돌은 편집기 자체의 되돌리기 버튼이 처리한다.

**테스트 (실패부터, `frontend/src/api/client.test.ts`, `state/useDeckEditor.save.test.tsx`, `screens/EditorScreen.test.tsx`, `screens/SourcesScreen.test.tsx`, `screens/StructureScreen.test.tsx`, `screens/RecoveryScreen.test.tsx`, `screens/ProjectView.flush.test.tsx`)**

- 클라이언트: 모든 요청에 표식 헤더가 붙는다. `getDeck` 뒤 `putDeck` 은 `If-Match` 를 보내고, 응답 ETag 로 다음 `If-Match` 가 바뀐다. ETag 를 모르면 `If-Match` 를 보내지 않는다. 다른 프로젝트 이름은 다른 키다.
- 훅: PUT 이 412 를 돌려주면 `conflict` 가 참이고 이후 편집에 PUT 이 나가지 않으며 `flushSave` 가 false 다. `reloadFromServer` 뒤 덱이 서버 덱이고 '저장됨' 이며 `canUndo` 가 거짓이고 `onDeckChange` 가 서버 덱으로 불렸다. 저장 실패 뒤 `retrySave` 가 PUT 을 다시 보낸다. 기존 무작위 시나리오 30건은 일반 오류만 주입하므로 그대로다.
- 편집 화면: 저장 실패 문구 옆 "다시 저장" 을 누르면 PUT 이 나간다. 되돌린 서버 덱에 현재 장이 없으면 첫 장이 선택된다. 타이밍은 `timings={{ measureMs: 0, saveMs: 큰 값 }}` 처럼 주입해 실제 시간을 기다리지 않는다.
- 자료 화면과 ProjectView: 보고 정보를 고치고 저장 버튼 없이 구조안 탭을 누르면 PUT 이 나가고 착지 뒤에 탭이 바뀐다(FC-07, FC-12). PUT 이 실패하면 자료 탭에 남고 배너가 뜬다. 입력을 바꾸지 않았으면 PUT 이 없다. 저장 버튼 직후 탭 전환은 PUT 이 1회다. 편집 탭이 '저장 대기' 일 때와 자료 탭이 미저장일 때 `beforeunload` 이벤트를 보내면 `defaultPrevented` 가 참이고, 저장된 상태면 거짓이다.
- 구조안과 복구 화면: 승인 루프의 `putDeck` 이 412 면 그 장이 실패로 표시되고 `onConflict` 가 불리며 남은 장은 생성 호출이 없다. 복원의 412 는 `onConflict` 로 이어진다. ProjectView 배너의 "서버 내용 다시 읽기" 가 `getDeck` 을 부르고 자식이 새 덱으로 다시 마운트된다.

## 문서 정정 (마지막 커밋)

- 로드맵 이월표: A1~A5 가 처리한 행(고정 임시 파일, ETag, Origin 보호, 프리셋과 열 폭, NFD, 대소문자 PUT, 재시도 수단, beforeunload, FC-07과 FC-12)을 처리 완료로. 새로 발견한 것은 신규 행.
- 설계서 7.2(저장 사고)에 잠금과 고유 임시 파일과 ETag 조건부 저장, 2.2 또는 신설 절에 상태 변경 요청 보호 규약(헤더와 Origin), 3.3 프리셋 검증 범위.
- `CLAUDE.md` 관례에 "상태 변경 API 는 `X-Requested-With: SlideCaptain` 을 요구한다. 새 라우트와 새 클라이언트 호출은 이 규약을 따른다" 한 줄.
- 진행 상태에 5A A 완료 항목.

## 실행 순서

A1 → A2 → A3 → A4 → A5 → 문서 정정 → 묶음 최종 리뷰 → 수정 반영 → push. 각 태스크 커밋마다 독립 리뷰를 받고 반영한 뒤 다음 태스크로 간다. 백엔드 태스크(A1~A4)가 끝나면 OpenAPI 와 프런트 타입을 재생성해 A5 가 그 타입 위에서 시작한다.

검증 명령은 D1 이 만든 CI 와 같다: 백엔드 전체, OpenAPI 와 타입 무변경, 프런트 테스트와 빌드, 감사기. push 뒤 Windows 와 macOS CI 성공을 확인한다.

## 적대 리뷰 반영 (2026-09-03)

세 관점(저장소 동시성, API 보안과 호환성, 프런트 UX 와 테스트) 리뷰어 3명이 각각 "수정 후 승인" 을 냈다. 발견 30건을 전부 반영했고 기각한 것은 없다. 핵심 변경:

| 관점 | 발견 | 반영 |
|---|---|---|
| API | critical: 미들웨어에서 `HTTPException` 을 던지면 500 (실측) | A2 에 `JSONResponse` 직접 반환 명시 |
| API | major: `_STATUS_BY_ERROR` 순서, ETag 따옴표 규약, Origin 접두사 비교의 스푸핑, 픽스처 6곳, 구조안 승인 루프와 복구 화면의 412 | A2 와 A5 에 각각 명시. `conftest.py` 신설 |
| 저장소 | major: 내용 높이 산식 모호(`title_height=1000` 이 통과하고 실제 높이 -578pt), `create_project` 와 업로드의 확인 후 쓰기 경합 | A3 산식 명시와 테스트 추가, A1 과 A2 에 잠금 범위 확장 |
| 저장소 | minor: `preset_overrides` 키 순서, 재현 숫자 오기, 임시 파일 닫기, Linux CI 문구 | 가정 1 한정, 숫자 실측으로 교체, `with` 로 닫기 명시, 문구 정정 |
| 프런트 | critical: 충돌 복구가 부모 덱을 갱신하지 않으면 다른 탭이 최신본을 덮음 | A5 의 `reloadFromServer` 가 `onDeckChange` 호출 |
| 프런트 | major: `chapterId` 동기화, `request()` 의 ETag 키 방식, 테스트 격리, 자료 탭 저장 직렬화, beforeunload 비대칭, 세 화면의 412 | A5 에 각각 명시. beforeunload 와 충돌 배너를 ProjectView 로 올림 |

## 이 계획이 틀렸을 가능성

- `If-Match` 를 선택으로 두면 헤더를 잊은 새 클라이언트 코드가 조용히 검사를 우회한다. 클라이언트 테스트가 `putDeck` 의 `If-Match` 를 단언하고, 서버 테스트가 "헤더 없음은 통과" 를 명시해 이것이 의도임을 남긴다. 실사용에서 우회 사고가 나면 필수로 바꾼다.
- 모든 상태 변경에 커스텀 헤더를 요구하면 사용자가 curl 로 하던 작업이 403 이 된다. 이 앱의 사용자는 비개발자라 실질 영향이 없고, 문서에 헤더를 적는다.
- 이 저장소 CI 는 Windows 와 macOS 만 돌리므로 NFD 시나리오는 macOS 러너의 darwin 한정 테스트로만 검증된다. Linux 환경은 애초에 검증 대상이 아니다.
- 자료 탭 보고 정보의 자동 플러시가 사용자의 의도와 다를 수 있다(저장하지 않으려고 탭을 옮긴 경우). 편집기가 이미 자동 저장이고, 되돌리기 경로(스냅샷)가 있으므로 손실보다 낫다고 판단한다. 파일럿에서 관찰되면 확인 대화로 바꾼다.
- 프로세스 안 잠금은 실행 스크립트를 두 번 띄운 경우를 막지 못한다. 그 경우는 포트 충돌로 두 번째 서버가 뜨지 않으므로 실제로는 한 프로세스다. 다른 포트로 띄우는 경우는 범위 밖이며 재심 기록대로 후속이다.
- 구조안 승인 루프가 412 에서 멈추면 이미 생성된 앞 장들은 저장되어 있고 뒤 장들은 미생성이다. 사용자가 "서버 내용 다시 읽기" 뒤 다시 승인하면 성공분을 계승하는 기존 규칙(재승인은 실패한 장만 재생성)이 이어받는다.
