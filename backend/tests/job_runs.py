"""작업 API 시험 도우미 (개정판 D3c-7, 계획 4.9).

동기 생성 래퍼(등록하고 끝날 때까지 기다린 뒤 결과를 응답으로 돌려주던 라우트)를 지운 뒤, 시험은 작업 API로 생성을
등록하고 끝날 때까지 기다린 뒤 원장 행을 본다. 래퍼 단언이 작업 API의 어디로 가는지는 계획 4.9의 대응표를 따른다:
① 등록 검사(404, 409, 422, 428)는 등록 응답과 "행이 생기지 않음" ② 실행 중 실패는 종결 행의 state와 error
③ 생성 뒤 판정(래퍼의 412나 409)은 state succeeded, candidate_status stale, stale_reasons.
"""

import uuid
from dataclasses import dataclass


@dataclass
class Run:
    registration: object  # 등록 응답 (httpx.Response). 202는 새 작업, 200은 같은 요청 ID 병합, 그 밖은 거절
    view: dict | None  # 종결된 작업 행(GET /jobs/{id}). 등록이 거절되면 None

    @property
    def rejected(self) -> bool:
        return self.view is None

    @property
    def state(self) -> str | None:
        return None if self.view is None else self.view["state"]

    @property
    def result(self) -> dict | None:
        return None if self.view is None else self.view["result"]

    @property
    def error(self) -> dict | None:
        return None if self.view is None else self.view["error"]

    @property
    def candidate(self) -> str | None:
        return None if self.view is None else self.view["candidate_status"]


def run_job(client, project: str, kind: str, params: dict, *, if_match: str | None = None,
            headers: dict | None = None, request_id: str | None = None, timeout: float = 15) -> Run:
    """작업을 등록하고 이 실행기의 작업이면 끝날 때까지 기다린다. if_match는 따옴표 없는 ETag다."""
    sent = dict(headers or {})
    if if_match is not None:
        sent["If-Match"] = f'"{if_match}"'
    before = _job_ids(client, project)
    response = client.post(f"/api/projects/{project}/jobs", headers=sent, json={
        "request_id": request_id or f"req-{uuid.uuid4().hex}", "kind": kind, "params": params})
    if response.status_code not in (200, 202):
        # 범주 ①은 "행이 생기지 않음"까지 본다 (D3c-7 리뷰 H1). 목록을 읽을 수 없으면(원장 없음, 프로젝트 없음) 건너뛴다
        if before is not None:
            assert _job_ids(client, project) == before, f"거절된 {kind} 등록이 작업 행을 남겼습니다"
        return Run(response, None)
    job_id = response.json()["id"]
    handle = client.app.state.job_runner._handles.get(job_id)
    if handle is not None:
        assert handle.wait_sync(timeout) is not None, f"{kind} 작업이 {timeout}초 안에 끝나지 않았습니다"
    return Run(response, client.get(f"/api/projects/{project}/jobs/{job_id}").json())


def _job_ids(client, project: str) -> set[str] | None:
    response = client.get(f"/api/projects/{project}/jobs")
    return {job["id"] for job in response.json()} if response.status_code == 200 else None


# -- 옛 래퍼 경로의 이전 도우미 ----------------------------------------------------------------------------
#
# 시험이 부르던 래퍼 경로와 본문을 작업 API 등록으로 바꾸고, 결과를 대응표의 범주로 나눠 돌려준다. 범주는 기록해 두었다가
# 대응표(docs/qa/2026-10-13-d3c7-wrapper-migration.md)를 만드는 데 쓴다(환경 변수 D3C7_MIGRATION_OUT).

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

_WRAPPER = re.compile(r"^/api/projects/(?P<project>[^/]+)/(?:(?P<structure>generate/structure)|"
                      r"generate/chapter/(?P<condense_ch>[^/]+)/condense|generate/chapter/(?P<chapter_ch>[^/]+)|"
                      r"(?P<diagram>generate/diagram)|(?P<rewrite>story-plan/rewrite)|(?P<repair>story-plan/repair))$")
RECORDS: list[dict] = []


class Outcome:
    """옛 래퍼 응답 자리에 쓰는 작업 결과. status_code와 json()은 범주마다 다음 자리를 가리킨다.

    ① 등록 거절: 등록 응답의 상태와 본문 ② 실행 중 실패(state failed): 원장 오류의 status와 {"detail", "code"}
    성공(state succeeded, 후보 held): 200과 원장의 결과. 생성 뒤 판정으로 낡은 후보(③, 후보 stale)도 200과 결과이므로,
    그 시험은 candidate와 stale_reasons를 따로 본다. 취소와 중단은 status_code가 None이고 state로 본다.

    ①과 ②, 성공과 ③은 status_code만으로는 갈리지 않는다. 그래서 만들 때 다음을 단언한다 (D3c-7 리뷰 H1, H2).
    - 실행 중 실패가 4xx이면 expect="run_failure"를 넘긴 시험만 받는다. 등록 검사(404, 409, 422, 428)가 임대 뒤의 실행
      단계로 밀려도 상태 코드와 detail은 같으므로, 이 단언이 없으면 이전한 ① 시험이 그 변화를 잡지 못한다.
    - 성공은 후보 held와 빈 stale_reasons다. 생성 뒤 판정이 사유를 내는 결과는 expect="stale"을 넘기고 stale_result로 본다.
    등록 단계 503(제공자 없음, 원장 없음)은 실행 단계 503(로그인)과 상태가 같아 이 규칙 밖이다. 그 시험은 run.rejected를 직접 본다.
    """

    def __init__(self, run: Run, kind: str, expect: str | None = None):
        assert expect in (None, "run_failure", "stale"), expect
        self.run, self.kind = run, kind
        view = run.view
        if view is None:
            self.category, self.status_code, self._body = "registration", run.registration.status_code, run.registration.json()
        elif view["state"] == "failed":
            error = view["error"] or {}
            self.category, self.status_code = "failure", error.get("status") or 500
            self._body = {"detail": error.get("detail"), **({"code": error["code"]} if error.get("code") else {})}
        elif view["state"] == "succeeded":
            self.category = "stale" if view["candidate_status"] == "stale" else "success"
            self.status_code, self._body = 200, view["result"]
        else:
            self.category, self.status_code, self._body = view["state"], None, view
        if os.environ.get("D3C7_MIGRATION_OUT"):
            RECORDS.append({"test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0], "kind": kind,
                            "category": self.category, "status": self.status_code,
                            "state": view["state"] if view else None,
                            "candidate": view["candidate_status"] if view else None,
                            "reasons": view["stale_reasons"] if view else None})
        if expect == "run_failure":
            assert self.category == "failure", f"실행 중 실패를 기대했지만 {self.category}입니다: {self.text}"
        elif self.category == "failure" and self.status_code < 500:
            raise AssertionError(f"{kind} 작업이 실행 단계에서 {self.status_code}로 끝났습니다. 등록 검사라면 등록에서 "
                                 f"거절해야 하고, 실행 중 실패가 맞다면 expect='run_failure'를 넘깁니다: {self.text}")
        if view is not None and view["state"] == "succeeded":
            clean = view["candidate_status"] == "held" and view["stale_reasons"] == []
            assert clean == (expect != "stale"), (
                f"{kind} 결과의 후보가 {view['candidate_status']}, 사유가 {view['stale_reasons']}입니다"
                + ("" if clean else ". 생성 뒤 판정을 기대한다면 expect='stale'을 넘깁니다"))

    def json(self):
        return self._body

    @property
    def text(self) -> str:
        return json.dumps(self._body, ensure_ascii=False)

    @property
    def view(self) -> dict | None:
        return self.run.view


def post_generation(client, path: str, json: dict | None = None, headers: dict | None = None,
                    expect: str | None = None, **kwargs) -> Outcome:
    """옛 래퍼 경로(path)와 본문(json)으로 작업을 등록하고 끝날 때까지 기다린다. expect는 Outcome의 설명을 본다."""
    m = _WRAPPER.match(path)
    assert m, f"래퍼 경로가 아닙니다: {path}"
    body = dict(json or {})
    if m["condense_ch"]:
        kind, params = "condense", {"chapter_id": m["condense_ch"], **body}
    elif m["chapter_ch"]:
        kind, params = "chapter", {"chapter_id": m["chapter_ch"], **body}
    else:
        kind = next(k for k in ("structure", "diagram", "rewrite", "repair") if m[k])
        params = body
    sent = dict(headers or {})
    return Outcome(run_job(client, m["project"], kind, params, headers=sent, **kwargs), kind, expect)


def write_records() -> None:
    out = os.environ.get("D3C7_MIGRATION_OUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for record in RECORDS:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        RECORDS.clear()


def format_error_result(outcome: Outcome) -> dict:
    """형식 오류(대응표 ②): 래퍼는 200과 status format_error 결과를 돌려줬다. 작업 API에서는 작업이 ai_output으로 실패하고
    AI 응답 원문과 사용량은 원장의 결과에 남는다. 그 결과를 돌려준다."""
    view = outcome.view
    assert view is not None and view["state"] == "failed", outcome.text
    assert view["error"]["error_class"] == "ai_output" and view["candidate_status"] == "none", outcome.text
    assert view["result"]["status"] == "format_error", outcome.text
    return view["result"]


def stale_result(outcome: Outcome, reasons: list[str], candidate: str = "stale") -> dict:
    """생성 뒤 판정(대응표 ③): 래퍼는 412나 409를 돌려줬다. 작업 API에서는 작업이 성공하고 결과가 낡은 후보로 남는다.
    판정할 수 없으면(자료를 읽지 못함) 후보는 held이고 사유는 unknown_*다. 등록할 때 expect="stale"을 넘긴다.

    stale_reasons는 실행기의 판정(_basis_reasons)이 아니라 조회 때 덱과 자료를 다시 읽어 계산한 값이다 (D3c-7 리뷰 H6).
    화면이 보는 사유도 이 값이다."""
    view = outcome.view
    assert view is not None and (view["state"], view["candidate_status"]) == ("succeeded", candidate), outcome.text
    assert view["stale_reasons"] == reasons, view["stale_reasons"]
    return view["result"]
