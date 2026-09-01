"""GET /api/status 테스트 (계획서 2026-09-01 태스크 4). 로그인 확인은 가짜 checker로 대체한다."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.auth_status import LoginStatus
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

LOGGED_IN = LoginStatus(logged_in=True, auth_method="claude.ai", account="co***@example.com")


class StubProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    async def complete(self, prompt, schema):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class StubProviderWithModel(StubProvider):
    model = "sonnet"


def _checker(status: LoginStatus):
    calls: list[int] = []

    def check() -> LoginStatus:
        calls.append(1)
        return status

    check.calls = calls  # type: ignore[attr-defined]
    return check


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _project_with_structure(client):
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"] = {"chapters": [
        {"id": "c1", "topic": "시장 현황", "conclusion": "성장", "template": "bullet_box",
         "source_refs": ["리서치.md"]},
    ]}
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_status_reports_login_provider_and_no_generation_yet(store):
    checker = _checker(LOGGED_IN)
    client = TestClient(create_app(store, provider=StubProvider([]), login_checker=checker))
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "subscription"
    assert body["login"] == {
        "logged_in": True, "auth_method": "claude.ai", "account": "co***@example.com",
        "cli_version": None, "error": None,
    }
    assert body["model"] is None  # StubProvider에는 model 속성이 없다
    assert body["last_generation_at"] is None
    datetime.fromisoformat(body["checked_at"])


def test_status_exposes_provider_model_when_present(store):
    client = TestClient(create_app(store, provider=StubProviderWithModel([]), login_checker=_checker(LOGGED_IN)))
    assert client.get("/api/status").json()["model"] == "sonnet"


def test_status_without_provider(store):
    client = TestClient(create_app(store, login_checker=_checker(LOGGED_IN)))
    body = client.get("/api/status").json()
    assert body["provider"] == "none"
    assert body["model"] is None


def test_status_caches_login_check(store):
    checker = _checker(LOGGED_IN)
    client = TestClient(create_app(store, provider=StubProvider([]), login_checker=checker))
    client.get("/api/status")
    client.get("/api/status")
    assert len(checker.calls) == 1


def test_status_records_last_success_after_structure_generation(store):
    client = TestClient(create_app(
        store, provider=StubProvider([ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")]),
        login_checker=_checker(LOGGED_IN),
    ))
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    assert client.post("/api/projects/p1/generate/structure", json={"target_chapters": 2}).json()["status"] == "ok"
    at = client.get("/api/status").json()["last_generation_at"]
    assert at is not None
    datetime.fromisoformat(at)


def test_status_records_last_success_after_condense(store):
    client = TestClient(create_app(
        store, provider=StubProvider([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")]),
        login_checker=_checker(LOGGED_IN),
    ))
    _project_with_structure(client)
    body = {"slots": {"template": "bullet_box",
                      "bullets": [{"text": "현재 내용이 다소 길다", "level": 0}],
                      "conclusion": "성장 지속", "footnote": ""}}
    assert client.post("/api/projects/p1/generate/chapter/c1/condense", json=body).status_code == 200
    assert client.get("/api/status").json()["last_generation_at"] is not None


def test_status_records_last_success_after_chapter_generation(store):
    client = TestClient(create_app(
        store, provider=StubProvider([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")]),
        login_checker=_checker(LOGGED_IN),
    ))
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={"instructions": ""})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert client.get("/api/status").json()["last_generation_at"] is not None


def test_status_survives_checker_exception(store):
    def broken() -> LoginStatus:
        raise RuntimeError("checker 고장")
    client = TestClient(create_app(store, provider=StubProvider([]), login_checker=broken))
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json()["login"]["logged_in"] is None
    assert "checker 고장" in r.json()["login"]["error"]


def test_status_not_updated_when_generation_fails(store):
    client = TestClient(create_app(
        store, provider=StubProvider([ProviderCallFailed("호출 실패")]), login_checker=_checker(LOGGED_IN),
    ))
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 2})
    assert r.status_code == 503
    assert client.get("/api/status").json()["last_generation_at"] is None
