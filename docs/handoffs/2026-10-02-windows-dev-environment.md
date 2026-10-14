# Windows 개발 환경 기준선과 재개 준비

작성: 2026-10-02 (서울 기준). 사용자가 회사 PC(Windows)에서 개정판 개발을 이어갈 수 있도록 환경 준비를 요청했다. 이번 작업은 개발 기능을 추가하지 않았다. 최신 개발선 정리, 의존성 설치, 테스트 기준선 확보, 원격 CI 실패의 원인 수정까지 수행했다. 개정판의 기능 상태와 다음 단위는 [D1 인계](2026-10-02-desktop-d1.md)와 [개정 계획](../plans/2026-10-02-windows-feedback-revision.md)이 진본이다.

## 브랜치와 보존 사항

- 작업 브랜치는 `feat/windows-feedback-revision`이다. 원격 `6cd5a1c`(D1 독립 앱 기반) 위에 이번 커밋을 올렸다. `main`은 `4f6a03a`(0.2.0)이며 이 브랜치의 조상이다.
- 이 PC의 이전 로컬 브랜치 `codex/windows-powerpoint-qa-20261002`(`8561b4e`)에 있던 미커밋 Windows 테스트 보정 5개 파일, QA 결과 문서와 로드맵 기록을 이 브랜치로 옮겨 커밋했다. 로드맵의 같은 위치에서 생긴 충돌은 양쪽 기록을 모두 남겨 해소했다. 옮기기 전 원본은 저장소 밖 `Documents/slidecaptain-backups/2026-10-02-windows-qa-uncommitted/`에 보존했다.
- `feedback/`의 사용자 피드백 원문은 회사 자료를 포함하므로 커밋하지 않았다. 루트의 과거 핸드오프와 오피스 파일은 `.gitignore` 대상이며 그대로 둔다.

## 원격 CI 실패 수정

`6cd5a1c`의 CI(run 36977946509)는 Windows와 macOS 모두 독립 서비스 패키징과 smoke 검사 단계에서 `Draft export contract`로 실패했다. 원인은 제품이 아니라 smoke 스크립트의 경로 비교였다. 백엔드 exporter는 `resolve(strict=True)`로 실제 경로를 반환하는데, `desktop/scripts/smoke-service.cjs`는 `os.tmpdir()` 경로를 그대로 데이터 폴더로 써서 경로 별칭이 있는 환경에서 `startsWith` 비교가 실패했다. Windows 러너의 임시 폴더는 8.3 짧은 이름(`RUNNER~1`)이고 macOS는 `/var`가 `/private/var`의 링크다. Linux의 `/tmp`는 별칭이 없어 통과했다.

- 이 PC에서 junction과 8.3 짧은 경로를 임시 폴더로 지정해 개발 서비스와 PyInstaller로 만든 frozen 서비스 모두에서 같은 실패를 재현했다. 실제 경로를 지정하면 통과했다.
- 수정은 임시 폴더를 `fs.realpath`로 실제 경로로 바꾼 한 곳이다. 데이터 폴더 포함 여부 검사, 일반 파일 검사, `final_export_allowed` 검사는 그대로다. `scripts/smoke_release.py`도 같은 방식으로 데이터 폴더를 `resolve()`한다.
- 수정 후 개발 서비스와 frozen 서비스 모두 실제 경로, junction, 8.3 경로에서 통과했다. desktop 테스트는 19건 통과했다. macOS 실행은 이 PC에서 확인하지 않았으며, 같은 원리로 해소된다고 추론했다. 푸시 후 CI 결과로 확인한다.
- 계획했던 독립 검토 2건은 사용자 결정으로 이번 작업에서 실행하지 않았다.

## Windows 기준선 (이 PC, 2026-10-02)

환경: Windows 11 22631, Python 3.13.5(`backend/.venv`, `backend[dev,desktop]` editable 설치), Node 22.17.1 x64. 실제 AI 호출은 0회다.

| 검사 | 명령 | 결과 |
| --- | --- | --- |
| 백엔드 전체 | `backend`에서 `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests -q` | 1,992 통과 / 24 건너뜀 / 실패 0 |
| 백엔드 전체 (UTF-8 모드 없이) | 위 명령에서 `PYTHONUTF8=1` 제외 | 1,936 통과 / 56 실패 / 24 건너뜀. 실패는 모두 cp949 `UnicodeDecodeError` |
| 프런트 전체 | `frontend`에서 `npx vitest run --maxWorkers=4` | 550 통과 / 53파일 |
| 프런트 전체 (기본 `npm test`) | `frontend`에서 `npm test` | 두 번 실행해 1건, 6건이 5초 제한 시간 초과로 실패. 단언 실패는 없고 해당 파일 단독 재실행은 모두 통과 |
| 화면 빌드 | `npm run build` (`tsc --noEmit` 포함) | 통과 |
| OpenAPI와 타입 동기화 | `dump_openapi.py` 후 `npm run generate-types` | 생성 파일 변경 없음 |
| desktop 경로 대조 | `scripts/check_desktop_routes.py` | 38개 경로 일치 |
| desktop 테스트 | `desktop`에서 `npm test` | 19 통과 |
| 공개 저장소 감사 | `scripts/audit_public_repo.py` | 발견 0건 |

건너뜀 24건은 심볼릭 링크 생성 권한 부족(WinError 1314) 12건, Windows가 거부하는 POSIX 전용 이름 변경 시나리오 7건, 사용 중인 디렉터리 이름 고정 3건, 링크 불가 기기 1건, macOS 전용 NFD/NFC 1건이다.

## 이 PC에서 알아둘 환경 차이

1. **한국어 Windows 인코딩**: 일부 테스트가 `Path.read_text()`를 인코딩 없이 호출해 cp949로 UTF-8 파일을 읽는다. 로컬에서는 `PYTHONUTF8=1`로 실행한다. 제품 코드의 쓰기는 UTF-8을 지정하므로 제품 결함은 확인되지 않았다.
2. **경로 길이**: 이 PC는 `LongPathsEnabled=0`이다. pytest `--basetemp`를 깊은 경로로 지정하면 렌더 이미지 경로가 260자를 넘어 `test_export_qualification.py` 등 23건이 실패한다. 기본 pytest 임시 폴더를 쓴다.
3. **프런트 테스트 부하**: 16코어 기본 병렬 실행에서 jsdom 테스트 일부가 5초를 넘는다. 저장소에 `testTimeout` 설정은 없다.
4. **심볼릭 링크 권한**: 이 계정에는 링크 생성 권한이 없어 관련 검사는 건너뛴다. CI와 권한 있는 기기에서는 검사가 유지된다.

## 후속 후보 (이번 작업에서 수정하지 않음)

- 테스트의 `read_text()`에 `encoding="utf-8"` 지정: Windows 로컬 결과를 CI와 일치시킨다.
- 프런트 `testTimeout` 상향 또는 worker 상한 검토.
- `desktop/builder.cjs`의 출력 폴더 검사도 경로 문자열을 그대로 비교한다. 8.3 이름, junction, 대소문자 차이로 체크아웃 안의 폴더가 바깥으로 판정될 수 있다. CI에는 영향이 없다.
- 기존 Windows QA 발견(차트 정수의 끝 소수점 표시, bar/column 합성 입력의 `unlinked_expression`)은 [Windows PowerPoint 결과](../qa/2026-10-02-windows-powerpoint-results.md)를 따른다.

## 다음 세션 시작 방법

1. `git pull`로 이 브랜치를 받고 CI 결과를 확인한다.
2. 의존성이 바뀌었으면 `backend/.venv/Scripts/python.exe -m pip install -e "backend[dev,desktop]"`, `frontend`와 `desktop`에서 `npm ci`를 실행한다.
3. 다음 개발 단위는 [D1 인계](2026-10-02-desktop-d1.md)의 남은 관문과 [첫 단위 인계](2026-10-02-windows-feedback-first-batch.md)의 순서를 따른다. 이 PC가 필요한 관문은 Windows 독립 앱 빌드와 실행, 자식 프로세스 정리, 프로필별 실제 로그인과 두 계정 전환, PowerPoint에서 사람이 직접 수정하고 저장하는 검수다.
