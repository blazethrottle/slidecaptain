"""자료 파일 업로드 API (원시 바이트 본문) 테스트. 계획서 2026-09-01 태스크 2, 2026-09-04 B2로 XLSX 확장."""

import threading
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import slidecaptain.server.app as app_module
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.server.app import create_app
from slidecaptain.sources.xlsx import extract_xlsx
from slidecaptain.storage.file_store import FileProjectStore

# store 픽스처는 backend/tests/conftest.py 참조. client는 프로젝트 p1을 미리 만드는 이 파일만의
# 확장이라 conftest의 것을 그대로 쓰지 않는다 (A2에서 기본 헤더 X-Requested-With만 conftest와 통일).


@pytest.fixture
def client(store):
    c = TestClient(create_app(store), headers={"X-Requested-With": "SlideCaptain"})
    assert c.post("/api/projects", json={"name": "p1", "title": "검토"}).status_code in (200, 201)
    return c


def _upload(client, filename: str, data: bytes, overwrite: bool = False):
    return client.post(
        f"/api/projects/p1/sources/{filename}/upload",
        params={"overwrite": str(overwrite).lower()},
        content=data,
        headers={"X-Requested-With": "SlideCaptain"},
    )


def _make_xlsx(sheet_name: str, cells: dict[str, object]) -> bytes:
    """B1 픽스처와 같은 방법(순수 openpyxl 저장)으로 API 계층 테스트용 XLSX 바이트를 만든다.
    <v> 사후 치환 같은 정밀 검증은 B1의 test_xlsx_extract.py 몫이라 여기서는 필요 없다."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for coord, value in cells.items():
        ws[coord] = value
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_without_app_header_is_rejected(client, store):
    # 다른 사이트의 페이지가 보내는 text/plain POST(사전 확인 없는 단순 요청)를 막는다 (2026-09-01 최종 리뷰
    # 반영. 2026-09-04 A2에서 이 검사가 공통 미들웨어로 옮겨가며 상태 코드가 400에서 403으로 바뀌었다).
    # client 픽스처는 이제 기본 헤더가 붙으므로, 헤더를 아예 안 보내는 클라이언트를 따로 만든다
    bare = TestClient(create_app(store))
    r = bare.post(
        "/api/projects/p1/sources/주입.md/upload",
        params={"overwrite": "true"},
        content=b"injected",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 403
    assert "Slide Captain 화면에서만" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_utf8_text_round_trip(client):
    text = "시장 규모는 500억 원이다"
    r = _upload(client, "리서치.md", text.encode("utf-8"))
    assert r.status_code == 200
    # 텍스트 업로드의 엑셀 요약 필드는 None/False/빈 목록이다 (계획서 B2)
    assert r.json() == {
        "filename": "리서치.md", "chars": len(text),
        "sheets": None, "cells": None, "truncated": False, "notes": [],
    }
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
    # 계획서 B2: 일반 미지원 문구가 .xlsx 허용과 구버전 xls 언급을 포함하도록 갱신됐다
    r = _upload(client, "보고서.pdf", b"%PDF-1.4")
    assert r.status_code == 422
    assert "PDF와 Word, 구버전 xls는 아직 지원하지 않습니다" in r.json()["detail"]
    assert ".xlsx" in r.json()["detail"]
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


def test_upload_case_only_conflict_409_even_with_overwrite_true(client):
    # A4: overwrite=true는 정확히 같은 이름에만 적용된다. 대소문자만 다른 이름은 overwrite로도
    # 우회할 수 없다 (write_source의 casefold 검사가 overwrite 플래그와 무관하게 걸린다)
    assert _upload(client, "report.md", b"v1").status_code == 200
    r = _upload(client, "Report.md", b"v2", overwrite=True)
    assert r.status_code == 409
    assert "report.md" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources/report.md").json()["text"] == "v1"
    assert client.get("/api/projects/p1/sources").json() == ["report.md"]


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
    r = c.post("/api/projects/없음/sources/a.md/upload", content=b"x", headers={"X-Requested-With": "SlideCaptain"})
    assert r.status_code == 404


def test_concurrent_upload_same_new_name_only_one_succeeds(client):
    # source_exists 확인과 write_source가 잠금 밖에서 쪼개져 있으면 같은 새 이름의 두 업로드가
    # 둘 다 확인을 통과할 수 있다 (적대 리뷰 재현). A2가 store.locked(name) 안에서 묶는다
    results: list[int] = []
    results_lock = threading.Lock()

    def worker(data: bytes) -> None:
        r = _upload(client, "동시.md", data)
        with results_lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(b"v1",)), threading.Thread(target=worker, args=(b"v2",))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [200, 409]
    assert client.get("/api/projects/p1/sources").json() == ["동시.md"]


# -- XLSX 업로드 (계획서 2026-09-04 태스크 B2) -------------------------------------------------


def test_upload_xlsx_saves_original_and_extract_separately(client, tmp_path):
    data = _make_xlsx("매출", {"A1": "제품", "B1": "노트북"})
    expected = extract_xlsx(data, "매출.xlsx")
    r = _upload(client, "매출.xlsx", data)
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "매출.xlsx"
    assert body["chars"] == len(expected.text)
    assert body["sheets"] == expected.sheets
    assert body["cells"] == expected.cells
    assert body["truncated"] == expected.truncated
    assert body["notes"] == expected.notes
    # 원본은 uploads/에 바이트 그대로, 추출본은 sources/에 UTF-8 텍스트로 (설계서 3.1, 가정 1)
    raw = (tmp_path / "projects" / "p1" / "uploads" / "매출.xlsx").read_bytes()
    assert raw == data
    extract_text = (tmp_path / "projects" / "p1" / "sources" / "매출.xlsx.md").read_text(encoding="utf-8")
    assert extract_text == expected.text
    # AI 입력(list_sources)에는 추출본만 보이고 원본은 나타나지 않는다
    assert client.get("/api/projects/p1/sources").json() == ["매출.xlsx.md"]


def test_upload_xlsx_duplicate_409_then_overwrite(client):
    data1 = _make_xlsx("시트1", {"A1": "v1"})
    data2 = _make_xlsx("시트1", {"A1": "v2", "A2": "v2b"})
    assert _upload(client, "표.xlsx", data1).status_code == 200
    r = _upload(client, "표.xlsx", data2)
    assert r.status_code == 409
    assert "같은 이름의 자료가 이미 있습니다" in r.json()["detail"]
    assert _upload(client, "표.xlsx", data2, overwrite=True).status_code == 200
    body = client.get("/api/projects/p1/sources/표.xlsx.md").json()
    assert "v2b" in body["text"]


def test_upload_xlsx_case_only_conflict_409_even_with_overwrite_true(client):
    data = _make_xlsx("s", {"A1": "x"})
    assert _upload(client, "report.xlsx", data).status_code == 200
    r = _upload(client, "Report.xlsx", data, overwrite=True)
    assert r.status_code == 409
    assert "report.xlsx" in r.json()["detail"]
    # 대소문자 충돌로 거절됐으므로 원본도 추출본도 새로 생기지 않는다
    assert client.get("/api/projects/p1/sources").json() == ["report.xlsx.md"]


def test_upload_xlsx_name_78_chars_rejected_before_extraction(client):
    # 추출본 이름(<원본>.md)이 80자를 넘는 경계: 원본이 78자 이상이면 넘친다 (계획서 B2)
    long_name = "a" * 73 + ".xlsx"
    assert len(long_name) == 78
    data = _make_xlsx("s", {"A1": "x"})
    r = _upload(client, long_name, data)
    assert r.status_code == 422
    assert "너무 깁니다" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_xlsx_name_77_chars_accepted(client):
    # 위 78자 거절의 경계 반대쪽: 77자는 추출본이 정확히 80자라 통과한다
    short_name = "a" * 72 + ".xlsx"
    assert len(short_name) == 77
    data = _make_xlsx("s", {"A1": "x"})
    r = _upload(client, short_name, data)
    assert r.status_code == 200


def test_upload_xlsx_size_limit_defaults_to_20mb():
    # 상수 값 자체를 고정한다: 텍스트(5MB)보다 크고 실측 근거(계획서 가정 4)와 일치해야 한다
    assert app_module._XLSX_UPLOAD_MAX_BYTES == 20 * 1024 * 1024


def test_upload_xlsx_within_patched_limit_passes_but_over_limit_is_422(client, monkeypatch):
    # 실제 20MB 파일을 만드는 대신 상한 상수를 파일 크기에 맞춰 조여, 검사 로직 자체(초과 여부
    # 비교)가 XLSX 전용 상수를 쓰는지 확인한다 (계획서 B2: XLSX는 텍스트의 5MB와 다른 20MB 상한)
    data = _make_xlsx("s", {"A1": "x" * 200})
    size = len(data)
    monkeypatch.setattr(app_module, "_XLSX_UPLOAD_MAX_BYTES", size)
    assert _upload(client, "안팎.xlsx", data).status_code == 200
    monkeypatch.setattr(app_module, "_XLSX_UPLOAD_MAX_BYTES", size - 1)
    r = _upload(client, "초과.xlsx", data)
    assert r.status_code == 422
    assert "엑셀 파일이 너무 큽니다" in r.json()["detail"]


def test_upload_xls_unsupported_422(client):
    r = _upload(client, "옛문서.xls", b"\xd0\xcf\x11\xe0")
    assert r.status_code == 422
    assert "구버전 엑셀(xls)은 지원하지 않습니다" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_corrupted_xlsx_422_korean(client):
    r = _upload(client, "손상.xlsx", "zip이 아닌 무작위 바이트".encode("utf-8"))
    assert r.status_code == 422
    assert "읽지 못했습니다" in r.json()["detail"]
    assert client.get("/api/projects/p1/sources").json() == []


def test_upload_xlsx_rolls_back_upload_if_extract_write_fails(client, tmp_path, monkeypatch):
    def _boom(self, name, filename, text):
        raise RuntimeError("디스크 꽉 참(가짜 실패)")

    monkeypatch.setattr(FileProjectStore, "write_source", _boom)
    data = _make_xlsx("s", {"A1": "x"})
    with pytest.raises(RuntimeError):
        _upload(client, "실패.xlsx", data)
    # 추출본 쓰기가 실패했으니 원본만 uploads/에 남으면 안 된다 (계획서 B2)
    assert not (tmp_path / "projects" / "p1" / "uploads" / "실패.xlsx").exists()


def test_generated_route_reads_xlsx_extract_as_source(client, store):
    # 생성 라우트가 기존 _load_sources 경로로 추출본을 읽어 프롬프트에 넣는다 (계획서 B2 테스트 항목)
    data = _make_xlsx("매출현황", {"A1": "제품", "B1": "노트북"})
    assert _upload(client, "매출.xlsx", data).status_code == 200

    class _CapturingProvider:
        def __init__(self):
            self.prompts: list[str] = []

        async def complete(self, prompt, schema):
            self.prompts.append(prompt)
            return ProviderResponse(structured={"chapters": []}, raw_text="r")

    provider = _CapturingProvider()
    gen_client = TestClient(
        create_app(store, provider=provider), headers={"X-Requested-With": "SlideCaptain"}
    )
    gr = gen_client.post("/api/projects/p1/generate/structure", json={})
    assert gr.status_code == 200
    assert provider.prompts
    assert "매출현황" in provider.prompts[0]
