import json

from slidecaptain.__main__ import main


def test_cli_uses_same_currentness_basis_and_does_not_publish_without_proofs(client, store, tmp_path, capsys):
    from slidecaptain.models.deck import BulletBoxSlots, Slide
    store.create_project("p", "Synthetic")
    deck = store.load_deck("p")
    from slidecaptain.models.deck import Chapter
    deck.structure.chapters = [Chapter(id="c1", topic="Synthetic", template="bullet_box")]
    deck.slides = [Slide(chapter_id="c1", slots=BulletBoxSlots(bullets=[], conclusion="Synthetic draft"))]
    store.save_deck("p", deck)
    result = client.post("/api/projects/p/export").json()
    export_id = __import__("pathlib").Path(result["path"]).stem
    deck_path = store.root / "p/deck.json"
    assert main(["qualification", str(deck_path), export_id]) == 2
    basis = json.loads(capsys.readouterr().out)
    assert basis["final_export_allowed"] is False
    path = tmp_path / "basis.json"
    path.write_text(json.dumps(basis), encoding="utf-8")
    assert main(["publish-final", str(deck_path), export_id, "--basis", str(path)]) == 1
    assert not list((store.root / "p/exports").glob("*.final.*.pptx"))


def test_cli_pilot_counts_held_work_without_scoring_it(tmp_path, capsys):
    spec = {"cases": [{"case_id": str(i), "source_fingerprint": str(i) * 64, "request": "question",
        "reading_profile": "report", "outputs": [{"arm": arm, "status": "held", "note": "not_run"}
        for arm in ("general-agent", "previous", "improved")]} for i in (1, 2, 3)]}
    path = tmp_path / "spec.json"; path.write_text(json.dumps(spec))
    folder = tmp_path / "pilot"
    assert main(["pilot", "prepare", str(path), "--out", str(folder)]) == 0
    capsys.readouterr()
    assert main(["pilot", "report", str(folder)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["planned_trials"] == 9 and report["held_trials"] == 9
    assert report["human_evaluated_trials"] == 0 and report["quality_verdict"] == "pending_user"
