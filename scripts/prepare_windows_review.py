"""Prepare isolated synthetic PowerPoint review files using the current exporter.

No AI calls, existing project writes, human verdicts, or signed approvals.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from slidecaptain.export.exporter import export_deck_data
from slidecaptain.models.deck import Deck
from slidecaptain.models.expression import ChartSpec, TextSpan
from slidecaptain.pipeline.story import story_fingerprint
from slidecaptain.storage.file_store import FileProjectStore


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "backend/tests/fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def basic_deck():
    bullets = [{"text": "합성 요청은 접수, 검토, 회신 순서로 처리한다."},
               {"text": "검토 결과와 다음 행동을 함께 기록한다."}]
    cases = [
        ("표지", {"template": "cover", "title": "합성 요청 처리 보고", "subtitle": "표현과 편집 기능 확인용 합성 자료", "date": "2026-10-02"}),
        ("핵심 요약", {"template": "summary", "conclusion": "접수부터 회신까지 담당자와 확인 항목을 정리한다.", "points": bullets}),
        ("요청 처리 기준", {"template": "bullet_box", "bullets": bullets, "conclusion": "회신 전에 검토 결과를 확인한다.", "footnote": "실제 회사 업무나 성과를 나타내지 않는 합성 예시"}),
        ("단계별 담당", {"template": "table", "columns": ["단계", "담당", "확인 항목"], "rows": [["접수", "접수 담당", "요청 내용"], ["검토", "검토 담당", "필요 자료"], ["회신", "접수 담당", "검토 결과"]], "footnote": "합성 운영 예시"}),
        ("회신 방식 비교", {"template": "compare2", "left": {"heading": "개별 회신", "bullets": [{"text": "요청별로 검토 결과를 전달한다."}]}, "right": {"heading": "묶음 회신", "bullets": [{"text": "관련 요청의 검토 결과를 함께 전달한다."}]}, "conclusion": "방식 선택은 요청 내용과 회신 시점에 따라 달라진다."}),
        ("실행 절차", {"template": "divider", "section_no": "02", "section_title": "요청 처리 절차"}),
        ("회신 전 확인", {"template": "callout", "text": "요청 내용과 검토 결과를 대조한 뒤 회신한다.", "tone": "accent1"}),
        ("담당자 역할", {"template": "cards", "cards": [{"badge": "접수", "heading": "접수 담당", "bullets": [{"text": "요청을 기록하고 검토 담당자에게 전달한다."}], "tail": "요청 기록", "emphasis": True}, {"badge": "검토", "heading": "검토 담당", "bullets": [{"text": "자료를 확인하고 결과를 정리한다."}], "tail": "검토 결과"}]}),
        ("처리 순서", {"template": "process", "steps": [{"heading": "접수", "subtitle": "요청 기록", "notes": ["내용 확인"]}, {"heading": "검토", "subtitle": "자료 확인", "notes": ["결과 정리"]}, {"heading": "회신", "subtitle": "결과 전달", "notes": ["기록 보관"]}]}),
        ("확인 항목 분류", {"template": "matrix", "rows": [{"category": "접수", "primary": "요청", "items": ["내용", "회신 시점"]}, {"category": "검토", "primary": "자료", "items": ["누락", "불일치"]}, {"category": "회신", "primary": "결과", "items": ["다음 행동", "담당자"]}]}),
    ]
    return Deck.model_validate({"meta": {"title": "합성 요청 처리 보고"}, "structure": {"chapters": [
        {"id": f"p{i}", "topic": title, "template": slots["template"]}
        for i, (title, slots) in enumerate(cases, 1)]}, "slides": [
        {"chapter_id": f"p{i}", "slots": slots}
        for i, (_, slots) in enumerate(cases, 1)]})


def samples():
    yield "templates", basic_deck(), {}, "10종 템플릿의 전체 페이지 표시와 편집"
    flow = fixture("q3b-project.json")
    yield "diagram", Deck.model_validate(flow["deck"]), flow["sources"], "도식의 노드, 연결선, 사실과 제안 구분"
    for kind in ("bar", "column"):
        item = fixture("q2d-numeric-review.json")
        payload = item["deck"]
        payload["meta"]["title"] = f"합성 비교 {kind}"
        payload["structure"]["chapters"][0]["template"] = "table"
        payload["slides"][0]["slots"] = {"template": "table", "columns": ["팀", "순매출"],
            "rows": [["A", "1200원"], ["B", "1000원"]], "footnote": "합성 자료, 같은 기간과 지표"}
        deck = Deck.model_validate(payload)
        plan = deck.structure.story_plan
        plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, item["sources"])
        deck.slides[0].chart = ChartSpec(rule_version="comparison-chart-v1", comparison_id=plan.comparisons[0].id, kind=kind)
        yield kind, deck, item["sources"], "차트 값 1200/1000, 원 단위, 기간, 0축과 데이터 편집"
    item = fixture("q2d-numeric-review.json")
    deck = Deck.model_validate(item["deck"])
    text = deck.slides[0].slots.bullets[0].text
    deck.slides[0].text_spans = [TextSpan(slot="bullets", index=0, start=0, end=2,
        role="bold", text_sha256=hashlib.sha256(text.encode()).hexdigest())]
    yield "emphasis", deck, item["sources"], "문장 앞 두 글자의 부분 굵게 표시와 줄바꿈"


def prepare(parent):
    # Exclusive creation means a repeat run cannot overwrite earlier feedback.
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / datetime.now().strftime("run-%Y%m%d-%H%M%S-%f")
    root.mkdir()
    store = FileProjectStore(root / "store")
    manifest = {"version": "windows-review-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "ai_calls": 0, "human_status": "not_run", "artifacts": []}
    try:
        manifest["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        manifest["worktree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO))
    except (OSError, subprocess.CalledProcessError):
        manifest["git_commit"] = None
        manifest["worktree_dirty"] = None
    for name, deck, sources, focus in samples():
        store.create_project(name, deck.meta.title)
        for filename, text in sources.items():
            store.write_source(name, filename, text)
        store.save_deck(name, deck, snapshot=False)
        artifact = export_deck_data(deck, store.exports_dir(name), sources=sources)
        manifest["artifacts"].append({"id": name, "title": deck.meta.title,
            "file": artifact.relative_to(root).as_posix(), "focus": focus,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "pages": [{"page": i, "topic": chapter.topic} for i, chapter in enumerate(deck.structure.chapters, 1)]})
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    template = (REPO / "scripts/windows-review-form.html").read_text(encoding="utf-8")
    payload = json.dumps(manifest, ensure_ascii=False).replace("<", "\\u003c")
    (root / "index.html").write_text(template.replace("__REVIEW_MANIFEST__", payload), encoding="utf-8")
    (parent / "latest-run.txt").write_text(str(root.resolve()), encoding="utf-8")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "projects/windows-review")
    args = parser.parse_args()
    print(prepare(args.out))
