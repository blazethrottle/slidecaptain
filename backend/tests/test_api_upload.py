"""자료 파일 업로드 API (원시 바이트 본문) 테스트. 계획서 2026-09-01 태스크 2."""

import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


@pytest.fixture
def client(store):
    c = TestClient(create_app(store))
    assert c.post("/api/projects", json={"name": "p1", "title": "검토"}).status_code in (200, 201)
    return c


def _upload(client, filename: str, data: bytes, overwrite: bool = False):
    return client.post(
        f"/api/projects/p1/sources/{filename}/upload",
        params={"overwrite": str(overwrite).lower()},
        content=data,
    )


def test_upload_utf8_text_round_trip(client):
    text = "시장 규모는 500억 원이다"
    r = _upload(client, "리서치.md", text.encode("utf-8"))
    assert r.status_code == 200
    assert r.json() == {"filename": "리서치.md", "chars": len(text)}
    assert client.get("/api/projects/p1/sources").json() == ["리서치.md"]
    assert client.get("/api/projects/p1/sources/리서치.md").json()["text"] == text


def test_upload_cp949_is_decoded_and_stored_as_utf8(client, tmp_path):
    r = _upload(client, "메모장.txt", "한글 메모".encode("cp949"))
    assert r.status_code == 200
    assert client.get("/api/projects/p1/sources/메모장.txt").json()["text"] == "한글 메모"
    # 저장 시점에 UTF-8로 정규화된다
    raw = (tmp_path / "projects" / "p1" / "sources" / "메모장.txt").read_bytes()
    assert raw.decode("utf-8") == "한글 메모"


def test_upload_utf8_bom_is_absorbed(client):
    r = _upload(client, "bom.txt", "﻿본문".encode("utf-8"))
    assert r.status_code == 200
    assert client.get("/api/projects/p1/sources/bom.txt").json()["text"] == "본문"


def test_upload_unsupported_extension_422(client):
    r = _upload(client, "보고서.pdf", b"%PDF-1.4")
    assert r.status_code == 422
    assert "PDF와 Word는 아직 지원하지 않습니다" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_uppercase_extension_accepted(client):
    r = _upload(client, "NOTES.MD", b"abc")
    assert r.status_code == 200
    assert client.get("/api/projects/p1/sources").json() == ["NOTES.MD"]


def test_upload_too_large_422(client):
    r = _upload(client, "big.txt", b"a" * (5 * 1024 * 1024 + 1))
    assert r.status_code == 422
    assert "너무 큽니다" in r.json()["detail"]


def test_upload_duplicate_409_then_overwrite(client):
    assert _upload(client, "a.md", b"v1").status_code == 200
    r = _upload(client, "a.md", b"v2")
    assert r.status_code == 409
    assert "같은 이름의 자료가 이미 있습니다" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources/a.md").json()["text"] == "v1"
    assert _upload(client, "a.md", b"v2", overwrite=True).status_code == 200
    assert client.get("/api/projects/p1/sources/a.md").json()["text"] == "v2"


def test_upload_invalid_name_422(client):
    # 이름 규칙: 첫 글자가 한글, 영문, 숫자여야 한다 (설계서 3.1)
    r = _upload(client, "..md", b"x")
    assert r.status_code == 422
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_strips_windows_path_prefix(client):
    # PureWindowsPath를 쓰므로 실행 OS와 무관하게 역슬래시도 분리자로 처리된다
    r = _upload(client, "sub%5Cx.md", b"x")
    assert r.status_code == 200
    assert r.json()["filename"] == "x.md"
    assert client.get("/api/projects/p1/sources").json() == ["x.md"]


def test_upload_binary_garbage_422(client):
    r = _upload(client, "이미지.txt", bytes([0xFF, 0xFE, 0x00, 0x81, 0xC0, 0xC1, 0xF5, 0xFF]))
    assert r.status_code == 422
    assert "텍스트로 읽지 못했습니다" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_crlf_is_normalized_like_read_text(client, tmp_path):
    # read_text()의 universal newline과 같은 동작: CRLF 파일을 올려도 \r이 남지 않는다 (2026-09-01 리뷰 반영)
    r = _upload(client, "메모장CRLF.txt", "첫 줄\r\n둘째 줄\r셋째 줄".encode("utf-8"))
    assert r.status_code == 200
    assert r.json()["chars"] == len("첫 줄\n둘째 줄\n셋째 줄")
    assert client.get("/api/projects/p1/sources/메모장CRLF.txt").json()["text"] == "첫 줄\n둘째 줄\n셋째 줄"
    # 탐색기로 넣은 CRLF 파일을 읽는 기존 경로도 같다
    (tmp_path / "projects" / "p1" / "sources" / "외부.md").write_bytes(b"a\r\nb")
    assert client.get("/api/projects/p1/sources/외부.md").json()["text"] == "a\nb"


def test_upload_empty_file_ok(client):
    r = _upload(client, "빈파일.txt", b"")
    assert r.status_code == 200
    assert r.json()["chars"] == 0


def test_upload_missing_project_404(store):
    c = TestClient(create_app(store))
    r = c.post("/api/projects/없음/sources/a.md/upload", content=b"x")
    assert r.status_code == 404
