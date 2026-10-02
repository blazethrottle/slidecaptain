# 0.2.0 로컬 릴리스 검증

2026-10-02. 사용자 승인 범위는 개인용 Windows·Mac 로컬 앱 개발 마무리, main 반영과 GitHub 릴리스다. 서비스에 치명적이지 않은 품질/지원 범위 부족은 [후속 항목](../releases/0.2.0.md)으로 남긴다. 실제 AI 호출은 0회다.

## 로컬 검사

- 백엔드 전체: 1,988 통과 / Windows 전용 2 미실행. 이후 설치기 플랫폼 선택 회귀 3개를 추가해 관련 설치/패키지/CLI 32개를 재검증했다.
- 프런트엔드: 52파일 / 532 통과, Node 22.17.1에서 TypeScript/Vite 빌드 성공.
- OpenAPI와 생성 타입은 0.2.0 버전 및 `/api/health`를 반영해 재생성했다. 버전 갱신 직후 생긴 옛 editable metadata와 OpenAPI 불일치는 재설치/재생성으로 해소했다.
- 공개 저장소 파일·이력 감사와 Git diff 검사를 수행했다. release builder는 Git 인덱스에 등록된 백엔드 파일과 빌드된 UI만 wheel에 넣고, 프로젝트·인증정보·회사 자료를 포함하지 않는다.
- 독립 리뷰: 저장 ETag·스냅샷·보호 문서 변경·Windows 핸들·게시 잠금·배포 경계를 집중 대조했고 104개 회귀가 통과했다. 새 설치기 플랫폼 회귀 16개도 재검토했다. 필수 잔여 발견은 0건이며 실제 패키지 실행 검증을 별도로 수행했다.

## 설치된 배포본 관통

wheel과 ZIP을 저장소 밖에서 만들고 새 폴더에 압축 해제했다. release launcher의 최초 설치로 별도 가상환경을 만든 뒤 고정 runtime 의존성 41종과 wheel을 설치했다. `pip check`가 통과했다. Node.js나 editable 소스 설치에 의존하지 않는 패키지 실행이다.

macOS의 uv 관리 Python에서 복사 방식 가상환경이 `libpython`을 찾지 못하는 실제 결함을 발견했다. POSIX는 symlink, Windows는 copy로 바꾸고 새 폴더 설치를 재검증했다. 이어 smoke 스크립트의 `python.resolve()`가 symlink를 base Python까지 따라가던 문제를 `absolute()`로 고쳤다. 덱 재열기 비교는 모델이 채우는 기본값을 고려해 장 ID·개수·제목 보존을 검사한다.

설치된 Python에서 별도 서버와 임시 프로젝트를 실행해 다음을 확인했다.

- health의 제품·버전·화면 준비 상태, 실제 HTML과 CSS/JS 정적 파일 2개.
- 프로젝트 생성, ETag 기반 덱 저장과 재열기, 스냅샷 조회.
- 편집 가능한 PPTX 초안 생성, OOXML slide1 존재, 내보내기 이력 조회.
- 초안의 `final_export_allowed=false` 유지. AI·로그인 검사 호출 없이 실행.
- 검사 프로세스만 종료하며 사용자 자료·인증·기존 서버를 변경하지 않음.

## 원격 릴리스 관문

CI는 Windows·macOS 각각 공개 감사, 전체 백엔드/프런트 검사, 생성 타입 무변경, 화면 빌드, ZIP 생성, 새 가상환경 설치, 설치된 패키지의 HTTP 관통을 실행한다. 통과한 출시 커밋만 main과 릴리스 태그에 반영한다. ZIP의 manifest는 source commit과 wheel/requirements SHA-256을 연결한다. 배포 파일 SHA-256은 GitHub 릴리스 자산의 `SHA256SUMS.txt`로 제공한다.

실제 PowerPoint 전체 페이지 표시·편집·렌더, 독립 서명과 사람 품질 수용은 확인된 보고가 없으므로 미확인으로 유지한다. GitHub의 양 OS 설치 CI는 이 항목을 대신하지 않는다. 이번 출시는 앱 배포이며 각 보고서의 제출 승인 관문은 유지한다.
