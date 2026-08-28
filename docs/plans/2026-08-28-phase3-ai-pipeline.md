# 단계 3: AI 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로바이더 인터페이스와 본인 구독 프로바이더(Agent SDK), 검증 게이트 3종(형식, 분량, 수치 대조)을 만들고, 구조안 생성과 장별 내용 생성 API를 연다. 테스트는 전부 모의 응답으로 한다(설계서 8).

**Architecture:** 교체 지점을 "원시 호출" 하나로 좁힌다: 프로바이더는 프롬프트와 응답 스키마를 받아 구조화 응답을 돌려주기만 하고(`complete(prompt, schema)`), 프롬프트 조립과 게이트 3종은 프로바이더와 무관한 파이프라인 공통부에 둔다. 생성 API는 초안을 반환만 하고 저장하지 않는다: 저장은 기존 `PUT /deck` 단일 경로다. 분량 게이트는 단계 1 엔진이 이미 계산하는 `SlidePlan.warnings`를 재사용한다.

**Tech Stack:** Python 3.13, claude-agent-sdk 0.2.145 (버전 고정), pydantic v2, FastAPI 0.141+, 기존 결정론 코어(레이아웃 엔진, 용량 계약)

## Global Constraints

- AI 파이프라인 테스트는 모의 응답만 쓴다. 실호출은 스모크 스크립트(Task 11) 하나뿐이고 pytest 대상이 아니다 (설계서 8)
- claude-agent-sdk는 `==0.2.145`로 고정한다 (배포 주기가 매우 빨라 유동 버전은 회귀 위험. 로드맵 검증표)
- 프로바이더 호출 구성은 스파이크로 검증된 조합을 쓴다: `tools=[]`, `setting_sources=[]`, `max_turns=1`, `output_format={"type": "json_schema", "schema": ...}` (아래 "착수 전 실증 결과")
- API 오류 안내는 쉬운 말 한국어: 원인과 다음 행동을 담는다 (설계서 7.2)
- 좌표와 글자 크기는 여전히 deck.json에 없다. AI는 슬롯 내용만 만든다 (핵심 원칙)
- 생성 텍스트에 엠대시(U+2014)와 중점(U+00B7)을 쓰지 않는다: 프롬프트로 지시하고 정규화가 기계 치환으로 보증한다
- TDD: 모든 태스크는 실패하는 테스트부터. 커밋은 태스크 단위
- 작업 브랜치: 실행 시작 시 `feature/phase3-ai-pipeline` 브랜치를 만들어 진행한다
- 테스트 실행 명령: `backend` 폴더에서 `.venv/Scripts/python.exe -m pytest tests -q` (Windows. macOS는 `.venv/bin/python`)

## 착수 전 실증 결과 (2026-08-28, 이 계획의 전제)

로드맵의 "미확인 리스크"(Agent SDK가 API 키 없이 구독 로그인을 쓰는지)를 실행으로 해소했다.

- 실험 조건: `ANTHROPIC_API_KEY` 부재 단언, `CLAUDE_CODE_*` 환경 변수 제거(일반 터미널 조건과 일치), `tools=[]`, `setting_sources=[]`, `max_turns=1`, json_schema 구조화 출력
- 결과: 호출 성공(`is_error: False`), `structured_output`에 스키마에 맞는 파싱 완료 JSON이 담김. 저장된 Claude Code 구독 로그인이 자동 사용됨
- 부수 실측: CLI 기본 모델이 opus 계열로 잡혀 사소한 호출에도 사용량 환산 약 0.36달러가 나왔다. 프로바이더 기본 모델을 명시 지정할 근거다 (설계 결정 4)
- 미실증으로 남는 것: 미로그인 환경의 실패 형태(오류 문구). 이 PC는 로그인 상태라 실측 불가. 오류 매핑은 방어적 일반 안내로 하고, 실환경 실증은 이월한다 (Task 11에서 로드맵 이월표에 등재)

httpx2 전환 검토(단계 3 착수 전 의존성 정리 이월)는 해소됐다: 현재 조합(httpx 0.28.1, starlette 1.6.0, fastapi 0.141.1)에서 전체 스위트와 TestClient 경로 모두 `-W always`로 실행해도 StarletteDeprecationWarning이 재현되지 않는다 (2026-08-28 실측). Task 11에서 이월표에 해소 기록만 남긴다.

## 이 계획이 소비하는 단계 1~2 인터페이스 (실측 확인, 2026-08-28)

| 이름 | 시그니처 | 위치 |
|---|---|---|
| `Deck`, `DeckMeta`, `Structure`, `Chapter` | `Chapter(id, topic, conclusion="", template, source_refs=[])` | `slidecaptain/models/deck.py` |
| 슬롯 모델 6종과 `Slots` | discriminated union (`template` 판별자). `TemplateName = Literal["cover", "summary", "bullet_box", "table", "compare2", "divider"]` | `slidecaptain/models/deck.py:13,75` |
| `Preset`, `apply_overrides(base, overrides)` | 전역 프리셋 + 덱별 덮어쓰기 | `slidecaptain/models/preset.py:103,126` |
| `capacity_contract(template, preset) -> dict[str, int]` | 슬롯별 최대 줄수 역산 (cover, divider는 `{}`) | `slidecaptain/metrics/capacity.py:71` |
| `build_slide(chapter, slots, page_no, preset, metrics) -> SlidePlan` | `SlidePlan.warnings: list[CapacityWarning]` 포함 | `slidecaptain/layout/templates.py:318` |
| `CapacityWarning` | `chapter_id, slot, message, needed_pt, available_pt` | `slidecaptain/models/render.py:43` |
| `FontMetrics.load_default()`, `metrics.face(bold)` | 폭 데이터 (번들) | `slidecaptain/metrics/font_metrics.py:118,98` |
| `measure_lines`, `max_lines`, `line_height_pt` | 줄수 실측 | `slidecaptain/metrics/capacity.py:16,20,24` |
| `create_app(store) -> FastAPI` | `_STATUS_BY_ERROR` 목록, `_validated_preset(deck)` | `slidecaptain/server/app.py:68,28,55` |
| `FileProjectStore.list_sources / read_source` | `read_source(name, filename) -> str` (현재 UTF-8 고정) | `slidecaptain/storage/file_store.py:227` |
| CLI `build_parser`, `_run_serve` | serve 서브커맨드 (`--data-dir`, `--port`) | `slidecaptain/__main__.py:16,47` |
| Agent SDK | `query(prompt, options)`, `ClaudeAgentOptions(tools, setting_sources, max_turns, model, output_format)`, `ResultMessage(is_error, structured_output, result, errors)`, 예외 `CLINotFoundError, CLIConnectionError, ProcessError, ClaudeSDKError` | claude-agent-sdk 0.2.145 (설치본 실측) |

## 파일 구조 (이 계획이 만들고 고치는 것)

```
backend/
  pyproject.toml                       # 수정: claude-agent-sdk==0.2.145 의존성 (Task 7)
  openapi.json                         # 재생성 (Task 10)
  scripts/
    smoke_generation.py                # 신규: 실호출 스모크 (수동 실행 전용, Task 11)
  slidecaptain/
    models/
      deck.py                          # 수정: 슬라이드 중복 금지, 표 셀 개행 금지 (Task 1)
    layout/
      engine.py                        # 수정: 구조안 순서 렌더 (Task 2)
      templates.py                     # 수정: 제목, 각주, 카드 소제목 용량 경고 (Task 3)
    metrics/
      capacity.py                      # 수정: compare2 heading 계약, 줄당 자수 환산 (Task 3)
    storage/
      file_store.py                    # 수정: 자료 인코딩 폴백과 422 (Task 4)
    pipeline/
      __init__.py                      # 신규 (빈 파일)
      normalize.py                     # 신규: 텍스트 정규화 (Task 5)
      numbers.py                       # 신규: 수치 추출과 대조 (Task 6)
      provider.py                      # 신규: 프로바이더 인터페이스와 오류 (Task 7)
      subscription.py                  # 신규: 본인 구독 프로바이더 (Task 7)
      prompts.py                       # 신규: 프롬프트 조립과 응답 스키마 (Task 8)
      service.py                       # 신규: 게이트 오케스트레이션 (Task 9)
    server/
      app.py                           # 수정: 생성 엔드포인트, 프로바이더 주입 (Task 10)
    __main__.py                        # 수정: serve --model (Task 10)
  tests/
    test_deck_schema.py                # 수정 (Task 1)
    test_layout_engine.py              # 수정: 순서와 경고 테스트 (Task 2, 3)
    test_file_store.py                 # 수정 (Task 4)
    test_normalize.py                  # 신규 (Task 5)
    test_numbers.py                    # 신규 (Task 6)
    test_subscription_provider.py      # 신규 (Task 7)
    test_prompts.py                    # 신규 (Task 8)
    test_generation_service.py         # 신규 (Task 9)
    test_api_generate.py               # 신규 (Task 10)
frontend/
  src/api/types.ts                     # 재생성 (Task 10)
```

## 이 계획이 소화하는 이월 항목

| 이월 항목 (로드맵) | 처리 태스크 |
|---|---|
| 장 순서의 진본 확정 (택일) | Task 1, 2에서 "구조안 순서" 채택 |
| 표 셀 안 개행 처리 (택일) | Task 1에서 "스키마 금지" 채택 (+ Task 5 정규화 선치환) |
| 각주 슬롯 용량 경고 | Task 3 |
| 장 제목(topic)과 2단 비교 카드 소제목(heading)의 용량 계약과 초과 경고 | Task 3 (경고와 heading 계약), Task 8 (계약의 프롬프트 명시). topic은 구조안 소유라 장별 생성 계약 대상이 아니며 렌더 경고로만 잡는다 |
| 자료 파일 비UTF-8 읽기의 500을 422로 | Task 4 |
| 텍스트 상류 정규화 전제를 생성 파이프라인에 명시 | Task 5 |
| httpx2 전환 검토 (착수 전) | 해소 확인됨. Task 11에서 기록 |

## 이 계획에서 확정하는 설계 결정

1. **덱 순서의 진본은 구조안이다** (이월 택일 확정): 렌더 순서는 `structure.chapters` 배열이 결정하고, `slides` 배열의 순서는 의미가 없다(장별 내용의 집합). 근거: 설계서 3.2가 순서를 구조안의 소유로 정의했고, 편집 화면의 순서 변경 조작(6.1)도 장 목록에서 일어난다. 순서 일치를 검증으로 강제하는 대안은 저장 주체(화면, AI 반영)마다 정렬 유지 부담을 지워 기각. 이 결정이 성립하려면 한 장에 슬라이드가 하나여야 하므로, 같은 장을 가리키는 슬라이드 중복을 모델 검증으로 금지한다.
2. **프로바이더 경계의 정밀화**: 설계서 2.2는 프로바이더를 "프롬프트 조립 → 호출 → 검증"으로 묶어 서술하지만, 프롬프트와 검증이 프로바이더마다 달라지면 품질 일관성(목적 2)이 깨진다. 교체 지점은 `complete(prompt, schema)` 원시 호출 하나로 좁히고, 조립과 게이트는 공통부에 둔다. 배포 단계의 앱 관리형, BYOK는 이 Protocol의 다른 구현으로 추가된다 (2.4 구도 유지).
3. **생성 API는 무저장**: 구조안과 장별 내용 생성은 초안을 반환만 한다. 덱 반영은 화면이 `PUT /deck`으로 수행한다(승인 흐름 포함). 근거: 저장 경로를 하나로 유지해 스냅샷과 검증이 한 곳에서 걸리고, 구조안 승인 전 자동 반영을 구조적으로 차단한다.
4. **기본 모델은 sonnet, serve --model로 변경 가능**: 스파이크 실측에서 CLI 기본(opus 계열)은 사소한 호출에도 사용량이 컸다. 덱 콘텐츠 생성은 sonnet 품질로 충분하다고 판단하되, 판단이 틀릴 경우를 위해 실행 시 `--model`로 바꿀 수 있게 한다. 모델명은 CLI 별칭("sonnet")을 써서 세부 버전 교체에 흔들리지 않게 한다.
5. **게이트 적용 범위**: 형식 게이트(1회 재시도)와 수치 대조 게이트는 호출 2종 모두에, 분량 게이트(1회 축약 재생성)는 장별 내용 생성에만 적용한다. 구조안에는 실측할 슬롯이 없다. 장 제목이 길어지는 문제는 렌더 시점의 제목 경고(Task 3)가 잡는다. **축약 재생성의 발동 조건은 슬롯 재생성으로 고칠 수 있는 경고로 한정한다**: 제목(title) 경고는 구조안의 topic에서 오므로 슬롯 재생성으로는 절대 해소되지 않아, 축약 판정과 축약 프롬프트에서 제외하고 결과 warnings에는 그대로 담는다 (2026-08-28 적대 리뷰 반영: 미필터 시 장 제목이 긴 장마다 헛된 구독 호출 1회가 낭비되고 condensed 플래그가 왜곡된다). 카드 소제목(heading)은 응답 스키마 안에 있어 축약 대상이다.
6. **수치 대조 규칙**: 두 자리 이상 숫자 토큰(콤마 자릿수, 소수점 포함)만 대상으로 한다. 한 자리 정수는 "3가지" 같은 개수 표현이 대부분이라 경고 소음이 된다. 대조는 장의 근거 자료가 아니라 프로젝트 자료 전체를 상대로 한다(근거 매핑이 어긋나도 원자료에 있으면 근거 있는 수치다). 매칭은 콤마를 제거한 정규화 텍스트에서 숫자 경계를 지켜 수행하되, 숫자 뒤 문장 마침표는 경계로 인정한다(234가 1,234의 일부에 걸리지 않게 하면서, "매출은 1200."처럼 마침표로 끝나는 원문이 오탐되지 않게. 2026-08-28 적대 리뷰 반영). **메타성 필드는 수집에서 제외한다**: cover의 date와 audience, divider의 section_no는 자료에 있을 이유가 없는 값이라 대조하면 상시 경고 소음이 된다. 결과는 차단이 아니라 경고 목록이다 (설계서 4.2).
7. **자료 인코딩 폴백**: 읽기는 utf-8-sig(BOM 흡수) → cp949(한국어 Windows 메모장 ANSI) 순서로 시도하고, 둘 다 실패하면 422 한국어 안내를 낸다. 이월 문구("422 안내로 감싸기")보다 한 걸음 나아간 결정이다: 사용자는 비개발자이고 메모장 ANSI 저장이 실제로 흔해, "UTF-8로 다시 저장하라"는 안내만으로는 장벽이 된다. cp949 오독 위험은 낮다(utf-8 실패 후 cp949 성공이면 cp949가 맞을 확률이 지배적). Task 11에서 로드맵 이월표에 이 정정을 날짜와 함께 기록한다.
8. **표 셀 개행은 스키마 금지** (이월 택일 확정): `TableSlots` 검증이 개행을 거부한다. 라이터의 셀 줄바꿈 처리 대안은 행 높이 계산과 균일성 규칙을 복잡하게 만들어 기각. AI 응답은 정규화(Task 5)가 개행을 공백으로 선치환하므로 이 검증에 걸리지 않고, 사용자 직접 입력(단계 4)과 파일 직접 수정만 걸린다.
9. **정규화 규칙 명세**: AI 응답의 모든 문자열 값에 적용한다. CRLF와 CR을 LF로 통일 후 개행을 공백으로(모든 슬롯 텍스트는 단일 문단), 탭을 공백으로, U+2014를 "-"로, U+00B7을 ", "로 치환, 연속 공백을 하나로, 양끝 공백 제거. 근거: 레이아웃의 줄바꿈 실측이 "개행 없는 단일 문단"을 전제하며(이월 항목), 엠대시와 중점은 프로젝트 금지 문자다.
10. **구조안 장 id는 서버가 부여한다**: AI 응답에는 id가 없고, 파이프라인이 순서대로 c1..cN을 부여한다. AI가 만든 id는 중복과 형식 위험만 더한다. 구조안 재생성은 항상 새 초안이다(기존 덱 반영은 화면의 승인 흐름 소관).
11. **장별 생성의 자료 공급 규칙** (2026-08-28 적대 리뷰 반영, 종전 미문서 동작의 명문화): cover와 divider는 자료 블록 없이 구조안 맥락과 보고 정보만으로 생성한다(자료가 필요 없는 템플릿에 자료 전문을 넣으면 호출마다 구독 사용량이 낭비된다). 본문 장에서 source_refs가 비었거나 실존 파일이 없으면 자료 전체로 폴백한다(매핑 누락이 생성 불능으로 이어지지 않게 하는 방어). 수치 대조는 결정 6대로 항상 자료 전체를 상대로 한다.
12. **재호출 프롬프트에 직전 산출물을 동봉한다** (2026-08-28 적대 리뷰 반영): 매 호출이 새 세션(max_turns=1)이라 모델의 컨텍스트에 직전 응답이 존재하지 않는다. 형식 재시도 프롬프트에는 실패한 응답 원문(앞 2,000자)을, 축약 프롬프트에는 직전 초안 JSON을 포함시켜, 1회 한도의 재호출이 실제로 직전 산출물을 딛고 개선하게 한다. 장별 프롬프트에는 보고 정보 블록(덱 제목, 피보고자, 오늘 날짜)을 넣어 cover 생성이 날짜와 보고 대상을 지어내지 않게 한다.
13. **수동 축약 API를 제공한다** (2026-08-28 적대 리뷰 반영, 과소 설계 보완): 설계서 6.2의 "이 장 축약" 버튼과 5.3 사다리 1단계(사용자 직접 수정 초과 시 축약)는 "현재 슬롯 내용을 입력으로 받는 축약" 경로를 요구하는데, 재생성 API만으로는 단계 4가 이 조작을 구현할 수 없다. `POST .../generate/chapter/{id}/condense`(본문에 현재 슬롯)를 추가한다. 축약 결과에도 같은 게이트(형식, 분량 실측, 수치 대조)가 걸리며 추가 축약 재시도는 없다(이 호출 자체가 축약이다).
14. **AI 호출 오류의 원문은 사용자에게 노출하지 않는다** (2026-08-28 적대 리뷰 반영): SDK 예외 원문(영문 stderr, exit code)은 서버 로그로 보내고, 사용자 문구는 원인 확인과 다음 행동을 담은 고정 한국어 안내만 쓴다 (설계서 7.2 "쉬운 말 안내"). 미로그인과 한도 소진의 원인별 세분 안내는 실패 형태 실측 후로 이월한다(착수 전 실증 결과 절).

---

### Task 1: 덱 스키마 강화 (슬라이드 중복 금지, 표 셀 개행 금지)

**Files:**
- Modify: `backend/slidecaptain/models/deck.py`
- Test: `backend/tests/test_deck_schema.py`

**Interfaces:**
- Consumes: `Deck`, `TableSlots` (기존)
- Produces: 같은 `chapter_id`를 가리키는 슬라이드가 2개면 `ValidationError`. 표 칸(`columns`, `rows`)에 개행이 있으면 `ValidationError`. Task 2의 순서 렌더와 Task 9의 검증 경로가 이 불변식에 의존한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_deck_schema.py`에 추가:

```python
def test_duplicate_slide_for_same_chapter_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Deck.model_validate({
            "meta": {"title": "t"},
            "structure": {"chapters": [{"id": "c1", "topic": "주제", "template": "bullet_box"}]},
            "slides": [
                {"chapter_id": "c1", "slots": {"template": "bullet_box", "conclusion": "결론"}},
                {"chapter_id": "c1", "slots": {"template": "bullet_box", "conclusion": "결론2"}},
            ],
        })
    assert "슬라이드" in str(exc_info.value)


def test_table_cell_newline_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Deck.model_validate({
            "meta": {"title": "t"},
            "structure": {"chapters": [{"id": "c1", "topic": "주제", "template": "table"}]},
            "slides": [{"chapter_id": "c1", "slots": {
                "template": "table", "columns": ["항목"], "rows": [["첫 줄\n둘째 줄"]],
            }}],
        })
    assert "줄바꿈" in str(exc_info.value)
```

파일 상단 import에 `pytest`, `ValidationError`(pydantic), `Deck`이 이미 있는지 확인하고 없으면 추가한다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deck_schema.py -q`
Expected: 신규 2개 FAIL (검증이 없어 통과해 버리므로 raises가 안 잡힘)

- [ ] **Step 3: 구현**

`backend/slidecaptain/models/deck.py`의 `TableSlots`에 validator 추가 (`rows_match_columns` 아래):

```python
    @model_validator(mode="after")
    def _cells_single_line(self) -> "TableSlots":
        # 표 셀 줄바꿈은 행 높이 계산과 균일성 규칙을 깨므로 데이터에서 금지한다 (단계 3 결정 8)
        for text in self.columns + [cell for row in self.rows for cell in row]:
            if "\n" in text or "\r" in text:
                raise ValueError("표 칸에는 줄바꿈을 넣을 수 없습니다. 내용을 한 줄로 줄이거나 행을 나눠 주세요")
        return self
```

`Deck._chapters_and_slides_consistent`의 `for slide in self.slides:` 반복 앞에 추가:

```python
        seen_slide_chapters: set[str] = set()
        for slide in self.slides:
            if slide.chapter_id in seen_slide_chapters:
                raise ValueError(
                    f"한 장에 슬라이드가 두 개 있습니다: {slide.chapter_id}. "
                    "장 하나에는 슬라이드 하나만 둘 수 있습니다"
                )
            seen_slide_chapters.add(slide.chapter_id)
```

(기존 반복문과 합쳐도 된다: 기존 `for slide in self.slides:` 본문 맨 앞에 중복 검사를 넣는 형태가 더 깔끔하다.)

- [ ] **Step 4: 전체 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS (기존 160개 + 신규 2개)

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/models/deck.py backend/tests/test_deck_schema.py
git commit -m "feat: 슬라이드 중복 금지와 표 셀 개행 금지 (덱 순서 진본 확정의 전제, 단계 2 이월)"
```

---

### Task 2: 렌더 순서의 진본을 구조안으로

**Files:**
- Modify: `backend/slidecaptain/layout/engine.py`
- Test: `backend/tests/test_layout_engine.py`

**Interfaces:**
- Consumes: `Deck`, `build_slide` (기존)
- Produces: `build_render_plan`은 `structure.chapters` 순서로 렌더하고, 내용이 아직 없는 장은 건너뛴다. 쪽번호는 렌더된 슬라이드 기준 1부터. 시그니처 불변: `build_render_plan(deck, preset, metrics) -> RenderPlan`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_layout_engine.py`에 추가 (파일 상단의 기존 import와 픽스처를 확인해 재사용하고, 없으면 아래 형태로 추가한다):

```python
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import BulletBoxSlots, Chapter, Deck, DeckMeta, Slide, Structure
from slidecaptain.models.preset import Preset

METRICS = FontMetrics.load_default()


def _two_chapter_deck() -> Deck:
    return Deck(
        meta=DeckMeta(title="순서 테스트"),
        structure=Structure(chapters=[
            Chapter(id="c2", topic="둘째 주제", template="bullet_box"),
            Chapter(id="c1", topic="첫째 주제", template="bullet_box"),
        ]),
        slides=[
            Slide(chapter_id="c1", slots=BulletBoxSlots(conclusion="결론1")),
            Slide(chapter_id="c2", slots=BulletBoxSlots(conclusion="결론2")),
        ],
    )


def test_render_order_follows_structure_not_slides_array():
    plan = build_render_plan(_two_chapter_deck(), Preset(), METRICS)
    assert [s.chapter_id for s in plan.slides] == ["c2", "c1"]


def test_chapter_without_slide_is_skipped_and_pages_renumber():
    # c1 슬라이드만 남긴다: 구조안에서 c1은 두 번째 장이므로, 장 위치를 그대로 쪽번호로 쓰는
    # 버그 구현은 2를 내고 올바른 구현(렌더 순번)은 1을 낸다 (2026-08-28 적대 리뷰 반영)
    deck = _two_chapter_deck()
    deck = deck.model_copy(update={"slides": [deck.slides[0]]})
    plan = build_render_plan(deck, Preset(), METRICS)
    assert [s.chapter_id for s in plan.slides] == ["c1"]
    page_para = next(
        p for f in plan.slides[0].frames if f.name.endswith(":page_number") for p in f.paras
    )
    assert page_para.text == "1"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_layout_engine.py -q`
Expected: `test_render_order_follows_structure_not_slides_array` FAIL (현재는 slides 배열 순서로 렌더)

- [ ] **Step 3: 구현**

`backend/slidecaptain/layout/engine.py`의 `build_render_plan` 본문을 교체:

```python
def build_render_plan(deck: Deck, preset: Preset, metrics) -> RenderPlan:
    chapters = {ch.id: ch for ch in deck.structure.chapters}
    for slide in deck.slides:
        if slide.chapter_id not in chapters:
            raise ValueError(f"구조안에 없는 장을 그릴 수 없습니다: {slide.chapter_id}")
    slides_by_chapter = {slide.chapter_id: slide for slide in deck.slides}

    # 렌더 순서의 진본은 구조안이다 (단계 3 결정 1). slides 배열 순서는 의미가 없다.
    slides = []
    page_no = 0
    for chapter in deck.structure.chapters:
        slide = slides_by_chapter.get(chapter.id)
        if slide is None:
            continue  # 내용이 아직 생성되지 않은 장
        page_no += 1
        slides.append(build_slide(chapter, slide.slots, page_no, preset, metrics))
    return RenderPlan(
        page_width_pt=preset.page_width_pt,
        page_height_pt=preset.page_height_pt,
        style=_style_from_preset(preset),
        slides=slides,
    )
```

- [ ] **Step 4: 전체 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS. 기존 테스트 중 slides 배열 순서에 의존하는 것이 있으면(골든, 회귀 포함) 구조안 순서와 일치하도록 테스트 데이터를 정렬해 고친다: 구조안과 슬라이드가 같은 순서로 작성된 기존 테스트는 영향이 없어야 정상이다.

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/layout/engine.py backend/tests/test_layout_engine.py
git commit -m "feat: 렌더 순서의 진본을 구조안으로 (단계 2 이월 택일 확정)"
```

---

### Task 3: 고정 높이 슬롯의 용량 경고 (제목, 각주, 카드 소제목)와 heading 계약

**Files:**
- Modify: `backend/slidecaptain/layout/templates.py`
- Modify: `backend/slidecaptain/metrics/capacity.py`
- Test: `backend/tests/test_layout_engine.py`, `backend/tests/test_capacity.py`

**Interfaces:**
- Consumes: `measure_lines`, `max_lines`, `line_height_pt`, `_content_geometry`, `_measure_warning` (기존)
- Produces:
  - 본문 4종 템플릿(summary, bullet_box, table, compare2)에서 `chapter.topic`이 제목 영역(1줄)을 넘으면 slot `"title"` 경고. bullet_box와 table의 `footnote`가 각주 영역(1줄)을 넘으면 slot `"footnote"` 경고. compare2 카드 `heading`이 소제목 영역(1줄)을 넘으면 slot `"left_card_heading"` / `"right_card_heading"` 경고. Task 9의 분량 게이트가 이 경고들을 그대로 소비한다.
  - `capacity_contract("compare2", preset)`에 `card_heading_max_lines` 추가 (이월 항목의 "용량 계약" 절반. Task 8의 프롬프트가 명시한다)
  - `hangul_chars_per_line(preset, face) -> int`: 본문 폭의 한 줄에 한글이 약 몇 자 들어가는지 (Task 8 프롬프트의 환산 안내용)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_layout_engine.py`에 추가 (Task 2에서 만든 import 재사용):

```python
from slidecaptain.models.deck import Card, CompareSlots, SummarySlots, TableSlots


def _plan_for(chapter: Chapter, slots) -> "SlidePlan":
    deck = Deck(
        meta=DeckMeta(title="경고 테스트"),
        structure=Structure(chapters=[chapter]),
        slides=[Slide(chapter_id=chapter.id, slots=slots)],
    )
    return build_render_plan(deck, Preset(), METRICS).slides[0]


def _warned_slots(plan_slide) -> set[str]:
    return {w.slot for w in plan_slide.warnings}


# 제목 경고는 4종 빌더 전부에 배선되므로 전부 검증한다 (2026-08-28 적대 리뷰 반영)
@pytest.mark.parametrize(
    "template,slots",
    [
        ("bullet_box", BulletBoxSlots(conclusion="결론")),
        ("summary", SummarySlots(conclusion="결론")),
        ("table", TableSlots(columns=["a"], rows=[["b"]])),
        ("compare2", CompareSlots(left=Card(heading="좌"), right=Card(heading="우"), conclusion="결론")),
    ],
)
def test_long_topic_warns_title_overflow(template, slots):
    long_topic = "제목 영역 한 줄을 확실히 넘기기 위한 매우 길고 긴 장 제목 문장이며 계속 이어진다" * 2
    chapter = Chapter(id="c1", topic=long_topic, template=template)
    slide = _plan_for(chapter, slots)
    assert "title" in _warned_slots(slide)


def test_short_topic_no_title_warning():
    chapter = Chapter(id="c1", topic="짧은 제목", template="bullet_box")
    slide = _plan_for(chapter, BulletBoxSlots(conclusion="결론"))
    assert "title" not in _warned_slots(slide)


def test_long_footnote_warns_on_bullet_box_and_table():
    long_footnote = "출처와 기준 시점을 장황하게 설명하는 각주 문장 " * 12
    chapter_b = Chapter(id="c1", topic="주제", template="bullet_box")
    slide_b = _plan_for(chapter_b, BulletBoxSlots(conclusion="결론", footnote=long_footnote))
    assert "footnote" in _warned_slots(slide_b)

    chapter_t = Chapter(id="c2", topic="주제", template="table")
    slide_t = _plan_for(chapter_t, TableSlots(columns=["a"], rows=[["b"]], footnote=long_footnote))
    assert "footnote" in _warned_slots(slide_t)
```

`backend/tests/test_capacity.py`에 추가 (파일 상단의 기존 import에 `Preset`, `FontMetrics`가 있는지 확인해 재사용):

```python
def test_compare2_contract_includes_heading_limit():
    contract = capacity_contract("compare2", Preset())
    assert contract["card_heading_max_lines"] == 1


def test_hangul_chars_per_line_matches_bundle_metrics():
    # 본문 폭 860pt x safety 0.97 / (0.92em x 12pt) = 75.5... -> 75자 (번들 폭 실측 기준)
    from slidecaptain.metrics.capacity import hangul_chars_per_line

    metrics = FontMetrics.load_default()
    assert hangul_chars_per_line(Preset(), metrics.face(False)) == 75


def test_long_card_heading_warns_on_compare2():
    # 실측 근거(2026-08-28): 카드 소제목 예산은 388.0pt(카드 내부 폭 400pt x safety 0.97)이고
    # 아래 문자열은 볼드 12pt로 약 728pt(1회 364pt의 2배)라 확실히 2줄이 된다.
    # 1회만 쓰면 364pt로 1줄에 들어가 경고가 나지 않는다 (적대 리뷰가 실측으로 확인한 함정)
    long_heading = "카드 소제목 영역 한 줄을 넘기기 위한 매우 긴 소제목 문구가 계속 이어진다 " * 2
    chapter = Chapter(id="c1", topic="주제", template="compare2")
    slide = _plan_for(chapter, CompareSlots(
        left=Card(heading=long_heading), right=Card(heading="짧음"), conclusion="결론",
    ))
    assert "left_card_heading" in _warned_slots(slide)
    assert "right_card_heading" not in _warned_slots(slide)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_layout_engine.py tests/test_capacity.py -q`
Expected: 신규 경고 테스트와 계약 테스트 FAIL (경고와 `card_heading_max_lines`, `hangul_chars_per_line`이 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/metrics/capacity.py`의 `capacity_contract` 안 `"compare2"` 계약 첫 항목으로 추가:

```python
        "compare2": {
            "card_heading_max_lines": max_lines(s.card_heading_height, r.body_pt, s.line_spacing),
            "card_bullets_max_lines": max_lines(
```

같은 파일 끝에 함수 추가:

```python
def hangul_chars_per_line(preset: Preset, face) -> int:
    """본문 폭의 한 줄에 한글이 약 몇 자 들어가는지 어림한다 (AI 프롬프트의 분량 환산 안내용)."""
    g = _content_geometry(preset)
    char_width = face.width_pt("가", preset.font_roles.body_pt)
    return math.floor(g["content_width"] * preset.spacing.safety_ratio / char_width)
```

`backend/slidecaptain/layout/templates.py`의 `_conclusion_warning` 아래에 공통 헬퍼를 추가:

```python
def _fixed_height_warning(
    chapter: Chapter, slot: str, text: str,
    width_pt: float, height_pt: float, font_pt: float, bold: bool,
    preset: Preset, metrics,
) -> CapacityWarning | None:
    """높이가 고정된 한 줄성 영역(제목, 각주, 카드 소제목)의 초과를 실측으로 잡는다."""
    if not text:
        return None
    s = preset.spacing
    capacity = max_lines(height_pt, font_pt, s.line_spacing)
    lines = measure_lines(text, width_pt, font_pt, metrics.face(bold), s)
    if lines <= capacity:
        return None
    lh = line_height_pt(font_pt, s.line_spacing)
    return _measure_warning(chapter, slot, lines * lh, height_pt)


def _title_warning(chapter: Chapter, preset: Preset, metrics) -> CapacityWarning | None:
    s, r = preset.spacing, preset.font_roles
    g = _content_geometry(preset)
    return _fixed_height_warning(
        chapter, "title", chapter.topic, g["content_width"], s.title_height, r.title_pt, True,
        preset, metrics,
    )


def _footnote_warning(chapter: Chapter, text: str, preset: Preset, metrics) -> CapacityWarning | None:
    s, r = preset.spacing, preset.font_roles
    g = _content_geometry(preset)
    return _fixed_height_warning(
        chapter, "footnote", text, g["content_width"], s.footnote_height, r.footnote_pt, False,
        preset, metrics,
    )
```

각 빌더에 경고를 연결한다.

`_build_bullet_box`의 `warnings = []` 직후:

```python
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)
```

같은 함수의 `if slots.footnote:` 분기 근처(warnings 수집부)에:

```python
    if (fw := _footnote_warning(chapter, slots.footnote, preset, metrics)) is not None:
        warnings.append(fw)
```

`_build_summary`, `_build_table`, `_build_compare2`의 `warnings = []` 직후에도 동일하게 `_title_warning` 연결. `_build_table`에는 `_footnote_warning`도 연결(bullet_box와 동일 형태).

`_build_compare2`의 `card_frame` 안, 불릿 실측 앞에 추가:

```python
        if (hw := _fixed_height_warning(
            chapter, f"{name}_heading", card.heading,
            card_w - 2 * s.box_padding, s.card_heading_height, r.body_pt, True,
            preset, metrics,
        )) is not None:
            warnings.append(hw)
```

- [ ] **Step 4: 전체 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS. 기존 골든과 회귀 테스트의 덱 데이터가 새 경고를 유발하면(제목이나 각주가 길면) 경고 유무 단언이 아닌 한 산출 PPTX는 불변이므로 통과해야 정상이다.

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/layout/templates.py backend/slidecaptain/metrics/capacity.py backend/tests/test_layout_engine.py backend/tests/test_capacity.py
git commit -m "feat: 제목, 각주, 카드 소제목의 용량 경고와 heading 계약 (단계 2 이월 2건)"
```

---

### Task 4: 자료 읽기 인코딩 폴백과 422

**Files:**
- Modify: `backend/slidecaptain/storage/file_store.py`
- Modify: `backend/slidecaptain/server/app.py` (오류 매핑 1줄)
- Test: `backend/tests/test_file_store.py`, `backend/tests/test_api_snapshots_sources.py`

**Interfaces:**
- Consumes: `read_source` (기존)
- Produces: `InvalidSourceEncoding(StorageError)` 예외. `read_source`는 utf-8-sig → cp949 순서로 디코드를 시도한다. API의 자료 읽기와 Task 10의 생성 엔드포인트가 이 동작에 의존한다 (바이너리 자료로 인한 500 제거).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_file_store.py`에 추가:

```python
from slidecaptain.storage.file_store import InvalidSourceEncoding


def test_read_source_cp949_fallback(store):
    store.create_project("p1")
    path = store.root / "p1" / "sources" / "옛문서.txt"
    path.write_bytes("한글 자료입니다. 매출 1,234억".encode("cp949"))
    assert "1,234억" in store.read_source("p1", "옛문서.txt")


def test_read_source_utf8_bom_absorbed(store):
    store.create_project("p1")
    path = store.root / "p1" / "sources" / "봄문서.txt"
    path.write_bytes("\ufeff본문 시작".encode("utf-8"))
    assert store.read_source("p1", "봄문서.txt") == "본문 시작"


def test_read_source_binary_rejected_with_guidance(store):
    store.create_project("p1")
    path = store.root / "p1" / "sources" / "그림.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe\xfd")
    with pytest.raises(InvalidSourceEncoding) as exc_info:
        store.read_source("p1", "그림.png")
    assert "텍스트" in str(exc_info.value)
```

`backend/tests/test_api_snapshots_sources.py`에 추가 (이 파일의 기존 client, store 픽스처를 재사용한다):

```python
def test_read_binary_source_returns_422(client, store):
    client.post("/api/projects", json={"name": "p1"})
    (store.root / "p1" / "sources" / "그림.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
    r = client.get("/api/projects/p1/sources/그림.png")
    assert r.status_code == 422
    assert "텍스트" in r.json()["detail"]
```

(이 API 테스트 파일의 픽스처가 store를 노출하지 않으면, `test_file_store.py`처럼 store를 만들고 `TestClient(create_app(store))`를 감싸는 형태로 픽스처를 보강한다.)

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_store.py tests/test_api_snapshots_sources.py -q`
Expected: cp949 폴백과 바이너리 테스트 FAIL (현재는 UnicodeDecodeError가 그대로 터짐), BOM 테스트 FAIL (BOM이 텍스트에 남음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/storage/file_store.py`에 예외 추가 (`SourceNotFound` 아래):

```python
class InvalidSourceEncoding(StorageError):
    pass
```

`read_source`의 마지막 `return path.read_text(encoding="utf-8")`을 교체:

```python
        # utf-8-sig가 BOM 유무 양쪽을 흡수한다. cp949는 한국어 Windows 메모장의
        # ANSI 저장을 위한 폴백이다 (단계 3 결정 7)
        for encoding in ("utf-8-sig", "cp949"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise InvalidSourceEncoding(
            f"자료 파일 {filename}을 텍스트로 읽지 못했습니다. "
            "PDF나 이미지 같은 텍스트 아닌 파일은 자료로 쓸 수 없습니다. "
            "텍스트 파일이라면 UTF-8 인코딩으로 다시 저장해 주세요."
        )
```

`backend/slidecaptain/server/app.py`의 import에 `InvalidSourceEncoding`을 추가하고, `_STATUS_BY_ERROR` 목록에서 `(StorageError, 400)` 앞에 매핑을 넣는다:

```python
_STATUS_BY_ERROR = [
    (InvalidName, 422),
    (InvalidSourceEncoding, 422),
    (ProjectNotFound, 404),
    (SnapshotNotFound, 404),
    (SourceNotFound, 404),
    (ProjectExists, 409),
    (StorageError, 400),
]
```

- [ ] **Step 4: 전체 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/storage/file_store.py backend/slidecaptain/server/app.py backend/tests/test_file_store.py backend/tests/test_api_snapshots_sources.py
git commit -m "feat: 자료 읽기 인코딩 폴백(utf-8-sig, cp949)과 422 안내 (단계 2 이월)"
```

---

### Task 5: 텍스트 정규화 모듈

**Files:**
- Create: `backend/slidecaptain/pipeline/__init__.py` (빈 파일)
- Create: `backend/slidecaptain/pipeline/normalize.py`
- Test: `backend/tests/test_normalize.py`

**Interfaces:**
- Consumes: 없음 (표준 라이브러리만)
- Produces: `normalize_text(text: str) -> str`, `normalize_payload(data: Any) -> Any` (dict/list 재귀, 문자열 값만 정규화, dict 키는 건드리지 않음), `collect_strings(data: Any) -> list[str]`. Task 9의 형식 게이트(파싱 전 정규화)와 수치 게이트(텍스트 수집)가 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_normalize.py` 신규:

```python
from slidecaptain.pipeline.normalize import collect_strings, normalize_payload, normalize_text


def test_newlines_become_single_spaces():
    assert normalize_text("첫 줄\r\n둘째 줄\r셋째\n넷째") == "첫 줄 둘째 줄 셋째 넷째"


def test_consecutive_spaces_and_tabs_collapse():
    assert normalize_text("앞  뒤\t끝   ") == "앞 뒤 끝"


def test_banned_characters_replaced():
    assert normalize_text("전략—핵심·요약") == "전략-핵심, 요약"


def test_payload_recurses_values_not_keys():
    payload = {"conclusion": "결론  문장\n계속", "bullets": [{"text": " 항목 ", "level": 1}]}
    result = normalize_payload(payload)
    assert result == {"conclusion": "결론 문장 계속", "bullets": [{"text": "항목", "level": 1}]}


def test_collect_strings_walks_nested():
    payload = {"a": "하나", "b": [{"c": "둘"}, "셋"], "d": 4}
    assert collect_strings(payload) == ["하나", "둘", "셋"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_normalize.py -q`
Expected: FAIL (`slidecaptain.pipeline` 모듈 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/pipeline/__init__.py`: 빈 파일.

`backend/slidecaptain/pipeline/normalize.py`:

```python
"""AI 생성 텍스트의 상류 정규화 (설계 결정 9).

레이아웃의 줄바꿈 실측(line_breaker)은 "개행 없는 단일 문단, 연속 공백 없음"을
전제한다. AI 응답이 이 전제를 벗어나도 여기서 흡수한다. 프로젝트 금지 문자
(엠대시 U+2014, 중점 U+00B7)도 이 단계에서 기계 치환으로 보증한다.
"""

import re
from typing import Any

_MULTI_SPACE = re.compile(r" {2,}")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    text = text.replace("\t", " ")
    text = text.replace("—", "-").replace("·", ", ")
    return _MULTI_SPACE.sub(" ", text).strip()


def normalize_payload(data: Any) -> Any:
    """AI 응답(JSON 호환 구조) 안의 모든 문자열 값을 정규화한다. dict 키는 스키마 필드라 건드리지 않는다."""
    if isinstance(data, str):
        return normalize_text(data)
    if isinstance(data, list):
        return [normalize_payload(item) for item in data]
    if isinstance(data, dict):
        return {key: normalize_payload(value) for key, value in data.items()}
    return data


def collect_strings(data: Any) -> list[str]:
    """구조 안의 모든 문자열 값을 순서대로 모은다 (수치 대조 게이트의 입력)."""
    if isinstance(data, str):
        return [data]
    if isinstance(data, list):
        return [s for item in data for s in collect_strings(item)]
    if isinstance(data, dict):
        return [s for value in data.values() for s in collect_strings(value)]
    return []
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/slidecaptain/pipeline backend/tests/test_normalize.py
git commit -m "feat: 생성 텍스트 정규화 (단일 문단 전제 흡수, 금지 문자 치환. 단계 2 이월)"
```

---

### Task 6: 수치 추출과 대조 모듈

**Files:**
- Create: `backend/slidecaptain/pipeline/numbers.py`
- Test: `backend/tests/test_numbers.py`

**Interfaces:**
- Consumes: 없음 (표준 라이브러리만)
- Produces: `extract_numbers(text: str) -> list[str]` (정규화 형태, 두 자리 이상만, 등장 순서 유지, 중복 제거), `find_unverified_numbers(texts: list[str], sources: list[str]) -> list[str]`. Task 9의 수치 게이트가 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_numbers.py` 신규:

```python
from slidecaptain.pipeline.numbers import extract_numbers, find_unverified_numbers


def test_extract_normalizes_commas_and_decimals():
    assert extract_numbers("매출 1,234억, 성장률 45.2%") == ["1234", "45.2"]


def test_extract_skips_single_digit_counts():
    assert extract_numbers("3가지 대안 중 2개 채택, 총 12건") == ["12"]


def test_extract_dedupes_keeping_order():
    assert extract_numbers("2026년 상반기, 2026년 하반기, 300억") == ["2026", "300"]


def test_verified_numbers_pass():
    sources = ["2026년 매출은 1,234억 원이며 성장률은 45.2%였다"]
    texts = ["매출 1234억 (45.2%)", "기준 연도 2026"]
    assert find_unverified_numbers(texts, sources) == []


def test_unverified_numbers_reported():
    sources = ["시장 규모는 500억 원"]
    texts = ["시장 규모 500억, 점유율 37%"]
    assert find_unverified_numbers(texts, sources) == ["37"]


def test_partial_digit_match_rejected():
    # 234는 1,234의 일부일 뿐, 자료에 있는 숫자가 아니다
    sources = ["매출 1,234억"]
    assert find_unverified_numbers(["순이익 234억"], sources) == ["234"]


def test_decimal_boundary_respected():
    # 45는 45.2의 일부일 뿐이다
    sources = ["성장률 45.2%"]
    assert find_unverified_numbers(["45명 대상"], sources) == ["45"]


def test_sentence_ending_period_is_a_boundary():
    # 문장 마침표와 한국식 날짜 표기는 소수점이 아니다 (2026-08-28 적대 리뷰 반영)
    sources = ["연간 매출은 1200. 기준일은 2026. 8. 28. 이다"]
    assert find_unverified_numbers(["매출 1200 (2026년 기준)"], sources) == []
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_numbers.py -q`
Expected: FAIL (`numbers` 모듈 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/pipeline/numbers.py`:

```python
"""수치 대조 게이트 (설계서 4.2 게이트 3).

생성 문장에서 숫자를 추출해 입력 자료 원문에 존재하는지 대조한다.
"근거 없는 수치 금지"를 프롬프트 당부가 아니라 기계 검증으로 강제하며,
결과는 차단이 아니라 화면 경고 표지로 쓰인다 (단계 3 결정 6).
"""

import re

# 콤마 자릿수 구분과 소수점을 포함한 숫자 토큰
_NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _normalize(token: str) -> str:
    return token.replace(",", "")


def extract_numbers(text: str) -> list[str]:
    """대조 대상 숫자를 정규화 형태(콤마 제거)로 추출한다. 등장 순서 유지, 중복 제거.

    한 자리 정수는 제외한다: "3가지" 같은 개수 표현이 대부분이라 경고 소음이 되고,
    놓쳤을 때의 위험도 작다.
    """
    seen: list[str] = []
    for m in _NUMBER_RE.finditer(text):
        value = _normalize(m.group())
        if len(value) < 2:
            continue
        if value not in seen:
            seen.append(value)
    return seen


def find_unverified_numbers(texts: list[str], sources: list[str]) -> list[str]:
    """자료 원문 어디에도 없는 숫자 목록.

    대조는 콤마를 제거한 정규화 텍스트에서 숫자 경계를 지켜 수행한다
    (234가 1,234의 일부에 걸려 통과하는 것을 막는다). 숫자 뒤 마침표는
    바로 숫자가 이어질 때만 소수점으로 보고 경계를 막는다: 문장 끝 마침표와
    한국식 날짜 표기("2026. 8. 28.")가 오탐되지 않게 한다.
    """
    haystack = "\n".join(_normalize(s) for s in sources)
    unverified: list[str] = []
    for text in texts:
        for number in extract_numbers(text):
            pattern = re.compile(r"(?<![\d.])" + re.escape(number) + r"(?!\.?\d)")
            if pattern.search(haystack) is None and number not in unverified:
                unverified.append(number)
    return unverified
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/slidecaptain/pipeline/numbers.py backend/tests/test_numbers.py
git commit -m "feat: 수치 추출과 원자료 대조 (검증 게이트 3의 계산부)"
```

---

### Task 7: 프로바이더 인터페이스와 본인 구독 프로바이더

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/slidecaptain/pipeline/provider.py`
- Create: `backend/slidecaptain/pipeline/subscription.py`
- Test: `backend/tests/test_subscription_provider.py`

**Interfaces:**
- Consumes: claude-agent-sdk 0.2.145 (`query`, `ClaudeAgentOptions`, `ResultMessage`, 예외들)
- Produces:
  - `ProviderError(Exception)` 기반, `ProviderNotAvailable`, `ProviderCallFailed` (전부 사용자에게 보여줄 한국어 메시지 보유)
  - `ProviderResponse(structured: Any | None, raw_text: str)` (dataclass)
  - `AIProvider` Protocol: `async def complete(self, prompt: str, schema: dict) -> ProviderResponse`
  - `SubscriptionProvider(model: str | None = None)` (기본 모델 `"sonnet"`), `DEFAULT_MODEL`
  - Task 9의 서비스와 Task 10의 앱 주입이 이 타입들을 쓴다

- [ ] **Step 1: 의존성 추가**

`backend/pyproject.toml`의 dependencies에 추가:

```toml
dependencies = [
    "pydantic>=2.9",
    "python-pptx==1.0.2",
    "fonttools>=4.63",
    "fastapi>=0.141",
    "uvicorn>=0.30",
    "claude-agent-sdk==0.2.145",
]
```

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`
Expected: claude-agent-sdk 0.2.145 설치 확인 (이미 설치돼 있으면 그대로 통과)

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_subscription_provider.py` 신규 (실호출 없음: `query`를 monkeypatch로 대체한다):

```python
import asyncio

import pytest

from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderNotAvailable, ProviderResponse
import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.subscription import DEFAULT_MODEL, SubscriptionProvider


def _fake_query(result_message=None, error: Exception | None = None, captured: dict | None = None):
    async def fake(prompt, options):
        if captured is not None:
            captured["prompt"] = prompt
            captured["options"] = options
        if error is not None:
            raise error
        # 실제 SDK 스트림은 ResultMessage 앞에 System, Assistant 등 다른 메시지를 먼저 낸다.
        # 더미를 선행시켜 isinstance 필터링을 테스트로 고정한다 (2026-08-28 적대 리뷰 반영)
        yield object()
        yield result_message

    return fake


def _result(is_error=False, structured=None, text="원문", errors=None):
    from claude_agent_sdk import ResultMessage

    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error,
        num_turns=1, session_id="s", result=text, structured_output=structured, errors=errors,
    )


def test_complete_returns_structured_and_raw(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        sub, "query", _fake_query(_result(structured={"answer": 2}), captured=captured)
    )
    provider = SubscriptionProvider()
    resp = asyncio.run(provider.complete("질문", {"type": "object"}))
    assert resp == ProviderResponse(structured={"answer": 2}, raw_text="원문")
    options = captured["options"]
    assert options.model == DEFAULT_MODEL == "sonnet"
    assert options.tools == []
    assert options.setting_sources == []
    assert options.max_turns == 1
    assert options.output_format == {"type": "json_schema", "schema": {"type": "object"}}


def test_model_override():
    assert SubscriptionProvider(model="opus").model == "opus"
    assert SubscriptionProvider().model == "sonnet"


def test_cli_not_found_maps_to_not_available(monkeypatch):
    from claude_agent_sdk import CLINotFoundError

    monkeypatch.setattr(sub, "query", _fake_query(error=CLINotFoundError("claude not found")))
    with pytest.raises(ProviderNotAvailable) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "Claude Code" in str(exc_info.value)


def test_process_error_maps_to_call_failed_without_raw_detail(monkeypatch):
    from claude_agent_sdk import ProcessError

    monkeypatch.setattr(
        sub, "query", _fake_query(error=ProcessError("raw stderr blob", exit_code=2))
    )
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "로그인" in str(exc_info.value)
    # SDK 예외 원문은 사용자 문구에 넣지 않는다 (설계 결정 14)
    assert "raw stderr blob" not in str(exc_info.value)


def test_cli_connection_error_maps_to_call_failed(monkeypatch):
    from claude_agent_sdk import CLIConnectionError

    monkeypatch.setattr(sub, "query", _fake_query(error=CLIConnectionError("no conn")))
    with pytest.raises(ProviderCallFailed):
        asyncio.run(SubscriptionProvider().complete("q", {}))


def test_error_result_maps_to_call_failed(monkeypatch):
    monkeypatch.setattr(
        sub, "query", _fake_query(_result(is_error=True, errors=["rate limited"]))
    )
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "rate limited" not in str(exc_info.value)
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_subscription_provider.py -q`
Expected: FAIL (`provider`, `subscription` 모듈 없음)

- [ ] **Step 4: provider.py 구현**

```python
"""AI 프로바이더 인터페이스 (설계서 2.4, 단계 3 결정 2).

교체 지점을 원시 호출 하나로 좁힌다: 프로바이더는 프롬프트와 응답 스키마를
받아 구조화 응답을 돌려주기만 한다. 프롬프트 조립과 검증 게이트는 파이프라인
공통부(prompts, service)에 있다. 배포 단계의 앱 관리형(API 키), BYOK는
이 Protocol의 다른 구현으로 추가된다.
"""

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """사용자에게 쉬운 말로 보여줄 AI 호출 오류 (설계서 7.2)."""


class ProviderNotAvailable(ProviderError):
    """호출 환경 자체가 없다 (Claude Code 미설치 등)."""


class ProviderCallFailed(ProviderError):
    """호출은 시도됐지만 실패했다 (미로그인, 한도 소진, 네트워크)."""


@dataclass
class ProviderResponse:
    structured: Any | None  # 스키마에 맞는 구조화 응답 (없으면 None)
    raw_text: str  # 응답 원문 (형식 재실패 시 수동 처리 화면에 보여준다)


class AIProvider(Protocol):
    async def complete(self, prompt: str, schema: dict) -> ProviderResponse: ...
```

- [ ] **Step 5: subscription.py 구현**

```python
"""본인 구독 프로바이더 (설계서 2.4의 1단계): Agent SDK로 로그인된 Claude Code를 구동한다.

실증(2026-08-28, 로드맵 미확인 리스크 해소): API 키 없이 호출이 성공하며
이 PC의 Claude Code 구독 로그인이 자동으로 쓰인다. output_format(json_schema)
지정 시 ResultMessage.structured_output으로 파싱 완료된 JSON이 돌아온다.

오류 원문(영문 stderr 등)은 로그로만 남기고 사용자 문구에는 넣지 않는다 (설계 결정 14).
"""

import logging

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    query,
)

from slidecaptain.pipeline.provider import (
    ProviderCallFailed,
    ProviderNotAvailable,
    ProviderResponse,
)

_LOG = logging.getLogger("slidecaptain.pipeline.subscription")

# CLI 기본 모델(opus 계열)은 사소한 호출에도 사용량이 크다 (2026-08-28 스파이크 실측).
# 별칭을 써서 세부 버전 교체에 흔들리지 않게 한다.
DEFAULT_MODEL = "sonnet"


class SubscriptionProvider:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL

    async def complete(self, prompt: str, schema: dict) -> ProviderResponse:
        options = ClaudeAgentOptions(
            tools=[],  # 도구 없이 순수 생성만
            setting_sources=[],  # 사용자 설정 격리: CLAUDE.md와 스킬이 생성에 개입하지 못하게
            max_turns=1,
            model=self.model,
            output_format={"type": "json_schema", "schema": schema},
        )
        result: ResultMessage | None = None
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message
        except CLINotFoundError as e:
            raise ProviderNotAvailable(
                "Claude Code를 찾지 못했습니다. 이 앱의 AI 생성에는 Claude Code 설치와 "
                "구독 로그인이 필요합니다."
            ) from e
        except (CLIConnectionError, ProcessError, ClaudeSDKError) as e:
            _LOG.warning("AI 호출 실패: %s", e)
            raise ProviderCallFailed(
                "AI 호출에 실패했습니다. Claude Code 로그인 상태와 구독 사용 한도를 "
                "확인한 뒤 잠시 후 다시 시도해 주세요."
            ) from e
        if result is None or result.is_error:
            _LOG.warning("AI 호출 비정상 종료: %s", result.errors if result else "응답 없음")
            raise ProviderCallFailed(
                "AI 호출이 정상적으로 끝나지 않았습니다. 잠시 후 다시 시도해 주세요."
            )
        return ProviderResponse(structured=result.structured_output, raw_text=result.result or "")
```

- [ ] **Step 6: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/pyproject.toml backend/slidecaptain/pipeline/provider.py backend/slidecaptain/pipeline/subscription.py backend/tests/test_subscription_provider.py
git commit -m "feat: 프로바이더 인터페이스와 본인 구독 프로바이더 (Agent SDK, 오류의 쉬운 말 매핑)"
```

---

### Task 8: 프롬프트 조립과 응답 스키마

**Files:**
- Create: `backend/slidecaptain/pipeline/prompts.py`
- Test: `backend/tests/test_prompts.py`

**Interfaces:**
- Consumes: `DeckMeta`, `Deck`, `Chapter`, 슬롯 모델 6종, `CapacityWarning`
- Produces (Task 9가 사용):
  - `build_structure_prompt(meta: DeckMeta, sources: dict[str, str], target_chapters: int | None = None, instructions: str = "") -> str`
  - `structure_response_schema() -> dict`
  - `build_chapter_prompt(deck: Deck, chapter: Chapter, sources: dict[str, str], contract: dict[str, int], today: str, instructions: str = "", chars_per_line: int | None = None) -> str` (cover와 divider는 자료 블록을 넣지 않는다: 결정 11. 보고 정보 블록에 오늘 날짜 포함: 결정 12)
  - `chapter_response_schema(template: str) -> dict`
  - `build_format_retry_prompt(base_prompt: str, raw_text: str) -> str` (실패 원문 동봉: 결정 12)
  - `build_condense_prompt(base_prompt: str, warnings: list[CapacityWarning], draft_json: str) -> str` (직전 초안 동봉: 결정 12. warnings가 비면 일반 축약 지시: 결정 13의 수동 축약이 이 경로를 쓴다)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_prompts.py` 신규:

```python
from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Structure
from slidecaptain.models.render import CapacityWarning
from slidecaptain.pipeline.prompts import (
    build_chapter_prompt,
    build_condense_prompt,
    build_format_retry_prompt,
    build_structure_prompt,
    chapter_response_schema,
    structure_response_schema,
)

META = DeckMeta(title="일본 시장 검토", report_type="strategy", audience="경영진")
SOURCES = {"리서치.md": "시장 규모는 500억 원이다", "메모.txt": "경쟁사는 3곳"}


def test_structure_prompt_contains_context_and_sources():
    prompt = build_structure_prompt(META, SOURCES, target_chapters=8, instructions="표를 적극 활용")
    assert "일본 시장 검토" in prompt
    assert "경영진" in prompt
    assert "8장" in prompt
    assert "표를 적극 활용" in prompt
    assert "=== 자료: 리서치.md ===" in prompt
    assert "시장 규모는 500억 원이다" in prompt
    assert "전략기획형" in prompt  # report_type=strategy의 유형 지침


def test_structure_prompt_without_target_count():
    prompt = build_structure_prompt(META, SOURCES)
    assert "자료 분량에 맞게" in prompt


def test_structure_schema_shape():
    schema = structure_response_schema()
    item = schema["properties"]["chapters"]["items"]
    assert set(item["required"]) == {"topic", "conclusion", "template", "source_refs"}
    assert "cover" in item["properties"]["template"]["enum"]


def _deck_two_chapters() -> Deck:
    return Deck(meta=META, structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장 중", template="bullet_box",
                source_refs=["리서치.md"]),
        Chapter(id="c2", topic="경쟁 구도", template="table"),
    ]))


def test_chapter_prompt_contains_structure_contract_and_report_info():
    deck = _deck_two_chapters()
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], {"리서치.md": SOURCES["리서치.md"]},
        {"bullets_max_lines": 11, "conclusion_max_lines": 2}, today="2026-08-28",
        instructions="숫자 근거 강조", chars_per_line=75,
    )
    assert "[c1] 시장 현황" in prompt
    assert "[c2] 경쟁 구도" in prompt  # 덱 전체 구조가 맥락으로 들어간다
    assert "최대 11줄" in prompt
    assert "약 75자" in prompt  # 줄당 자수 환산 안내 (적대 리뷰 반영)
    assert "숫자 근거 강조" in prompt
    assert "2026-08-28" in prompt  # 보고 정보 블록의 오늘 날짜 (결정 12)
    assert "경영진" in prompt
    assert "메모.txt" not in prompt  # 근거로 매핑되지 않은 자료는 넣지 않는다


def test_cover_prompt_omits_sources_block():
    # cover는 자료가 필요 없다: 자료 전문을 넣으면 호출마다 사용량이 낭비된다 (결정 11)
    deck = Deck(meta=META, structure=Structure(chapters=[
        Chapter(id="c1", topic="표지", template="cover"),
    ]))
    prompt = build_chapter_prompt(deck, deck.structure.chapters[0], SOURCES, {}, today="2026-08-28")
    assert "=== 자료:" not in prompt
    assert "일본 시장 검토" in prompt  # 보고 정보(덱 제목)는 들어간다


def test_chapter_schema_is_slot_model_schema():
    schema = chapter_response_schema("bullet_box")
    assert "conclusion" in schema["properties"]
    schema_table = chapter_response_schema("table")
    assert "columns" in schema_table["properties"]


def test_retry_prompt_carries_failed_raw_text():
    base = "기본 프롬프트"
    retry = build_format_retry_prompt(base, raw_text="깨진 응답 원문")
    assert base in retry
    assert "깨진 응답 원문" in retry  # 매 호출이 새 세션이라 직전 응답을 동봉해야 한다 (결정 12)


def test_condense_prompt_carries_draft_and_warnings():
    base = "기본 프롬프트"
    warning = CapacityWarning(chapter_id="c1", slot="bullets", message="bullets 분량이 영역을 30pt 넘습니다",
                              needed_pt=130.0, available_pt=100.0)
    condense = build_condense_prompt(base, [warning], draft_json='{"bullets": ["초안"]}')
    assert base in condense
    assert "bullets" in condense
    assert '{"bullets": ["초안"]}' in condense  # 직전 초안 동봉 (결정 12)
    assert "축약" in condense


def test_condense_prompt_without_warnings_gives_general_instruction():
    # 수동 축약(결정 13): 초과가 아니어도 사용자가 축약을 요청할 수 있다
    condense = build_condense_prompt("기본", [], draft_json="{}")
    assert "간결" in condense
    assert "초과" not in condense
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompts.py -q`
Expected: FAIL (`prompts` 모듈 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/pipeline/prompts.py`:

```python
"""프롬프트 조립 (설계서 4.1). 호출 2종: 구조안 생성, 장별 내용 생성.

프롬프트는 프로바이더와 무관한 공통부다: 어느 프로바이더로 호출해도 같은
지시가 나가야 산출물 품질이 일관된다 (설계서 1.1의 목적 2).
"""

from slidecaptain.models.deck import (
    BulletBoxSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    Deck,
    DeckMeta,
    DividerSlots,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.render import CapacityWarning

REPORT_TYPE_GUIDES: dict[str, str] = {
    "research": "연구분석형: 목표와 배경, 결과 요약, 결과 상세, 반드시 필요한 사항, 출처 순서로 장을 구성한다",
    "approval": "승인요청형: 핵심 요약과 요청사항, 배경과 문제, 대안 비교와 추천, 실행 계획과 리스크 순서로 장을 구성한다",
    "strategy": "전략기획형: 핵심 결론, 현황, 문제와 변화, 전략 방향과 근거, 실행 로드맵 순서로 장을 구성한다",
}

TEMPLATE_GUIDE = """\
사용할 수 있는 템플릿:
- cover: 표지 (제목, 부제, 날짜, 보고 대상). 첫 장에 쓴다
- summary: 핵심 요약 (결론 강조 박스 + 요점 목록)
- bullet_box: 가장 흔한 본문 장 (불릿 + 결론 박스 + 선택 각주)
- table: 비교표, 데이터 표 (열 이름 + 행 + 선택 각주)
- compare2: 옵션 비교나 전후 대비 카드 2개 + 결론 박스
- divider: 섹션 구분 간지"""

STYLE_RULES = """\
문체 규칙:
- 장 제목(topic)은 주제형으로 짧게 쓴다: 그 장이 무엇을 말하는지. 결론 문장은 conclusion에 둔다
- 본문, 불릿, 표 칸은 압축 문체를 쓴다: 명사형 종결, 조사 생략 허용
- 엠대시(U+2014)와 중점(U+00B7)은 쓰지 않는다
- 자료에 없는 수치를 만들지 않는다. 모든 숫자는 자료 원문에 있는 값만 쓴다"""

_SLOTS_BY_TEMPLATE = {
    "cover": CoverSlots,
    "summary": SummarySlots,
    "bullet_box": BulletBoxSlots,
    "table": TableSlots,
    "compare2": CompareSlots,
    "divider": DividerSlots,
}

_CONTRACT_LABELS = {
    "points_max_lines": "요점 목록 전체",
    "bullets_max_lines": "불릿 전체",
    "conclusion_max_lines": "결론 박스",
    "footnote_max_lines": "각주",
    "rows_max_single_line": "표 행 수 (머리글 포함, 한 줄짜리 행 기준)",
    "card_heading_max_lines": "카드 소제목",
    "card_bullets_max_lines": "카드 하나의 불릿 전체",
}


def _sources_block(sources: dict[str, str]) -> str:
    return "\n\n".join(f"=== 자료: {name} ===\n{text}" for name, text in sources.items())


def build_structure_prompt(
    meta: DeckMeta,
    sources: dict[str, str],
    target_chapters: int | None = None,
    instructions: str = "",
) -> str:
    count_line = (
        f"- 목표 장수: {target_chapters}장 내외 (표지와 간지 포함)"
        if target_chapters
        else "- 목표 장수: 자료 분량에 맞게 정한다 (표지와 간지 포함)"
    )
    extra = f"\n추가 지시:\n{instructions}\n" if instructions else ""
    return f"""당신은 보고 슬라이드의 구조를 설계한다. 아래 자료를 읽고 장 구성안을 만들어라.

보고 정보:
- 제목: {meta.title}
- 보고 유형: {REPORT_TYPE_GUIDES[meta.report_type]}
- 피보고자: {meta.audience or "미지정"}
{count_line}

{TEMPLATE_GUIDE}

{STYLE_RULES}

각 장은 topic(주제형 제목), conclusion(그 장의 결론 한 줄), template(템플릿 이름),
source_refs(그 장의 근거가 되는 자료 파일 이름 목록. 아래 자료의 파일 이름만 쓸 것)를 갖는다.
{extra}
{_sources_block(sources)}"""


def structure_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "conclusion": {"type": "string"},
                        "template": {
                            "type": "string",
                            "enum": ["cover", "summary", "bullet_box", "table", "compare2", "divider"],
                        },
                        "source_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["topic", "conclusion", "template", "source_refs"],
                },
            }
        },
        "required": ["chapters"],
    }


def _contract_block(contract: dict[str, int], chars_per_line: int | None = None) -> str:
    if not contract:
        return "분량 한도: 이 템플릿은 짧은 텍스트만 담는다. 각 칸은 한 줄로 쓴다"
    lines = "\n".join(
        f"- {_CONTRACT_LABELS.get(key, key)}: 최대 {value}줄" for key, value in contract.items()
    )
    hint = (
        f"\n- 환산 안내: 본문 한 줄은 한글 약 {chars_per_line}자 분량이다 (2단 비교 카드 안에서는 그 절반)"
        if chars_per_line
        else ""
    )
    return "분량 한도 (실제 폰트 폭으로 실측한 줄수 기준. 초과하면 재생성을 요구한다):\n" + lines + hint


def build_chapter_prompt(
    deck: Deck,
    chapter: Chapter,
    sources: dict[str, str],
    contract: dict[str, int],
    today: str,
    instructions: str = "",
    chars_per_line: int | None = None,
) -> str:
    structure_lines = "\n".join(
        f"- [{ch.id}] {ch.topic} ({ch.template}): {ch.conclusion}"
        for ch in deck.structure.chapters
    )
    extra = f"\n추가 지시:\n{instructions}\n" if instructions else ""
    # cover와 divider는 자료가 필요 없다: 자료 전문을 넣으면 사용량만 낭비된다 (결정 11)
    sources_part = (
        "" if chapter.template in ("cover", "divider") else "\n" + _sources_block(sources)
    )
    return f"""당신은 보고 슬라이드 한 장의 내용을 채운다.

보고 정보:
- 덱 제목: {deck.meta.title}
- 피보고자: {deck.meta.audience or "미지정"}
- 오늘 날짜: {today}

덱 전체 구조 (맥락으로만 참고):
{structure_lines}

채울 장: [{chapter.id}] {chapter.topic}
- 이 장의 결론: {chapter.conclusion or "미정 (자료에서 도출)"}
- 템플릿: {chapter.template}

{_contract_block(contract, chars_per_line)}

{STYLE_RULES}
{extra}{sources_part}"""


def chapter_response_schema(template: str) -> dict:
    return _SLOTS_BY_TEMPLATE[template].model_json_schema()


def build_format_retry_prompt(base_prompt: str, raw_text: str) -> str:
    # 매 호출이 새 세션이라 직전 응답이 모델 컨텍스트에 없다: 실패 원문을 동봉한다 (결정 12)
    return (
        base_prompt
        + "\n\n직전 시도의 응답이 요구한 JSON 형식에 맞지 않았다. 실패한 응답은 다음과 같다:\n"
        + raw_text[:2000]
        + "\n\n스키마를 정확히 지켜 처음부터 다시 생성하라."
    )


def build_condense_prompt(
    base_prompt: str, warnings: list[CapacityWarning], draft_json: str
) -> str:
    if warnings:
        listed = "\n".join(f"- {w.slot}: {w.message}" for w in warnings)
        ask = "이 초안이 분량 한도를 초과했다. 요지를 유지하면서 다음 항목을 한도 안으로 축약해 다시 생성하라:\n" + listed
    else:
        # 수동 축약(결정 13): 초과가 아니어도 더 간결한 버전을 요청할 수 있다
        ask = "이 초안을 요지를 유지하면서 더 간결하게 축약해 다시 생성하라."
    return base_prompt + "\n\n직전에 생성된 초안은 다음과 같다:\n" + draft_json + "\n\n" + ask
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/slidecaptain/pipeline/prompts.py backend/tests/test_prompts.py
git commit -m "feat: 프롬프트 조립과 응답 스키마 (호출 2종, 용량 계약의 프롬프트 명시)"
```

---

### Task 9: 생성 서비스 (게이트 오케스트레이션)

**Files:**
- Create: `backend/slidecaptain/pipeline/service.py`
- Test: `backend/tests/test_generation_service.py`

**Interfaces:**
- Consumes: `AIProvider`, `ProviderResponse`, `ProviderError` (Task 7), prompts 전부 (Task 8), `normalize_payload`, `collect_strings` (Task 5), `find_unverified_numbers` (Task 6), `capacity_contract`, `hangul_chars_per_line` (Task 3), `build_slide`, `FontMetrics`
- Produces (Task 10의 API가 response_model로 그대로 노출):
  - `StructureResult(status: Literal["ok", "format_error"], structure: Structure | None, raw_text: str, unverified_numbers: list[str], format_retried: bool)`
  - `ChapterResult(status: Literal["ok", "format_error"], slots: Slots | None, raw_text: str, warnings: list[CapacityWarning], unverified_numbers: list[str], format_retried: bool, condensed: bool)`
  - `GenerationService(provider: AIProvider, metrics: FontMetrics)`:
    - `async generate_structure(meta, sources, target_chapters=None, instructions="") -> StructureResult`
    - `async generate_chapter(deck, chapter_id, sources, preset, instructions="") -> ChapterResult` (없는 장이면 `ValueError`)
    - `async condense_chapter(deck, chapter_id, current_slots, sources, preset, instructions="") -> ChapterResult` (수동 축약, 결정 13. 템플릿 불일치면 `ValueError`)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_generation_service.py` 신규:

```python
import asyncio

import pytest

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import BulletBoxSlots, Chapter, Deck, DeckMeta, Structure, TableSlots
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderResponse
from slidecaptain.pipeline.service import GenerationService

METRICS = FontMetrics.load_default()
SOURCES = {"리서치.md": "시장 규모는 500억 원이다. 2026년 기준."}


class StubProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _service(responses) -> tuple[GenerationService, StubProvider]:
    stub = StubProvider(responses)
    return GenerationService(stub, METRICS), stub


def _deck() -> Deck:
    return Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장", template="bullet_box",
                source_refs=["리서치.md"]),
    ]))


STRUCTURE_PAYLOAD = {"chapters": [
    {"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
    {"topic": "시장 현황", "conclusion": "규모 500억", "template": "bullet_box",
     "source_refs": ["리서치.md", "없는파일.md"]},
]}

SLOTS_PAYLOAD = {"template": "bullet_box",
                 "bullets": [{"text": "시장 규모 500억", "level": 0}],
                 "conclusion": "성장 지속", "footnote": ""}


def test_generate_structure_ok_assigns_ids_and_filters_refs():
    service, stub = _service([ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "ok"
    ids = [ch.id for ch in result.structure.chapters]
    assert ids == ["c1", "c2"]
    assert result.structure.chapters[1].source_refs == ["리서치.md"]  # 실존 파일만
    assert result.format_retried is False
    assert len(stub.calls) == 1


def test_generate_structure_format_retry_then_success():
    service, stub = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad"),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good"),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "ok"
    assert result.format_retried is True
    assert "형식" in stub.calls[1][0]  # 재시도 프롬프트에 형식 오류 안내가 붙는다


def test_generate_structure_format_failure_returns_raw():
    service, _ = _service([
        ProviderResponse(structured=None, raw_text="원문1"),
        ProviderResponse(structured={"chapters": "문자열이면 안 됨"}, raw_text="원문2"),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "format_error"
    assert result.structure is None
    assert result.raw_text == "원문2"


def test_generate_structure_flags_unverified_numbers():
    payload = {"chapters": [{"topic": "시장", "conclusion": "규모 700억으로 성장",
                             "template": "bullet_box", "source_refs": []}]}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.unverified_numbers == ["700"]


def test_generate_chapter_ok_normalizes_and_verifies():
    payload = {"template": "bullet_box",
               "bullets": [{"text": "시장  규모\n500억", "level": 0}],
               "conclusion": "성장 지속", "footnote": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.slots.bullets[0].text == "시장 규모 500억"  # 정규화 적용
    assert result.unverified_numbers == []
    assert result.warnings == []
    assert result.condensed is False


def test_generate_chapter_condenses_once_on_overflow():
    long_bullets = [{"text": f"근거 없는 장문 불릿 문장 {i}번이며 자료 원문의 맥락 설명이 길게 이어진다", "level": 0}
                    for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, stub = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r2"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is True
    assert result.warnings == []
    assert "축약" in stub.calls[1][0]


def test_generate_chapter_keeps_warnings_if_condense_still_over():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=over_payload, raw_text="r2"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is True
    assert any(w.slot == "bullets" for w in result.warnings)


def test_generate_chapter_condense_format_failure_keeps_first_draft():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=None, raw_text="깨진 축약"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is False  # 축약 실패: 초안 유지
    assert any(w.slot == "bullets" for w in result.warnings)
    assert len(result.slots.bullets) == 30


def test_generate_chapter_template_field_is_forced():
    wrong_template = dict(SLOTS_PAYLOAD, template="table")
    service, _ = _service([ProviderResponse(structured=wrong_template, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    # AI가 template을 잘못 채워도 장의 템플릿으로 강제되어 형식 오류가 아니다
    assert result.status == "ok"
    assert result.slots.template == "bullet_box"


def test_generate_chapter_unknown_chapter_raises():
    service, _ = _service([])
    with pytest.raises(ValueError):
        asyncio.run(service.generate_chapter(_deck(), "없는장", SOURCES, Preset()))


def test_provider_error_propagates():
    service, _ = _service([ProviderCallFailed("한도 소진")])
    with pytest.raises(ProviderCallFailed):
        asyncio.run(service.generate_structure(_deck().meta, SOURCES))


SOURCES_TWO = {"리서치.md": "시장 규모는 500억 원이다", "별도.md": "점유율은 37%다"}


def _deck_refs_one() -> Deck:
    return Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장", template="bullet_box",
                source_refs=["리서치.md"]),
    ]))


def test_chapter_numbers_checked_against_all_sources_not_only_refs():
    # 결정 6: 대조는 자료 전체 상대. 37은 refs 밖 자료(별도.md)에 있으므로 경고가 아니다
    payload = {"template": "bullet_box",
               "bullets": [{"text": "점유율 37%", "level": 0}],
               "conclusion": "성장", "footnote": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck_refs_one(), "c1", SOURCES_TWO, Preset()))
    assert result.unverified_numbers == []


def test_chapter_unverified_number_reported():
    payload = {"template": "bullet_box",
               "bullets": [{"text": "점유율 89%", "level": 0}],
               "conclusion": "성장", "footnote": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck_refs_one(), "c1", SOURCES_TWO, Preset()))
    assert result.unverified_numbers == ["89"]


def test_generate_chapter_format_retry_then_success():
    service, stub = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="good"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.format_retried is True
    assert "bad" in stub.calls[1][0]  # 재시도 프롬프트에 실패 원문이 동봉된다 (결정 12)


def test_generate_chapter_format_failure_returns_raw():
    service, _ = _service([
        ProviderResponse(structured=None, raw_text="원문1"),
        ProviderResponse(structured=None, raw_text="원문2"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "format_error"
    assert result.slots is None
    assert result.raw_text == "원문2"


def test_long_title_warning_does_not_trigger_condense():
    # title 경고는 슬롯 재생성으로 못 고친다: 축약을 발동하면 호출만 낭비된다 (결정 5)
    long_topic = "제목 영역 한 줄을 확실히 넘기기 위한 매우 길고 긴 장 제목 문장이며 계속 이어진다" * 2
    deck = Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic=long_topic, conclusion="성장", template="bullet_box",
                source_refs=["리서치.md"]),
    ]))
    service, stub = _service([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    result = asyncio.run(service.generate_chapter(deck, "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert len(stub.calls) == 1  # 축약 호출이 발동하지 않는다
    assert result.condensed is False
    assert any(w.slot == "title" for w in result.warnings)  # 경고 자체는 결과에 남는다


def test_condense_call_carries_draft_json():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, stub = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r2"),
    ])
    asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert "장문 불릿 0번" in stub.calls[1][0]  # 축약 프롬프트에 직전 초안이 동봉된다 (결정 12)


def test_condense_provider_error_keeps_draft():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderCallFailed("한도"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"  # 축약 호출 실패로 유효한 초안을 잃지 않는다
    assert result.condensed is False
    assert any(w.slot == "bullets" for w in result.warnings)


def test_cover_metadata_fields_exempt_from_number_check():
    deck = Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c0", topic="표지", template="cover"),
    ]))
    payload = {"template": "cover", "title": "검토", "subtitle": "",
               "date": "2026-08-28", "audience": "경영진 30명"}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(deck, "c0", SOURCES, Preset()))
    assert result.unverified_numbers == []  # date와 audience는 대조 대상이 아니다 (결정 6)


def test_condense_chapter_manual():
    # 수동 축약 (결정 13): 현재 슬롯을 초안으로 받아 1회 축약한다
    current = BulletBoxSlots(bullets=[{"text": "시장 규모 500억과 부연 설명", "level": 0}],
                             conclusion="성장 지속")
    service, stub = _service([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    result = asyncio.run(service.condense_chapter(_deck(), "c1", current, SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is True
    assert "축약" in stub.calls[0][0]
    assert "시장 규모 500억과 부연 설명" in stub.calls[0][0]  # 현재 슬롯이 초안으로 동봉된다


def test_condense_chapter_template_mismatch_raises():
    wrong = TableSlots(columns=["a"], rows=[["b"]])
    service, _ = _service([])
    with pytest.raises(ValueError):
        asyncio.run(service.condense_chapter(_deck(), "c1", wrong, SOURCES, Preset()))
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_generation_service.py -q`
Expected: FAIL (`service` 모듈 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/pipeline/service.py`:

```python
"""생성 서비스: 프롬프트 조립 → 프로바이더 호출 → 검증 게이트 (설계서 4).

게이트는 코드가 수행하며 호출마다 자동이다 (설계서 4.2):
1. 형식: 응답을 스키마로 검증. 실패 시 1회 재시도, 재실패 시 원문을 담아 반환 (수동 처리 경로)
2. 분량: 레이아웃 실측 경고 확인. 초과 시 1회 축약 재생성 (해소 사다리 1단계, 장별 생성만)
3. 수치: 생성 문장의 숫자를 자료 원문 전체와 대조. 없는 숫자는 경고 목록 (차단 아님)
"""

from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from slidecaptain.layout.templates import build_slide
from slidecaptain.metrics.capacity import capacity_contract, hangul_chars_per_line
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Slots, Structure
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import CapacityWarning
from slidecaptain.pipeline.normalize import collect_strings, normalize_payload
from slidecaptain.pipeline.numbers import find_unverified_numbers
from slidecaptain.pipeline.prompts import (
    build_chapter_prompt,
    build_condense_prompt,
    build_format_retry_prompt,
    build_structure_prompt,
    chapter_response_schema,
    structure_response_schema,
)
from slidecaptain.pipeline.provider import AIProvider, ProviderError, ProviderResponse

_SLOTS_ADAPTER: TypeAdapter = TypeAdapter(Slots)

# 자료에 있을 이유가 없는 메타성 필드: 수치 대조 수집에서 제외한다 (설계 결정 6)
_NUMBER_EXEMPT_FIELDS: dict[str, set[str]] = {
    "cover": {"date", "audience"},
    "divider": {"section_no"},
}


def _fixable(warnings: list[CapacityWarning]) -> list[CapacityWarning]:
    """축약 재생성으로 고칠 수 있는 경고만 남긴다 (설계 결정 5).

    title 경고는 구조안의 topic에서 오므로 슬롯 재생성으로는 해소되지 않는다.
    """
    return [w for w in warnings if w.slot != "title"]


class StructureResult(BaseModel):
    status: Literal["ok", "format_error"]
    structure: Structure | None = None
    raw_text: str = ""
    unverified_numbers: list[str] = []
    format_retried: bool = False


class ChapterResult(BaseModel):
    status: Literal["ok", "format_error"]
    slots: Slots | None = None
    raw_text: str = ""
    warnings: list[CapacityWarning] = []
    unverified_numbers: list[str] = []
    format_retried: bool = False
    condensed: bool = False


def _try_parse(parse: Callable[[Any], Any], response: ProviderResponse) -> Any | None:
    if response.structured is None:
        return None
    try:
        return parse(normalize_payload(response.structured))
    except (ValidationError, KeyError, TypeError, ValueError):
        return None


class GenerationService:
    def __init__(self, provider: AIProvider, metrics: FontMetrics) -> None:
        self.provider = provider
        self.metrics = metrics

    async def _call_with_format_gate(
        self, prompt: str, schema: dict, parse: Callable[[Any], Any]
    ) -> tuple[Any | None, str, bool]:
        """게이트 1 (형식): 실패 시 1회 재시도. (parsed, raw_text, retried)를 돌려준다."""
        response = await self.provider.complete(prompt, schema)
        parsed = _try_parse(parse, response)
        if parsed is not None:
            return parsed, response.raw_text, False
        retry = await self.provider.complete(
            build_format_retry_prompt(prompt, response.raw_text), schema
        )
        return _try_parse(parse, retry), retry.raw_text, True

    async def generate_structure(
        self,
        meta: DeckMeta,
        sources: dict[str, str],
        target_chapters: int | None = None,
        instructions: str = "",
    ) -> StructureResult:
        prompt = build_structure_prompt(meta, sources, target_chapters, instructions)

        def parse(payload: Any) -> Structure:
            chapters = [
                Chapter(
                    id=f"c{i}",  # id는 서버가 부여한다 (설계 결정 10)
                    topic=ch["topic"],
                    conclusion=ch["conclusion"],
                    template=ch["template"],
                    source_refs=[r for r in ch["source_refs"] if r in sources],
                )
                for i, ch in enumerate(payload["chapters"], start=1)
            ]
            return Structure(chapters=chapters)

        structure, raw, retried = await self._call_with_format_gate(
            prompt, structure_response_schema(), parse
        )
        if structure is None:
            return StructureResult(status="format_error", raw_text=raw, format_retried=retried)
        texts = [t for ch in structure.chapters for t in (ch.topic, ch.conclusion)]
        return StructureResult(
            status="ok",
            structure=structure,
            raw_text=raw,
            unverified_numbers=find_unverified_numbers(texts, list(sources.values())),
            format_retried=retried,
        )

    async def generate_chapter(
        self,
        deck: Deck,
        chapter_id: str,
        sources: dict[str, str],
        preset: Preset,
        instructions: str = "",
    ) -> ChapterResult:
        chapter = self._find_chapter(deck, chapter_id)
        prompt = self._chapter_prompt(deck, chapter, sources, preset, instructions)
        schema = chapter_response_schema(chapter.template)
        parse = self._slots_parser(chapter)

        slots, raw, retried = await self._call_with_format_gate(prompt, schema, parse)
        if slots is None:
            return ChapterResult(status="format_error", raw_text=raw, format_retried=retried)

        warnings = self._measure(chapter, slots, preset)
        condensed = False
        fixable = _fixable(warnings)
        if fixable:  # 게이트 2 (분량): 1회 축약 재생성. 직전 초안을 동봉한다 (설계 결정 12)
            try:
                condense_response = await self.provider.complete(
                    build_condense_prompt(prompt, fixable, slots.model_dump_json()), schema
                )
            except ProviderError:
                condense_response = None  # 축약 호출 실패로 유효한 초안을 잃지 않는다
            if condense_response is not None:
                condensed_slots = _try_parse(parse, condense_response)
                if condensed_slots is not None:
                    slots = condensed_slots
                    raw = condense_response.raw_text
                    warnings = self._measure(chapter, slots, preset)
                    condensed = True

        return self._chapter_result(chapter, slots, raw, warnings, sources, retried, condensed)

    async def condense_chapter(
        self,
        deck: Deck,
        chapter_id: str,
        current_slots: Any,
        sources: dict[str, str],
        preset: Preset,
        instructions: str = "",
    ) -> ChapterResult:
        """수동 축약 (설계 결정 13): 현재 슬롯을 초안으로 받아 1회 축약한다.

        이 호출 자체가 축약이므로 추가 축약 재시도는 없다. 형식과 수치 게이트는 동일하게 걸린다.
        """
        chapter = self._find_chapter(deck, chapter_id)
        if current_slots.template != chapter.template:
            raise ValueError(
                f"장 {chapter_id}의 템플릿({chapter.template})과 보낸 슬롯의 "
                f"템플릿({current_slots.template})이 다릅니다"
            )
        base = self._chapter_prompt(deck, chapter, sources, preset, instructions)
        warnings_now = _fixable(self._measure(chapter, current_slots, preset))
        prompt = build_condense_prompt(base, warnings_now, current_slots.model_dump_json())
        slots, raw, retried = await self._call_with_format_gate(
            prompt, chapter_response_schema(chapter.template), self._slots_parser(chapter)
        )
        if slots is None:
            return ChapterResult(status="format_error", raw_text=raw, format_retried=retried)
        warnings = self._measure(chapter, slots, preset)
        return self._chapter_result(chapter, slots, raw, warnings, sources, retried, condensed=True)

    # -- 내부 공통 ---------------------------------------------------------

    def _find_chapter(self, deck: Deck, chapter_id: str) -> Chapter:
        chapter = next((ch for ch in deck.structure.chapters if ch.id == chapter_id), None)
        if chapter is None:
            raise ValueError(f"구조안에 없는 장입니다: {chapter_id}")
        return chapter

    def _chapter_prompt(
        self, deck: Deck, chapter: Chapter, sources: dict[str, str], preset: Preset, instructions: str
    ) -> str:
        # 프롬프트에는 근거로 매핑된 자료만 넣되, 매핑이 비면 전체로 폴백한다 (설계 결정 11).
        # cover와 divider의 자료 생략은 build_chapter_prompt가 처리한다
        chapter_sources = {n: sources[n] for n in chapter.source_refs if n in sources} or sources
        return build_chapter_prompt(
            deck,
            chapter,
            chapter_sources,
            capacity_contract(chapter.template, preset),
            today=date.today().isoformat(),
            instructions=instructions,
            chars_per_line=hangul_chars_per_line(preset, self.metrics.face(False)),
        )

    def _slots_parser(self, chapter: Chapter) -> Callable[[Any], Any]:
        def parse(payload: Any) -> Any:
            # AI가 template 판별자를 잘못 채워도 장의 템플릿으로 강제한다
            return _SLOTS_ADAPTER.validate_python({**payload, "template": chapter.template})

        return parse

    def _chapter_result(
        self,
        chapter: Chapter,
        slots: Any,
        raw: str,
        warnings: list[CapacityWarning],
        sources: dict[str, str],
        retried: bool,
        condensed: bool,
    ) -> ChapterResult:
        exempt = _NUMBER_EXEMPT_FIELDS.get(chapter.template, set())
        texts = collect_strings(slots.model_dump(exclude=exempt))
        return ChapterResult(
            status="ok",
            slots=slots,
            raw_text=raw,
            warnings=warnings,
            unverified_numbers=find_unverified_numbers(texts, list(sources.values())),
            format_retried=retried,
            condensed=condensed,
        )

    def _measure(self, chapter: Chapter, slots: Any, preset: Preset) -> list[CapacityWarning]:
        return build_slide(chapter, slots, 1, preset, self.metrics).warnings
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/slidecaptain/pipeline/service.py backend/tests/test_generation_service.py
git commit -m "feat: 생성 서비스와 검증 게이트 3종 (형식 재시도, 분량 축약, 수치 대조)"
```

---

### Task 10: 생성 API 엔드포인트와 serve --model

**Files:**
- Modify: `backend/slidecaptain/server/app.py`
- Modify: `backend/slidecaptain/__main__.py`
- Modify: `backend/openapi.json` (재생성), `frontend/src/api/types.ts` (재생성)
- Test: `backend/tests/test_api_generate.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `GenerationService`, `StructureResult`, `ChapterResult` (Task 9), `AIProvider`, `ProviderError` (Task 7), `SubscriptionProvider` (Task 7)
- Produces:
  - `create_app(store: ProjectStore, provider: AIProvider | None = None) -> FastAPI` (기존 호출부와 호환: provider 생략 시 생성 엔드포인트만 503)
  - HTTP: `POST /api/projects/{name}/generate/structure` (본문 `{"target_chapters": int|null, "instructions": str}`), `POST /api/projects/{name}/generate/chapter/{chapter_id}` (본문 `{"instructions": str}`), `POST /api/projects/{name}/generate/chapter/{chapter_id}/condense` (본문 `{"slots": Slots, "instructions": str}`. 수동 축약, 설계 결정 13)
  - 오류: ProviderError → 503, 자료 없음 → 422, 없는 장 → 404, 축약 슬롯의 템플릿 불일치 → 422. 문구는 비개발자가 화면 기준으로 수행할 수 있는 행동 안내 (2026-08-28 적대 리뷰 반영). 생성 결과는 저장하지 않는다 (설계 결정 3)
  - CLI: `serve --model MODEL` (기본 None → 프로바이더 기본 sonnet). 앱 조립부를 `_build_serve_app(data_dir, model)` 헬퍼로 분리해 배선을 테스트 가능하게 한다

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_generate.py` 신규:

```python
import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderResponse
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

STRUCTURE_PAYLOAD = {"chapters": [
    {"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
    {"topic": "시장 현황", "conclusion": "규모 500억", "template": "bullet_box",
     "source_refs": ["리서치.md"]},
]}

SLOTS_PAYLOAD = {"template": "bullet_box",
                 "bullets": [{"text": "시장 규모 500억", "level": 0}],
                 "conclusion": "성장 지속", "footnote": ""}


class StubProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    async def complete(self, prompt, schema):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _client(store, responses) -> TestClient:
    return TestClient(create_app(store, provider=StubProvider(responses)))


def _project_with_structure(client):
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"] = {"chapters": [
        {"id": "c1", "topic": "시장 현황", "conclusion": "성장", "template": "bullet_box",
         "source_refs": ["리서치.md"]},
    ]}
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_generate_structure_returns_draft_without_saving(store):
    client = _client(store, [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert [ch["id"] for ch in body["structure"]["chapters"]] == ["c1", "c2"]
    # 초안일 뿐 저장되지 않는다 (설계 결정 3)
    assert client.get("/api/projects/p1/deck").json()["structure"]["chapters"] == []


def test_generate_structure_without_sources_422(store):
    client = _client(store, [])
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 422
    assert "자료" in r.json()["detail"]


def test_generate_chapter_ok(store):
    client = _client(store, [ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["slots"]["template"] == "bullet_box"
    assert body["unverified_numbers"] == []
    # 생성 결과는 저장되지 않는다
    assert client.get("/api/projects/p1/deck").json()["slides"] == []


def test_generate_chapter_unknown_chapter_404(store):
    client = _client(store, [])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/없는장", json={})
    assert r.status_code == 404


def test_provider_failure_returns_503(store):
    client = _client(store, [ProviderCallFailed("한도를 소진했습니다")])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 503
    assert "한도" in r.json()["detail"]


def test_generate_without_provider_returns_503(store):
    client = TestClient(create_app(store))  # provider 없음: 기존 시그니처 호환
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 503


def test_condense_chapter_endpoint(store):
    client = _client(store, [ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    _project_with_structure(client)
    body = {"slots": {"template": "bullet_box",
                      "bullets": [{"text": "현재 내용이 다소 길다", "level": 0}],
                      "conclusion": "성장 지속", "footnote": ""}}
    r = client.post("/api/projects/p1/generate/chapter/c1/condense", json=body)
    assert r.status_code == 200
    assert r.json()["condensed"] is True


def test_condense_chapter_template_mismatch_422(store):
    client = _client(store, [])
    _project_with_structure(client)
    body = {"slots": {"template": "table", "columns": ["a"], "rows": [["b"]]}}
    r = client.post("/api/projects/p1/generate/chapter/c1/condense", json=body)
    assert r.status_code == 422
```

`backend/tests/test_cli.py`에 serve --model 배선 테스트도 추가 (파서 테스트와 별개로, CLI 인자가 프로바이더까지 실제로 전달되는지 고정한다. 2026-08-28 적대 리뷰 반영):

```python
def test_serve_app_wires_model_to_provider(tmp_path, monkeypatch):
    import slidecaptain.pipeline.subscription as sub
    from slidecaptain.__main__ import _build_serve_app

    captured = {}

    class Spy(sub.SubscriptionProvider):
        def __init__(self, model=None):
            captured["model"] = model
            super().__init__(model)

    monkeypatch.setattr(sub, "SubscriptionProvider", Spy)
    _build_serve_app(tmp_path / "data", "opus")
    assert captured["model"] == "opus"
```

`backend/tests/test_cli.py`에 추가:

```python
def test_serve_parser_accepts_model():
    from slidecaptain.__main__ import build_parser

    args = build_parser().parse_args(["serve", "--model", "opus"])
    assert args.model == "opus"
    args_default = build_parser().parse_args(["serve"])
    assert args_default.model is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_generate.py tests/test_cli.py -q`
Expected: FAIL (라우트 없음 404, --model 인자 없음)

- [ ] **Step 3: 서버 구현**

`backend/slidecaptain/server/app.py`에 import 추가:

```python
from slidecaptain.pipeline.provider import AIProvider, ProviderError
from slidecaptain.pipeline.service import ChapterResult, GenerationService, StructureResult
```

요청 모델 추가 (`ExportResult` 아래. `Slots`를 `slidecaptain.models.deck` import에 추가한다):

```python
class GenerateStructureRequest(BaseModel):
    target_chapters: int | None = None
    instructions: str = ""


class GenerateChapterRequest(BaseModel):
    instructions: str = ""


class CondenseChapterRequest(BaseModel):
    slots: Slots  # 화면이 들고 있는 현재 슬롯 (미저장 수정 포함. 설계 결정 13)
    instructions: str = ""
```

`create_app` 시그니처와 본문 수정:

```python
def create_app(store: ProjectStore, provider: AIProvider | None = None) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")
    metrics = FontMetrics.load_default()  # 앱 수명 동안 1회 로드
    service = GenerationService(provider, metrics) if provider is not None else None

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request, exc: ProviderError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    def _require_service() -> GenerationService:
        if service is None:
            # 오류 문구는 비개발자가 수행할 수 있는 행동으로 (2026-08-28 적대 리뷰 반영)
            raise HTTPException(
                503, "AI 생성 기능을 사용할 수 없는 상태입니다. 앱을 다시 시작해 주세요."
            )
        return service

    def _load_sources(name: str) -> dict[str, str]:
        files = store.list_sources(name)
        if not files:
            raise HTTPException(
                422,
                "입력 자료가 없습니다. 자료 화면에서 파일을 추가하거나, "
                "프로젝트 폴더의 sources에 텍스트 파일을 넣어 주세요.",
            )
        return {f: store.read_source(name, f) for f in files}
```

기존 라우트들 아래에 추가:

```python
    @app.post("/api/projects/{name}/generate/structure", response_model=StructureResult)
    async def generate_structure(name: str, req: GenerateStructureRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        sources = _load_sources(name)
        return await svc.generate_structure(deck.meta, sources, req.target_chapters, req.instructions)

    @app.post("/api/projects/{name}/generate/chapter/{chapter_id}", response_model=ChapterResult)
    async def generate_chapter(name: str, chapter_id: str, req: GenerateChapterRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        if all(ch.id != chapter_id for ch in deck.structure.chapters):
            raise HTTPException(404, f"구조안에 없는 장입니다: {chapter_id}")
        preset = _validated_preset(deck)
        sources = _load_sources(name)
        return await svc.generate_chapter(deck, chapter_id, sources, preset, req.instructions)

    @app.post(
        "/api/projects/{name}/generate/chapter/{chapter_id}/condense",
        response_model=ChapterResult,
    )
    async def condense_chapter(name: str, chapter_id: str, req: CondenseChapterRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        chapter = next((ch for ch in deck.structure.chapters if ch.id == chapter_id), None)
        if chapter is None:
            raise HTTPException(404, f"구조안에 없는 장입니다: {chapter_id}")
        if req.slots.template != chapter.template:
            raise HTTPException(
                422,
                f"이 장의 템플릿({chapter.template})과 보낸 내용의 템플릿({req.slots.template})이 "
                "다릅니다. 화면을 새로고침한 뒤 다시 시도해 주세요.",
            )
        preset = _validated_preset(deck)
        sources = _load_sources(name)
        return await svc.condense_chapter(deck, chapter_id, req.slots, sources, preset, req.instructions)
```

- [ ] **Step 4: CLI 구현**

`backend/slidecaptain/__main__.py`의 serve 파서에 추가:

```python
    p_serve.add_argument("--model", default=None, help="AI 생성 모델 (기본: sonnet)")
```

앱 조립부를 모듈 수준 헬퍼로 분리한다 (uvicorn.run과 분리해 배선을 테스트 가능하게. 2026-08-28 적대 리뷰 반영):

```python
def _build_serve_app(data_dir: Path, model: str | None):
    from slidecaptain.pipeline.subscription import SubscriptionProvider
    from slidecaptain.server.app import create_app
    from slidecaptain.storage.file_store import FileProjectStore

    return create_app(FileProjectStore(data_dir), provider=SubscriptionProvider(model=model))
```

`_run_serve`에서 앱 생성부를 교체 (기존의 create_app, FileProjectStore 지역 import는 헬퍼로 옮겨졌으므로 정리한다):

```python
    app = _build_serve_app(args.data_dir, args.model)
```

모듈 docstring의 serve 줄도 갱신한다: `- python -m slidecaptain serve [--data-dir PATH] [--port N] [--model MODEL]`

- [ ] **Step 5: 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: `test_openapi.py`의 동기화 테스트만 FAIL (스키마가 바뀌었으므로), 나머지 전체 PASS

- [ ] **Step 6: OpenAPI와 TS 타입 재생성**

Run (backend 폴더): `.venv/Scripts/python.exe scripts/dump_openapi.py`
Run (저장소 루트): `npm --prefix frontend run generate-types`
Run (backend 폴더): `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 7: 커밋**

```bash
git add backend/slidecaptain/server/app.py backend/slidecaptain/__main__.py backend/tests/test_api_generate.py backend/tests/test_cli.py backend/openapi.json frontend/src/api/types.ts
git commit -m "feat: 구조안과 장별 생성 API, serve --model (프로바이더 주입과 503 매핑)"
```

---

### Task 11: 실호출 스모크와 문서 갱신

**Files:**
- Create: `backend/scripts/smoke_generation.py`
- Modify: `docs/plans/2026-08-27-mvp-roadmap.md`
- Modify: `docs/specs/2026-08-27-mvp-design.md` (정정 3건, 날짜 병기)
- Modify: `README.md` (기능 요약 1~2줄)

**Interfaces:**
- Consumes: `GenerationService`, `SubscriptionProvider` (전 태스크)
- Produces: 실호출 검증 1회의 기록. 로드맵의 진행 상태, 이월표, 미확인 리스크 문단 갱신. 설계서와 구현의 정합 (하위 문서의 조용한 재정의 금지 관례 준수)

- [ ] **Step 1: 스모크 스크립트 작성**

`backend/scripts/smoke_generation.py` 신규:

```python
"""실호출 스모크: 구독 프로바이더로 구조안과 장 하나를 실제 생성해 본다.

pytest 대상이 아니다 (실호출은 구독 사용량을 쓴다). 수동 실행:
  backend 폴더에서 .venv/Scripts/python.exe scripts/smoke_generation.py
"""

import asyncio
import json

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, DeckMeta, Structure
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.service import GenerationService
from slidecaptain.pipeline.subscription import SubscriptionProvider

SOURCES = {
    "리서치.md": (
        "국내 구독형 콘텐츠 시장 규모는 2025년 1조 2,000억 원으로 추정된다. "
        "연평균 성장률은 14.5%다. 주요 사업자는 3곳이며 상위 사업자 점유율은 62%다."
    )
}


async def main() -> None:
    service = GenerationService(SubscriptionProvider(), FontMetrics.load_default())
    meta = DeckMeta(title="구독 시장 검토", report_type="research", audience="경영진")

    print("== 구조안 생성 ==")
    structure_result = await service.generate_structure(meta, SOURCES, target_chapters=4)
    print("status:", structure_result.status, "/ 재시도:", structure_result.format_retried)
    print("근거 없는 수치:", structure_result.unverified_numbers)
    if structure_result.status != "ok":
        print("원문:", structure_result.raw_text[:500])
        return
    for ch in structure_result.structure.chapters:
        print(f"  [{ch.id}] {ch.topic} ({ch.template}) refs={ch.source_refs}")

    body_chapter = next(
        (ch for ch in structure_result.structure.chapters if ch.template not in ("cover", "divider")),
        None,
    )
    if body_chapter is None:
        print("본문 장이 없어 장별 생성을 건너뜁니다 (구조안이 표지와 간지뿐입니다).")
        return
    deck = Deck(meta=meta, structure=Structure(chapters=structure_result.structure.chapters))

    print(f"== 장별 생성: [{body_chapter.id}] {body_chapter.topic} ==")
    chapter_result = await service.generate_chapter(deck, body_chapter.id, SOURCES, Preset())
    print("status:", chapter_result.status, "/ 축약:", chapter_result.condensed)
    print("분량 경고:", [w.slot for w in chapter_result.warnings])
    print("근거 없는 수치:", chapter_result.unverified_numbers)
    if chapter_result.slots is not None:
        print(json.dumps(chapter_result.slots.model_dump(), ensure_ascii=False, indent=2)[:1200])


asyncio.run(main())
```

- [ ] **Step 2: 스모크 실행 (실호출 1회)**

Run (backend 폴더): `.venv/Scripts/python.exe scripts/smoke_generation.py`
Expected: 구조안 status ok (장 4개 내외, cover 포함), 장별 생성 status ok, 분량 경고 없음 또는 소수, 근거 없는 수치 목록이 자료 밖 숫자만 담음. 실패하면 원인을 systematic-debugging으로 추적한다 (프롬프트, 스키마, SDK 순).

- [ ] **Step 3: 로드맵 갱신**

`docs/plans/2026-08-27-mvp-roadmap.md`:

1. "미확인 리스크" 문단을 해소 기록으로 교체: 무키 구독 호출 실증 성공(2026-08-28, 스파이크와 스모크), 구조화 출력 확인. 미로그인 실패 문구의 실환경 실증(원인별 세분 안내 포함)은 이월표에 신규 등재("다른 환경에서 처음 실행할 때", 폰트 실증과 같은 묶음)
2. 이월표에서 이 계획이 소화한 7건에 "단계 3에서 처리 완료 (2026-08-28)" 표시: 장 순서 진본(구조안 순서 채택), 표 셀 개행(스키마 금지 채택), 각주 슬롯 경고, 장 제목과 카드 소제목의 용량 계약과 경고(heading은 계약과 경고 모두, topic은 구조안 소유라 렌더 경고만: 부분 처리 사유 병기), 비UTF-8 422(cp949 폴백 포함으로 확장, 사유 병기), 텍스트 상류 정규화, httpx2 검토(현 조합에서 경고 재현 불가로 해소)
3. 진행 상태에 단계 3 완료 체크 (최종 리뷰 통과 후)
4. 단계 3의 새 방치 확정이나 이월이 리뷰에서 나오면 같은 절에 추가

- [ ] **Step 4: 설계서 정정 3건 (날짜와 사유 병기, 2026-08-28 적대 리뷰 반영)**

`docs/specs/2026-08-27-mvp-design.md`:

1. **2.2 구성 요소 3 (AI 프로바이더)**: "프롬프트 조립 → Claude 호출 → 응답 스키마 검증. 교체 가능한 부품" 서술에 정밀화를 병기한다: "(2026-08-28 단계 3 정밀화: 교체 지점은 원시 호출 `complete(prompt, schema)` 하나로 좁히고, 프롬프트 조립과 검증 게이트는 프로바이더와 무관한 공통부에 둔다. 프로바이더마다 프롬프트가 달라지면 품질 일관성 목적이 깨지기 때문이다)"
2. **3.2 모델 검증 목록**: 기존 3건(장 id 중복 금지, 존재하는 장, 템플릿 일치)에 단계 3 확정 2건을 추가한다: "같은 장을 가리키는 슬라이드 중복 금지, 표 칸 안 줄바꿈 금지 (2026-08-28 단계 3 확정. 전자는 덱 순서의 진본을 구조안으로 확정한 결정의 전제, 후자는 행 높이 계산과 균일성 보호)"
3. **4.2 게이트 3 (수치 대조)**: 적용 범위 한정을 병기한다: "(2026-08-28 단계 3 정밀화: 두 자리 이상 숫자만 대조하고, 표지의 날짜와 보고 대상 같은 메타성 필드는 제외한다. 한 자리 정수는 개수 표현이 대부분이라 경고 소음이 되기 때문이며, 이만큼 보증 범위가 좁아진다)"

- [ ] **Step 5: README 갱신**

`README.md`의 기능 요약에 AI 생성 한 줄을 추가한다 (구조안 생성과 장별 생성과 수동 축약 API, 검증 게이트 3종, 본인 구독 호출). 기존 서술 형식을 따른다.

- [ ] **Step 6: 커밋**

```bash
git add backend/scripts/smoke_generation.py docs/plans/2026-08-27-mvp-roadmap.md docs/specs/2026-08-27-mvp-design.md README.md
git commit -m "docs: 단계 3 마무리 (실호출 스모크, 로드맵과 설계서 정합 기록)"
```

---

## 완료 기준

1. `backend` 전체 테스트 스위트 PASS (실호출 없이)
2. 스모크 스크립트로 실제 구조안과 장 1개 생성 성공 (구독 호출, 게이트 통과)
3. openapi.json과 types.ts가 라이브 스키마와 동기화 (test_openapi 통과)
4. 로드맵의 이월표와 리스크 문단이 실제 처리 결과와 일치
5. 브랜치 최종 리뷰 후 main 머지 (superpowers:finishing-a-development-branch)
