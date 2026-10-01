"""Local, blinded comparison preparation. Human judgments are never fabricated."""

import hashlib
import html
import io
import json
import math
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ARMS = ("general-agent", "previous", "improved")
CRITERIA = ("narrative", "evidence", "representation", "readability", "submission_readiness")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 32 * 1024 * 1024
_MAX_TOTAL = 256 * 1024 * 1024


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("측정값은 0 이상의 실제 수치 또는 미확인(null)이어야 합니다.")
    return value


def _json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _pptx_bytes(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > _MAX_BYTES:
        raise ValueError("비교 출력은 제한 크기 이내의 일반 PPTX 파일이어야 합니다.")
    value = p.read_bytes()
    if len(value) > _MAX_BYTES:
        raise ValueError("비교 출력 크기 한도를 넘었습니다.")
    import io
    from pptx import Presentation
    with ZipFile(io.BytesIO(value)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > 256 * 1024 * 1024:
            raise ValueError("PPTX 압축 해제 한도를 넘었습니다.")
    if not Presentation(io.BytesIO(value)).slides:
        raise ValueError("대상 0페이지는 비교 성공이 아닙니다.")
    return value


def _blind_metadata(data):
    """Strip producer metadata in the comparison copy; never rewrite its source."""
    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as original, ZipFile(output, "w") as blinded:
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename.startswith("docProps/") and entry.filename.endswith(".xml"):
                root = ET.fromstring(content)
                # Metadata is not slide content. Remove author/provider/title and
                # custom tags alike; appearance and editable slide parts stay intact.
                for node in list(root):
                    root.remove(node)
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            blinded.writestr(entry, content)
    return output.getvalue()


def prepare_blind_pilot(spec: dict, out_dir: str | Path) -> Path:
    """Validate all cases before creating an immutable local comparison folder."""
    if not isinstance(spec, dict):
        raise ValueError("비교 계획은 JSON 객체여야 합니다.")
    output = Path(out_dir)
    if output.exists() or output.is_symlink():
        raise FileExistsError("기존 비교 폴더를 덮어쓰지 않습니다.")
    cases = spec.get("cases", [])
    if not 3 <= len(cases) <= 100:
        raise ValueError("처음 비교에는 독립 자료 최소 3건, 최대 100건이 필요합니다.")
    seen_sources, seen_ids = set(), set()
    trials, mapping, artifacts = [], {}, {}
    for case_index, case in enumerate(cases, 1):
        source = case.get("source_fingerprint", "")
        case_id = case.get("case_id", "")
        if not isinstance(source, str) or not _HEX.fullmatch(source) or source in seen_sources:
            raise ValueError("사례마다 독립 자료 SHA-256이 필요합니다. 같은 자료의 버전을 별도 사례로 세지 않습니다.")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen_ids:
            raise ValueError("사례 ID는 비어 있지 않은 고유 문자열이어야 합니다.")
        seen_sources.add(source); seen_ids.add(case_id)
        request, profile = case.get("request"), case.get("reading_profile")
        if not isinstance(request, str) or not request.strip() or not isinstance(profile, str) or not profile.strip():
            raise ValueError("같은 보고 질문과 읽기 환경을 명시해야 합니다.")
        supplied = case.get("outputs", [])
        if len(supplied) != 3 or {x.get("arm") for x in supplied} != set(ARMS):
            raise ValueError("모든 사례에 일반 에이전트, 기존 버전, 개선 버전 세 비교군이 필요합니다.")
        order = secrets.SystemRandom().sample(list(supplied), 3)
        conditions = hashlib.sha256(json.dumps({"source": source, "request": request,
            "profile": profile, "format": "pptx"}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        for letter, item in zip("ABC", order):
            trial_id = f"case-{case_index:03d}-{letter}"
            status = item.get("status")
            if status not in ("completed", "failed", "held"):
                raise ValueError("실행 상태는 completed, failed 또는 held여야 합니다.")
            if status != "completed" and (not isinstance(item.get("note"), str) or not item["note"].strip()):
                raise ValueError("실패/보류 이유를 남겨야 합니다.")
            row = {"trial_id": trial_id, "case_number": case_index, "label": letter, "status": status,
                   "conditions_fingerprint": conditions, "request": request, "reading_profile": profile,
                   "cost_usd": _number(item.get("cost_usd")), "production_minutes": _number(item.get("production_minutes")),
                   "artifact_sha256": None, "artifact": None}
            mapping[trial_id] = {"case_id": case_id, "arm": item["arm"], "source_fingerprint": source,
                                 "provider": item.get("provider"), "model": item.get("model"),
                                 "settings": item.get("settings"), "note": item.get("note")}
            if status == "completed":
                original = _pptx_bytes(item.get("artifact", ""))
                mapping[trial_id]["source_artifact_sha256"] = hashlib.sha256(original).hexdigest()
                data = _blind_metadata(original)
                if sum(len(blob) for blob in artifacts.values()) + len(data) > _MAX_TOTAL:
                    raise ValueError("비교 출력 합계 크기 한도를 넘었습니다. 사례를 나눠 준비해 주세요.")
                row["artifact_sha256"] = hashlib.sha256(data).hexdigest()
                row["artifact"] = f"{trial_id}.pptx"
                artifacts[row["artifact"]] = data
            trials.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".blind-pilot-", dir=output.parent))
    try:
        for name, data in artifacts.items():
            (stage / name).write_bytes(data)
        _json(stage / "manifest.json", {"version": "blind-pilot-v1", "trials": trials})
        _json(stage / "private-mapping.json", mapping)
        os.chmod(stage / "private-mapping.json", 0o600)
        _json(stage / "evaluations-template.json", {"evaluations": []})
        (stage / "index.html").write_text(_form(trials), encoding="utf-8")
        # Rename only into an absent destination; a parallel creator must not be replaced.
        output.mkdir()
        try:
            for child in stage.iterdir():
                os.link(child, output / child.name)
        except Exception:
            # Only our just-created entries are owned here.
            for child in stage.iterdir():
                target = output / child.name
                if target.exists() and os.path.samefile(target, child):
                    target.unlink()
            output.rmdir()
            raise
    finally:
        shutil.rmtree(stage)
    return output


def _form(trials):
    cards = []
    labels = {"narrative": "보고 흐름", "evidence": "근거와 수치", "representation": "표현 적절성",
              "readability": "가독성", "submission_readiness": "제출 준비도"}
    for row in trials:
        name = html.escape(row["trial_id"], quote=True)
        if row["status"] != "completed":
            cards.append(f'<section><h2>{name}</h2><p>실행되지 않은 비교 출력입니다. 분모에 포함하며 품질을 판정하지 않습니다.</p></section>')
            continue
        fields = ''.join(f'<label>{label}<select data-criterion="{key}"><option value="">미판정</option>'
            '<option value="passed">통과</option><option value="needs_revision">수정 필요</option></select></label>'
            for key, label in labels.items())
        cards.append(f'<section data-trial="{name}"><h2>{name}</h2><p>{html.escape(row["request"])}</p>'
            f'<p>읽기 환경: {html.escape(row["reading_profile"])}</p><a href="{name}.pptx">비교 출력 열기</a>{fields}'
            '<label>판단 근거<textarea data-note></textarea></label><label>검수자<input data-reviewer></label>'
            '<label>제출까지 실제 수정 시간(분)<input data-minutes type="number" min="0" step="0.1"></label></section>')
    script = """document.querySelector('#save').onclick=()=>{const evaluations=[...document.querySelectorAll('[data-trial]')].map(s=>({trial_id:s.dataset.trial,reviewer:s.querySelector('[data-reviewer]').value,criteria:Object.fromEntries([...s.querySelectorAll('[data-criterion]')].map(e=>[e.dataset.criterion,e.value||null])),note:s.querySelector('[data-note]').value,revision_minutes:s.querySelector('[data-minutes]').value===''?null:Number(s.querySelector('[data-minutes]').value)}));const b=new Blob([JSON.stringify({evaluations},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='evaluations.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};"""
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
        '<title>보고서 비교 판정</title><style>body{max-width:900px;margin:32px auto;padding:0 20px;font:16px/1.6 sans-serif}section{border:1px solid #ccd;padding:20px;margin:20px 0}label{display:block;margin:12px 0}textarea,input,select{display:block;width:100%;box-sizing:border-box;padding:8px}button{padding:12px}</style>' \
        '<h1>보고서 비교 판정</h1><p>제작 방식을 가린 출력입니다. 모든 페이지를 직접 확인해 판정하고 실제 수정 시간을 기록하세요. 미판정과 미측정은 빈칸으로 유지합니다.</p>' \
        + ''.join(cards) + '<button id="save">판정 기록 저장</button><script>' + script + '</script></html>'


def read_blind_pilot_report(folder: str | Path, evaluations: dict | None = None) -> dict:
    folder = Path(folder)
    for filename in ("manifest.json", "private-mapping.json"):
        file = folder / filename
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("비교 기록 파일을 안전하게 읽을 수 없거나 크기 한도를 넘었습니다.")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    mapping = json.loads((folder / "private-mapping.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "blind-pilot-v1":
        raise ValueError("지원하지 않는 비교 기록입니다.")
    trials = manifest["trials"]
    if not isinstance(trials, list) or not 9 <= len(trials) <= 300 or len(trials) % 3:
        raise ValueError("비교 대상이 없거나 기록된 비교군 범위가 손상되었습니다.")
    by_id = {r["trial_id"]: r for r in trials}
    if len(by_id) != len(trials) or set(mapping) != set(by_id):
        raise ValueError("비교 실행 ID나 눈가림 매핑이 중복/손상되었습니다.")
    cases = {}
    for row in trials:
        private = mapping[row["trial_id"]]
        if not isinstance(private, dict) or not set(private).issubset({"case_id", "arm", "source_fingerprint", "provider", "model", "settings", "note", "source_artifact_sha256"}):
            raise ValueError("눈가림 매핑의 필드가 손상되었습니다.")
        if row["status"] not in ("completed", "failed", "held") or private.get("arm") not in ARMS:
            raise ValueError("비교 상태나 비교군 기록이 손상되었습니다.")
        _number(row.get("cost_usd")); _number(row.get("production_minutes"))
        actual_conditions = hashlib.sha256(json.dumps({"source": private["source_fingerprint"], "request": row["request"],
            "profile": row["reading_profile"], "format": "pptx"}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if actual_conditions != row["conditions_fingerprint"]:
            raise ValueError("비교 자료/질문/환경이 기록된 동일 조건과 달라졌습니다.")
        if not isinstance(row.get("case_number"), int) or isinstance(row["case_number"], bool):
            raise ValueError("비교 사례 번호가 손상되었습니다.")
        cases.setdefault(row["case_number"], []).append(row)
    sources = []
    for group in cases.values():
        if len(group) != 3 or {mapping[r["trial_id"]]["arm"] for r in group} != set(ARMS) or \
                len({r["conditions_fingerprint"] for r in group}) != 1:
            raise ValueError("사례별 비교 조건이나 세 비교군이 손상되었습니다.")
        source = {mapping[r["trial_id"]]["source_fingerprint"] for r in group}
        if len(source) != 1 or not _HEX.fullmatch(next(iter(source))):
            raise ValueError("사례별 원자료 식별값이 손상되었습니다.")
        sources.append(next(iter(source)))
    if len(sources) != len(set(sources)):
        raise ValueError("같은 자료를 독립 사례로 중복 집계할 수 없습니다.")
    judgments = {}
    for entry in (evaluations or {}).get("evaluations", []):
        key = entry.get("trial_id")
        if key not in by_id or key in judgments or by_id[key]["status"] != "completed":
            raise ValueError("실행한 고유 비교 출력만 사람이 판정할 수 있습니다.")
        criteria = entry.get("criteria", {})
        if set(criteria) != set(CRITERIA) or any(x not in (None, "passed", "needs_revision") for x in criteria.values()):
            raise ValueError("다섯 품질 기준마다 통과/수정 필요/미판정을 구분해야 합니다.")
        if any(criteria.values()) and (not str(entry.get("reviewer", "")).strip() or not str(entry.get("note", "")).strip()):
            raise ValueError("판정에는 검수자와 근거가 필요합니다.")
        entry = {**entry, "revision_minutes": _number(entry.get("revision_minutes"))}
        judgments[key] = entry
    rows = []
    for trial in trials:
        row = {**trial, **mapping[trial["trial_id"]], "evaluation": judgments.get(trial["trial_id"])}
        if trial["status"] == "completed":
            p = folder / trial["artifact"]
            if p.parent != folder or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != trial["artifact_sha256"]:
                raise ValueError("눈가림 출력이 바뀌어 기존 사람 판정을 적용할 수 없습니다.")
        rows.append(row)
    costs = [r["cost_usd"] for r in rows]
    minutes = [r["evaluation"]["revision_minutes"] if r["evaluation"] else None for r in rows]
    return {"version": "blind-pilot-v1", "planned_trials": len(rows),
            "completed_trials": sum(r["status"] == "completed" for r in rows),
            "failed_trials": sum(r["status"] == "failed" for r in rows),
            "held_trials": sum(r["status"] == "held" for r in rows),
            "human_evaluated_trials": sum(any(j["criteria"].values()) for j in judgments.values()), "quality_verdict": "pending_user",
            "measured_cost_usd": sum(costs) if all(c is not None for c in costs) else None,
            "measured_revision_minutes": sum(minutes) if all(m is not None for m in minutes) else None,
            "cost_measured_trials": sum(c is not None for c in costs),
            "revision_time_measured_trials": sum(m is not None for m in minutes), "trials": rows}
