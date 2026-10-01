import json
from pathlib import Path

import pytest

from slidecaptain.pipeline.blind_pilot import prepare_blind_pilot, read_blind_pilot_report


def _spec():
    return {"cases": [{"case_id": f"case-{i}", "source_fingerprint": str(i) * 64,
        "request": "Synthetic decision question", "reading_profile": "report", "outputs": [
            {"arm": arm, "status": "held", "note": "Awaiting authorized generation"}
            for arm in ("general-agent", "previous", "improved")]} for i in (1, 2, 3)]}


def test_missing_measurements_and_failed_trials_stay_in_denominator(tmp_path):
    spec = _spec()
    spec["cases"][0]["outputs"][0]["status"] = "failed"
    folder = tmp_path / "pilot"
    prepare_blind_pilot(spec, folder)
    report = read_blind_pilot_report(folder)
    assert report["planned_trials"] == 9
    assert report["failed_trials"] == 1
    assert report["held_trials"] == 8
    assert report["quality_verdict"] == "pending_user"
    assert report["measured_cost_usd"] is None
    assert report["measured_revision_minutes"] is None


def test_same_material_versions_do_not_count_as_independent_cases(tmp_path):
    spec = _spec()
    spec["cases"][1]["source_fingerprint"] = spec["cases"][0]["source_fingerprint"]
    with pytest.raises(ValueError, match="독립"):
        prepare_blind_pilot(spec, tmp_path / "pilot")
    assert not (tmp_path / "pilot").exists()


def test_zero_target_is_not_passed(tmp_path):
    with pytest.raises(ValueError):
        prepare_blind_pilot({"cases": []}, tmp_path / "pilot")


def test_blinded_html_never_reveals_arm_or_provider(tmp_path):
    folder = tmp_path / "pilot"
    prepare_blind_pilot(_spec(), folder)
    html = (folder / "index.html").read_text(encoding="utf-8")
    for secret in ("general-agent", "previous", "improved"):
        assert secret not in html
    assert "quality_verdict" not in html
    assert (folder / "private-mapping.json").exists()


def test_existing_pilot_never_overwritten(tmp_path):
    folder = tmp_path / "pilot"
    prepare_blind_pilot(_spec(), folder)
    before = (folder / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepare_blind_pilot(_spec(), folder)
    assert (folder / "manifest.json").read_bytes() == before


def test_held_trial_cannot_be_scored_as_success(tmp_path):
    folder = tmp_path / "pilot"
    prepare_blind_pilot(_spec(), folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    trial = manifest["trials"][0]
    with pytest.raises(ValueError):
        read_blind_pilot_report(folder, {"evaluations": [{"trial_id": trial["trial_id"],
            "reviewer": "reader", "criteria": {}, "note": "unchecked"}]})


def test_negative_or_boolean_measurements_rejected(tmp_path):
    spec = _spec()
    spec["cases"][0]["outputs"][0]["cost_usd"] = True
    with pytest.raises(ValueError):
        prepare_blind_pilot(spec, tmp_path / "pilot")
