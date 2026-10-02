# Q3a 인계: 독립 도식 계약과 근거 참조

작성: 2026-09-13. 사용자 요청: "slide captain 프로젝트 계속". 직전 [Q1b 세 번째 단위 인계](2026-09-13-q1b3-export-history-handoff.md)의 다음 후보를 [단위 계획](../plans/2026-09-13-q3a-diagram-contract.md)으로 한정해 구현했다.

## 종료 지점과 승인 범위

의미적 노드, 관계, 라벨과 기존 Evidence ID를 파싱/검증하는 Q3a 첫 단위를 완료했다. 기존 Deck/StoryPlan/QualityReport, 저장 버전, API/생성/프런트 계약을 변경하지 않았다. 앱에서 도식을 생성하거나 보여주는 기능은 아직 없다. 이 인계에서 멈추며 배치와 렌더를 같은 단위에 묶지 않는다.

원본 브랜치는 `codex/phase-5b`, HEAD는 `a8c6d7a`다. 기존 누적 미커밋 변경을 별도로 백업하고 detached 작업 트리에서 구현/검증했다. 커밋/pull/push/merge/배포와 실제 AI 호출은 하지 않았다. 기존 서버와 사용자 프로젝트도 변경하지 않았다.

## 실제 계약

- `backend/slidecaptain/models/diagram.py`: `DiagramSpec(q3a-v1)`과 `parse_diagram_spec(payload, evidence=...)`를 추가했다. 입력은 dict/JSON/모델 인스턴스이며 기존 Evidence 장부를 반드시 제공한다.
- canvas는 기존 Preset 크기 참조와 report 프로필, 배치 이름은 flow_horizontal만 받는다. 이는 후속 계산을 위한 이름이며 실제 좌표를 계산하지 않는다.
- 노드 2~12개, 관계 1~24개, 내용 500자/라벨 120자를 상한으로 둔다. 사실 노드와 flow/reference 관계에는 자기 근거가 필요하고, proposal은 명시적 제안이다. 추정/미확인 노드에는 조건을 남긴다.
- 중복 ID/관계/JSON 키, 끊긴 노드/근거 참조, 자기 연결, 순환 flow와 미지원 관계 타입을 거절한다. comparison은 Q2b 비교 조건에 연결할 때까지 미지원이다. reference/proposal에는 순서나 인과를 부여하지 않는다.
- 좌표/크기/앵커/스타일/HTML/SVG/script 전용 필드와 품질 결과를 입력받지 않는다. 일반 content/label은 실행하지 않는 평문이며 이후 렌더 연결도 이 경계를 유지해야 한다.
- 반환 객체의 후속 편집은 다시 파싱해야 한다. 중첩 Diagram 모델은 직접 재검증하고 Evidence는 원래 필드를 보존해 재검증한다. 검증 우회 인스턴스의 추가 필드도 버리지 않고 거절한다.

원문 위치/해시 형식과 근거 ID 존재는 검사하지만 파일의 현재성, 발췌의 실제 일치, 관계의 진실성과 자유 문장의 인과 의미는 검사하지 않는다. fixture의 원문/해시 대조 통과를 임의 입력에 대한 보증으로 확대하지 않는다.

## 검증 결과

| 대상 | 관측 결과 |
|---|---|
| Q3a 계약 | 100개 중 실패 0개 |
| 백엔드 전체 | 1,359개 중 1,358개 통과, Windows 전용 1개 미실행, 실패 0개 |
| 프런트 전체 | 30개 파일의 312개 중 실패 0개 |
| 타입/빌드 | OpenAPI/TypeScript 생성 파일 2개가 시작본과 바이트 동일, tsc/Vite 빌드 통과 |
| 실제 저장 왕복 | 레거시/q2a/q2b/q2c 4개 중 차이 0개, 도식 파싱으로 저장 파일 변경 0개, 계획 3종의 fingerprint 유지 |
| 독립 계획/구현 리뷰 | 인과 의미 범위 정정과 파서의 필드 손실 결함 반영, 재검토에서 추가 필수 수정 없음 |
| 순환 판정 독립 대조 | 검토자가 4개 노드 방향 그래프 4,096종을 대조해 불일치 0건으로 보고 |
| 공개 저장소 감사 | 원본의 추적/미추적 일반 파일 239개 중 경로/내용 규칙 발견 0개 |
| 실제 AI/도식 화면/PowerPoint/독자 품질 | 대상 0건, 미검증 |

최초 새 모듈 부재는 수집 오류 1건이었다. 독립 구현 리뷰가 발견한 model_dump의 미정의 필드 손실은 root/중첩 Diagram과 Evidence/locator에서 8개 실패 사례로 재현했다. 수정 후 모두 통과했고 별도 검토자가 추가 필드 거절, 정상 왕복, 입력 보존과 순환 객체 거절을 다시 확인했다. 이번 리뷰를 과거 Q1/Q2나 누적 브랜치 전체의 독립 검수로 소급하지 않는다.

검사는 격리 작업 트리의 backend를 PYTHONPATH로 지정해 원본 가상환경으로 실행했다. 마지막 코드 수정 뒤 백엔드 전체를 재실행했으며 프런트에는 변경이 없어 성공한 전체 검사/빌드를 반복하지 않았다.

## 보존과 작업 파일

원본 파일 234개를 백업했다. 원본의 시작 해시를 대조한 뒤 기존 상태 문서 6개를 갱신하고 모델/검사/fixture/계획/인계 5개를 추가했다. 기존 228개 파일은 바이트 동일하며 삭제는 0개다. 기존 코드와 생성 타입, 빈 스테이징을 보존했다. 원본 경로에서 새 모듈이 로드되는 것과 fixture 파싱도 확인했다.

백업과 검증 로그는 저장소 밖 macOS 임시 폴더의 `slidecaptain-q3a-mw44iryz/`에 있다. `baseline/`, `baseline.json`, `initial-index.patch`, `review-red.log`, `backend-tests-final.log`, `frontend-tests.log`, `frontend-build.log`, `compatibility-check.json`, `applied-preservation.json`, `final-verification.json`을 남겼다. detached 작업 트리도 이 폴더의 `work/`에 보존한다. 임시 폴더는 영구 보관소가 아니며 프로젝트의 지속 인계는 이 문서다.

새 코드/검사/fixture와 기존 문서 변경은 다음과 같다.

- `backend/slidecaptain/models/diagram.py`
- `backend/tests/test_diagram_contract.py`, `backend/tests/fixtures/q3a-diagram.json`
- 단위 계획/이 인계, 도입안, 로드맵, 품질 개발 계획, 품질 아키텍처/제품 요구와 `CLAUDE.md`의 최신 인계 포인터

## 다음 행동과 재심 대상

다음 후보는 Q3b 결정론 배치의 첫 단위다. 현재 Preset/폰트와 검증된 DiagramSpec에서 최소 typed render 결과를 만드는 어댑터를 계획 리뷰로 확정한다. 같은 입력의 같은 좌표/크기/앵커, 관계/근거 보존, 페이지 밖 배치와 글자/라벨 용량의 실패 조건부터 검증한다. 프런트에서 배치를 재계산하지 않는다.

도입안의 페이지 밖 좌표 검사는 Q3a에서 좌표 입력 자체의 거절로 한정했다. 계산된 배치의 경계는 다음 단위이며 이 정정은 도입안/로드맵에도 반영했다. 입력 개수/문자열 상한은 화면 가독성이나 사용자 요구를 실측한 값이 아니므로 첫 배치와 실제 렌더에서 재심한다. 순환 흐름, comparison, 프로필 확대와 다른 레이아웃도 현재 버전의 미지원 범위다.

실제 원문/관계 의미, 렌더/검수 상태 저장과 도식 편집 시 품질 만료, 생성/UI/PPTX 연결은 미구현이다. Q1b Windows 네이티브/새 CI와 기존 Q2의 의미/요약 정합성 이월도 그대로 남아 있다.

## 위키 참조와 환경 관측

`wiki/projects/slidecaptain.md`는 과거 맥락만 참고했고 최신 상태는 현재 인계/구현으로 확인했다. `wiki/concepts/Editable-HTML-Diagram-Contract.md`의 의미/배치 분리와 관계 근거, 구조 통과의 품질 승격 금지를 적용했다. Codex 명시적 읽기 로그 2건을 확인했다. `pages_read=2`, `frames_applied=1`, `wiki_irrelevant_justified=0`, `reflux=0`이며 새 지식 저장 없이 프로젝트 기록으로 환류했다. 기존 도입안과 같은 결론이었으므로 규칙 대조 결과는 no_effect 1건으로 기존 측정 원장에 남겼다. 사용자 품질 판정은 작성하지 않았다.

세션 진입 때 요청된 환경 동기화로 wiki-use.md 설치 사본 2개가 갱신됐고 기존 설치 사본은 백업됐다. 새 앱 세션의 지침 읽기 검증은 수행하지 않았다. 위키 본문과 무관한 대기 큐는 수정하지 않았다.
