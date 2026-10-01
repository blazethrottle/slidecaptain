"""Synthetic, bounded pilot through the app API; default: prepare, no AI.

Run from backend with the repository's dev dependencies installed:
  python -m scripts.quality_pilot --output /new/local/folder [--offline]
Live use additionally requires --live --consent --max-calls N.
The limit counts provider.complete attempts, not SDK turns or billing units.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from slidecaptain.models.deck import Deck
from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.codex import CodexConnection
from slidecaptain.pipeline.connections import (
    AIConnections, AISelection, ClaudeConnection, LoginAttempt, ModelOption,
)
from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderError, ProviderResponse
from slidecaptain.pipeline.story import require_current_story, story_fingerprint
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

PROJECT = "quality-pilot"
BODY = "pilot-action"


def _write(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def scenario():
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/q3b-project.json"
    sample = json.loads(fixture.read_text(encoding="utf-8"))
    data = sample["deck"]
    data["structure"]["chapters"].append({
        "id": BODY, "topic": "자동 알림 도입 전 확인할 사항", "template": "bullet_box",
        "conclusion": "효과와 비용을 확인한 뒤 도입 여부를 결정한다",
        "source_refs": list(sample["sources"]),
    })
    plan = data["structure"]["story_plan"]
    plan["claims"].append({
        "id": "action", "statement": "자동 알림의 효과와 비용을 확인한 뒤 도입 여부를 결정한다.",
        "kind": "proposal", "evidence_ids": ["e3"], "caveats": ["효과와 비용은 확인하지 않았다."],
    })
    plan["chapters"].extend([
        {"chapter_id": "cover", "role": "cover", "claim_ids": []},
        {"chapter_id": BODY, "role": "action", "claim_ids": ["action"]},
    ])
    data["slides"].append({"chapter_id": BODY, "slots": {
        "template": "bullet_box", "bullets": [{"text": "효과와 비용을 확인할 필요가 있다."}],
        "conclusion": "합성 초안: 도입 여부 미결정", "footnote": "합성 자료",
    }})
    deck = Deck.model_validate(data)
    plan = deck.structure.story_plan
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sample["sources"])
    require_current_story(deck, sample["sources"])
    brief = plan.brief.model_copy(update={"decision_question": "요청 처리 흐름과 자동 알림 도입 전 확인할 사항은 무엇인가?"})
    return {
        "synthetic": True, "sources": sample["sources"], "deck": deck.model_dump(mode="json"),
        "rewrite_brief": brief.model_dump(mode="json"),
        "chapter_instructions": "합성 운영 사례다. 근거에 없는 수치와 효과를 만들지 말고, 사실과 제안을 구분해 짧게 작성한다.",
        "rewrite_instructions": "기존 도식과 보호 주장/근거를 보존한다. 표지, 개선 검토, 업무 흐름 순으로 배치한다. 장은 추가하거나 삭제하지 않는다.",
    }


class OfflineProvider:
    """Fixed synthetic responses, never a real provider fallback."""

    async def complete(self, prompt, schema):
        data = scenario()
        if "chapter_order" in schema.get("properties", {}):
            plan = data["deck"]["structure"]["story_plan"]
            payload = {k: deepcopy(plan[k]) for k in (
                "claims", "answer_claim_ids", "unanswered_questions", "comparisons", "derivations",
            )}
            payload["evidence"] = []
            payload["claims"] = [claim for claim in payload["claims"] if claim["id"] == "action"]
            by_id = {c["chapter_id"]: c for c in plan["chapters"]}
            payload["chapter_order"] = ["cover", BODY, "synthetic-flow"]
            payload["chapters"] = [by_id[key] for key in ("cover", BODY)]
        else:
            payload = {
                "template": "bullet_box", "bullets": [
                    {"text": "접수 후 검토 담당자에게 요청을 전달한다."},
                    {"text": "자동 알림 도입은 제안이며 효과와 비용을 확인해야 한다."},
                ], "conclusion": "도입 전 효과와 비용을 확인한다", "footnote": "합성 자료",
            }
        return ProviderResponse(structured=payload, raw_text="synthetic offline response")


class BudgetedProvider:
    """One shared dispatch budget covers generation, retry and condense."""

    def __init__(self, upstream, *, max_calls, on_change=None, on_request=None):
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("호출 상한은 양의 정수여야 합니다.")
        self.upstream = upstream
        self.max_calls = max_calls
        self.calls = 0
        self.blocked_calls = 0
        self.records = []
        self.on_change = on_change or (lambda: None)
        self.on_request = on_request or (lambda number, prompt, schema: None)
        self._lock = threading.Lock()
        self._journal_failed = False

    async def complete(self, prompt, schema):
        with self._lock:
            if self._journal_failed:
                raise OSError("실행 기록을 보존하지 못해 추가 호출을 중단했습니다.")
            if self.calls >= self.max_calls:
                self.blocked_calls += 1
                self.on_change()
                raise ProviderCallFailed("승인된 호출 상한에 도달했습니다.")
            self.calls += 1
            record = {"number": self.calls, "status": "started", "usage": None,
                      "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                      "schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()}
            self.records.append(record)
            try:
                self.on_request(self.calls, prompt, schema)
                self.on_change()
            except BaseException:
                self.calls -= 1
                record["status"] = "not_sent"
                self._journal_failed = True
                raise
        try:
            response = await self.upstream.complete(prompt, schema)
        except BaseException as exc:
            record["status"] = "failed" if isinstance(exc, Exception) else "interrupted"
            usage = exc.usage if isinstance(exc, ProviderError) else None
            record["usage"] = usage.model_dump(mode="json") if usage else None
            raise
        else:
            record["status"] = "returned"
            record["usage"] = response.usage.model_dump(mode="json") if response.usage else None
            return response
        finally:
            try:
                self.on_change()
            except BaseException:
                self._journal_failed = True
                raise


class _PilotConnection:
    def __init__(self, provider, model, real=None):
        self.bounded = provider
        self.model = model
        self.real = real

    def status(self):
        return self.real.status() if self.real else LoginStatus(logged_in=True, auth_method="synthetic")

    def models(self):
        return self.real.models() if self.real else [ModelOption(id=self.model, label=self.model)]

    def login_status(self):
        return LoginAttempt(state="idle")

    def provider(self, model):
        if model != self.model:
            raise ProviderCallFailed("파일럿 모델이 바뀌었습니다.")
        return self.bounded

    def close(self):
        if self.real:
            self.real.close()


class PilotStopped(Exception):
    pass


def _expect(condition, message):
    if not condition:
        raise PilotStopped(message)


def _workflow(client, output, data, report):
    route = f"/api/projects/{PROJECT}"

    def request(method, suffix, *, status=200, **kwargs):
        response = client.request(method, route + suffix, **kwargs)
        _expect(response.status_code == status, f"{method} {suffix}: HTTP {response.status_code}")
        return response

    report["stage"] = "chapter"
    base = request("GET", "/deck")
    generated = request("POST", f"/generate/chapter/{BODY}", json={"instructions": data["chapter_instructions"]}).json()
    _write(output / "chapter-result.json", generated)
    _expect(generated["status"] == "ok", "장 생성 응답을 적용하지 못했습니다.")
    deck = base.json()
    slide = next(s for s in deck["slides"] if s["chapter_id"] == BODY)
    slide["slots"] = generated["slots"]
    request("PUT", "/deck", json=deck, headers={"If-Match": base.headers["etag"]})
    before = request("GET", "/deck")
    _write(output / "before-rewrite.json", before.json())
    # The service intentionally preserves a valid draft when condensing fails.
    # That does not mean the pilot may disregard a blocked dispatch.
    _expect(report["blocked_calls"] == 0, "호출 상한으로 중단했습니다. 생성된 본문은 저장했습니다.")
    snapshots = request("GET", "/snapshots").json()

    report["stage"] = "rewrite_preview"
    candidate = request("POST", "/story-plan/rewrite", json={
        "brief": data["rewrite_brief"], "instructions": data["rewrite_instructions"],
    }, headers={"If-Match": before.headers["etag"]}).json()
    _write(output / "rewrite-result.json", candidate)
    _expect(candidate["status"] == "ok", "재작성 후보를 적용하지 못했습니다.")
    unchanged = request("GET", "/deck")
    checks = report["checks"]
    checks["preview_did_not_save"] = (
        unchanged.headers["etag"] == before.headers["etag"] and unchanged.json() == before.json()
        and request("GET", "/snapshots").json() == snapshots
    )
    _expect(checks["preview_did_not_save"], "미리보기 중 저장본이 바뀌었습니다.")
    report["stage"] = "rewrite_apply"
    applied = request("POST", "/story-plan/rewrite/apply", json={
        "deck": candidate["deck"], "sources_fingerprint": candidate["sources_fingerprint"],
    }, headers={"If-Match": candidate["base_etag"]}).json()
    checks["rewrite_preserved_slides"] = applied["slides"] == before.json()["slides"]
    _expect(checks["rewrite_preserved_slides"], "재작성 과정에서 기존 본문이 변경됐습니다.")
    _write(output / "applied-deck.json", applied)

    report["stage"] = "export"
    render = request("GET", "/render-plan").json()
    _write(output / "render-plan.json", render)
    exported = request("POST", "/export").json()
    _write(output / "export-result.json", exported)
    pptx = Path(exported["path"])
    quality = json.loads(Path(exported["quality_path"]).read_text(encoding="utf-8"))
    document = Presentation(pptx)
    checks["pptx_slide_count"] = len(document.slides)
    _expect(checks["pptx_slide_count"] == 3, "PPTX의 장 수가 다릅니다.")
    checks["pptx_hash_matches"] = quality["artifact_sha256"] == hashlib.sha256(pptx.read_bytes()).hexdigest()
    _expect(checks["pptx_hash_matches"], "PPTX와 품질 기록의 해시가 다릅니다.")
    shapes = {shape.name: shape for page in document.slides for shape in page.shapes}
    expected = [f"synthetic-flow:node:{node}" for node in ("intake", "review", "pilot")]
    checks["editable_diagram"] = all(name in shapes and shapes[name].shape_type != MSO_SHAPE_TYPE.PICTURE for name in expected)
    _expect(checks["editable_diagram"], "편집 가능한 도식 요소를 찾지 못했습니다.")
    paths_before = {p.name for p in pptx.parent.iterdir()}
    rejected = client.post(route + "/export?final=true")
    checks["final_export_blocked"] = rejected.status_code == 422 and paths_before == {p.name for p in pptx.parent.iterdir()}
    _expect(checks["final_export_blocked"], "미검수 제출본이 차단되지 않았습니다.")
    report["quality_status"] = quality["status"]
    report["artifacts"] = {"pptx": str(pptx), "quality": exported["quality_path"]}


def run_pilot(output, *, mode="prepare", consent=False, max_calls=None, model=None, provider=None,
              ai_provider="claude", codex_home=None):
    if mode not in {"prepare", "offline", "live"}:
        raise ValueError("지원하지 않는 실행 모드입니다.")
    if mode == "live" and (not consent or type(max_calls) is not int or max_calls < 1):
        raise ValueError("실제 호출에는 전송 동의와 명시적인 양의 호출 상한이 필요합니다.")
    limit = 5 if max_calls is None else max_calls
    if type(limit) is not int or limit < 1:
        raise ValueError("호출 상한은 양의 정수여야 합니다.")
    if ai_provider not in {"claude", "chatgpt"}:
        raise ValueError("지원하지 않는 AI 서비스입니다.")
    model = model if model is not None else ("sonnet" if ai_provider == "claude" else "gpt-6-luna")
    chosen = AISelection(provider=ai_provider, model=model)
    if ai_provider == "claude" and model not in {"sonnet", "opus", "haiku"}:
        raise ValueError("Claude 모델은 sonnet, opus, haiku 중에서 선택해야 합니다.")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "mode": mode, "status": "running", "stage": "prepare", "synthetic": True,
        "requested_provider": ai_provider, "requested_model": model,
        "max_calls": limit, "provider_calls": 0, "external_calls": 0, "blocked_calls": 0,
        "call_unit": "provider.complete attempts; excludes pre-dispatch refusals; SDK turns are separate",
        "usage_basis": "app CallUsage; raw SDK missing-field normalization is not independently verified",
        "calls": [], "checks": {}, "review": {k: "not_run" for k in ("semantic", "browser", "powerpoint", "reader")},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    bounded = None
    real = None
    manager = None

    def persist():
        if bounded:
            report.update(provider_calls=bounded.calls, external_calls=bounded.calls if mode == "live" else 0,
                          blocked_calls=bounded.blocked_calls, calls=bounded.records)
        _write(output / "report.json", report)

    try:
        data = scenario()
        _write(output / "input.json", data)
        report["input_sha256"] = hashlib.sha256((output / "input.json").read_bytes()).hexdigest()
        store = FileProjectStore(output / "projects")
        store.create_project(PROJECT)
        for filename, text in data["sources"].items():
            store.write_source(PROJECT, filename, text)
        store.save_deck(PROJECT, Deck.model_validate(data["deck"]), snapshot=False)
        if mode == "prepare":
            report["status"] = "prepared"
            return report
        if mode == "live":
            real = (ClaudeConnection() if ai_provider == "claude" else CodexConnection(
                Path(codex_home) if codex_home is not None
                else Path.home() / "slidecaptain-projects" / ".slidecaptain-codex",
            ))
        upstream = provider or (real.provider(model) if real else OfflineProvider())
        bounded = BudgetedProvider(upstream, max_calls=limit, on_change=persist,
                                   on_request=lambda n, prompt, schema: _write(output / f"call-{n:02d}-input.json", {
                                       "prompt": prompt, "schema": schema,
                                   }))
        connection = _PilotConnection(bounded, model, real)
        manager = AIConnections(output / "ai-settings.json", initial=chosen, connections={ai_provider: connection})
        _, selection, _ = manager.selected_status()
        with TestClient(create_app(store, ai_connections=manager), headers={
            "X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain", "X-AI-Selection": selection,
        }) as client:
            _workflow(client, output, data, report)
        report["status"] = "completed"
        report["stage"] = "done"
    except Exception as exc:
        report["status"] = "blocked"
        report["error"] = str(exc) if isinstance(exc, PilotStopped) else type(exc).__name__
    except BaseException:
        report["status"] = "interrupted"
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            persist()
        finally:
            if manager is not None:
                manager.close()
            elif real is not None:
                real.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="새 로컬 출력 폴더")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--offline", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--consent", action="store_true", help="합성 입력을 선택한 AI 서비스로 전송하는 데 동의")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--provider", choices=["claude", "codex"], default="claude")
    parser.add_argument("--model", help="Claude 기본 sonnet, Codex 기본 gpt-6-luna. 다른 모델은 명시적으로 지정")
    parser.add_argument("--codex-home", type=Path, help="SlideCaptain 전용 Codex 프로필 경로 (기본: ~/slidecaptain-projects/.slidecaptain-codex)")
    args = parser.parse_args(argv)
    if args.live and (not args.consent or args.max_calls is None or args.max_calls < 1):
        parser.error("--live에는 --consent와 양의 --max-calls가 필요합니다.")
    if args.max_calls is not None and args.max_calls < 1:
        parser.error("--max-calls는 양의 정수여야 합니다.")
    try:
        report = run_pilot(args.output, mode="live" if args.live else "offline" if args.offline else "prepare",
                           consent=args.consent, max_calls=args.max_calls, model=args.model,
                           ai_provider="chatgpt" if args.provider == "codex" else "claude",
                           codex_home=args.codex_home)
    except FileExistsError:
        parser.error("이미 존재하는 출력 폴더는 사용할 수 없습니다.")
    except ValueError:
        parser.error("AI 서비스와 모델 설정을 확인해 주세요.")
    print(json.dumps({k: report[k] for k in ("status", "stage", "provider_calls", "external_calls")}, ensure_ascii=False))
    return 0 if report["status"] in {"prepared", "completed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
