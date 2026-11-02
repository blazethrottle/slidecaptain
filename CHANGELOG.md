# Changelog

## 0.2.1 (준비, 2026-11-02)

v0.2.0 이후 main의 개정판을 배포 버전에 담고, 알려진 의존성 권고를 고친다. 상세와 남은 권고는 [docs/releases/0.2.1.md](docs/releases/0.2.1.md), 사용자 안내는 [docs/releases/revision-update-notes.md](docs/releases/revision-update-notes.md).

- Python 배포 잠금: pillow 12.3.0 → 13.0.0, pyjwt 2.13.0 → 2.15.1, mcp 2.1.1 → 2.3.0, opentelemetry-api 1.44.0 → 1.45.2.
- 프런트: vite 8.2.2 → 8.3.5, vitest 4.1.11 → 4.1.12, js-yaml, brace-expansion, source-map-js 패치.
- 독립 앱: electron 44.5.1 → 44.10.1, undici와 fast-uri 패치.
- CI에 Python `pip-audit`와 프런트, 독립 앱 `npm audit --audit-level=high` 잡을 추가.
- 앱 버전 0.2.1.

태그 생성과 GitHub 릴리스 게시는 이 변경에 포함하지 않는다.
