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
from slidecaptain.pipeline.story import _text_hash, story_fingerprint
from slidecaptain.storage.file_store import FileProjectStore


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "backend/tests/fixtures"


def targeted_review():
    """C3 T4's manual checks; preparing files never supplies a verdict."""
    checks = [
        ("bar-axis", "가로 막대 값 축과 그림 영역", "bar", 1,
         "미리보기와 PowerPoint에서 값 축 글자 0, 1320과 그림 영역 위쪽 시작을 비교한다.",
         "값 축은 아래에 있고 그림 영역 위쪽 시작 차이는 1pt 이내다. 측정값을 메모한다."),
        ("bar15-values", "15자리 값과 축 글자", "bar15", 1,
         "미리보기와 PowerPoint의 데이터 값과 축 최댓값을 비교한다.",
         "값 123456789.123456과 축 최댓값 135802468.035810이 같은 글자로 보인다."),
        ("column-labels", "세로 막대 범주 이름", "column", 1,
         "A팀, B팀 글자가 축 아래 미리보기와 같은 높이에 있는지 확인한다.",
         "기본 12pt에서 글자 획이 축 아래 약 15~25pt이고 잘리지 않는다."),
        ("process-labels", "번호 단계 보조 라벨 배치", "templates", 9,
         "첫 단계의 라벨 두 개를 포함해 번호 단계 페이지를 미리보기와 PowerPoint에서 비교한다.",
         "라벨이 단계 이름과 부제 아래 왼쪽 정렬로 쌓이고 행 안에 있다. 사용자가 판정한다."),
        ("process-label-movement", "라벨 직접 이동과 선택 테두리", "templates", 9,
         "합성 프로젝트 templates의 편집 화면에서 라벨을 선택하고 직접 이동해 본다.",
         "사용자가 가로 이동 범위 0~144pt와 선택 테두리 크기를 판정한다. 원하는 변경을 메모한다(C3R-05)."),
        ("status-icon", "반영 결과 확인 필요 아이콘", None, None,
         "Windows 앱의 '반영 결과 확인 필요' 상태에서 느낌표 두 개(‼︎, U+203C U+FE0E)를 확인한다. "
         "양식의 문자만 보고 통과 처리하지 않는다. 실제 앱 상태를 재현하지 못하면 미평가로 남긴다.",
         "실제 앱에서 글자 모양으로 표시되고 네모나 대체 문자로 깨지지 않는다. Windows 버전과 배율을 기록한다."),
    ]
    return {"version": "c3-t4-v1", "checks": [
        dict(zip(("id", "title", "artifact_id", "page", "instruction", "expected"), row))
        for row in checks
    ]}


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
        ("처리 순서", {"template": "process", "steps": [{"heading": "접수", "subtitle": "요청 기록", "notes": ["내용 확인", "담당 접수팀"]}, {"heading": "검토", "subtitle": "자료 확인", "notes": ["결과 정리"]}, {"heading": "회신", "subtitle": "결과 전달", "notes": ["기록 보관"]}]}),
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
    # bar15는 유효숫자 15자리 값과 그 축(회사 PC 이월표 (7))을 PowerPoint가 미리보기와 같은 글자로 보이는지 본다
    for name, kind, a_value in (("bar", "bar", "1200"), ("column", "column", "1200"), ("bar15", "bar", "123456789.123456")):
        item = fixture("q2d-numeric-review.json")
        item = json.loads(json.dumps(item, ensure_ascii=False).replace("1,200", "1,200" if a_value == "1200" else a_value))
        for evidence in item["deck"]["structure"]["story_plan"]["evidence"]:
            evidence["source_revision"] = _text_hash(item["sources"][evidence["source_id"]])
        payload = item["deck"]
        payload["meta"]["title"] = f"합성 비교 {name}"
        payload["structure"]["chapters"][0]["template"] = "table"
        payload["slides"][0]["slots"] = {"template": "table", "columns": ["팀", "순매출"],
            "rows": [["A", f"{a_value}원"], ["B", "1000원"]], "footnote": "합성 자료, 같은 기간과 지표"}
        deck = Deck.model_validate(payload)
        plan = deck.structure.story_plan
        plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, item["sources"])
        deck.slides[0].chart = ChartSpec(rule_version="comparison-chart-v1", comparison_id=plan.comparisons[0].id, kind=kind)
        yield name, deck, item["sources"], f"차트 값 {a_value}/1000, 원 단위, 기간, 0축과 데이터 편집"
    item = fixture("q2d-numeric-review.json")
    deck = Deck.model_validate(item["deck"])
    text = deck.slides[0].slots.bullets[0].text
    deck.slides[0].text_spans = [TextSpan(slot="bullets", index=0, start=0, end=2,
        role="bold", text_sha256=hashlib.sha256(text.encode()).hexdigest())]
    yield "emphasis", deck, item["sources"], "문장 앞 두 글자의 부분 굵게 표시와 줄바꿈"


def prepare(parent):
    # 상대 경로면 아래 relative_to가 실패해 반쯤 만든 폴더가 남는다 (C3 리뷰 C3R-12)
    parent = Path(parent).resolve()
    # Exclusive creation means a repeat run cannot overwrite earlier feedback.
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / datetime.now().strftime("run-%Y%m%d-%H%M%S-%f")
    root.mkdir()
    store = FileProjectStore(root / "store")
    manifest = {"version": "windows-review-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "ai_calls": 0, "human_status": "not_run", "artifacts": [],
                "targeted_review": targeted_review()}
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
