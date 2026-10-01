"""The review kit must be reproducible, editable, and isolated from old runs."""

import hashlib
import importlib.util
import json
from pathlib import Path

from pptx import Presentation


def test_review_kit_exports_all_pages_and_keeps_previous_run(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/prepare_windows_review.py"
    spec = importlib.util.spec_from_file_location("windows_review_kit", script)
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    first = kit.prepare(tmp_path)
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ai_calls"] == 0 and manifest["human_status"] == "not_run"
    assert len(manifest["artifacts"]) == 5
    assert sum(len(a["pages"]) for a in manifest["artifacts"]) == 15
    originals = {}
    for item in manifest["artifacts"]:
        path = first / item["file"]
        originals[path] = path.read_bytes()
        assert hashlib.sha256(originals[path]).hexdigest() == item["sha256"]
        pptx = Presentation(path)
        assert len(pptx.slides) == len(item["pages"])
        if item["id"] in ("bar", "column"):
            charts = [s.chart for s in pptx.slides[0].shapes if s.has_chart]
            assert len(charts) == 1
            assert charts[0].series[0].values == (1200.0, 1000.0)
        quality = json.loads(path.with_suffix(".quality.json").read_text(encoding="utf-8"))
        assert quality["final_export_allowed"] is False
    saved_feedback = first / "feedback.json"
    saved_feedback.write_text('{"note":"keep my feedback"}', encoding="utf-8")
    second = kit.prepare(tmp_path)
    assert second != first and second.exists()
    assert saved_feedback.read_text(encoding="utf-8") == '{"note":"keep my feedback"}'
    assert all(p.read_bytes() == data for p, data in originals.items())
    form = (first / "index.html").read_text(encoding="utf-8")
    assert "__REVIEW_MANIFEST__" not in form
    assert manifest["artifacts"][0]["sha256"] in form
