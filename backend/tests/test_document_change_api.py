from copy import deepcopy
from fastapi.testclient import TestClient
from test_document_changes import sample
from slidecaptain.server.app import create_app


def setup(store):
    deck,sources=sample()
    for name in ("one","two"):
        store.create_project(name)
        for filename,text in sources.items():store.write_source(name,filename,text)
        store.save_deck(name,deck,snapshot=False)
    client=TestClient(create_app(store),headers={"X-Requested-With":"SlideCaptain"})
    return client,deck,sources


def basis(client,store,name="one"):
    headers={"If-Match":f'"{store.deck_etag(name)}"'}
    response=client.get(f"/api/projects/{name}/document-changes/basis",headers=headers)
    assert response.status_code==200,response.text
    assert response.headers["cache-control"]=="no-store"
    return response.json(),headers


def test_change_preview_snapshot_apply_and_cross_project_token_rejection(store):
    client,deck,sources=setup(store)
    current,headers=basis(client,store)
    candidate=deck.model_dump(mode="json");candidate["slides"][0]["subtitle"]="명시적 교체"
    body={"candidate":candidate,"expected_source_fingerprint":current["sources_fingerprint"]}
    assert client.post("/api/projects/one/document-changes/preview",json=body).status_code==428
    response=client.post("/api/projects/one/document-changes/preview",json=body,headers=headers)
    assert response.status_code==200,response.text
    preview=response.json();assert preview["final_export_allowed"] is False
    assert not store.list_snapshots("one") and store.load_deck("one")==deck
    body.update(candidate=preview["candidate"],confirmation_token=preview["confirmation_token"],
                acknowledged_loss_ids=[item["id"] for item in preview["losses"]])
    assert client.post("/api/projects/two/document-changes/apply",json=body,headers=headers).status_code==422
    missing=deepcopy(body);missing["acknowledged_loss_ids"]=[]
    assert client.post("/api/projects/one/document-changes/apply",json=missing,headers=headers).status_code==422
    saved=client.post("/api/projects/one/document-changes/apply",json=body,headers=headers)
    assert saved.status_code==200,saved.text
    assert saved.headers["etag"].strip('"')==store.deck_etag("one")
    assert len(store.list_snapshots("one"))==1
    assert store.load_deck("one").document_review.requires_independent_review is True
    assert client.post("/api/projects/one/document-changes/apply",json=body,headers=headers).status_code==412


def test_document_basis_and_apply_rejects_allsource_changes(store):
    client,deck,sources=setup(store)
    current,headers=basis(client,store)
    candidate=deck.model_dump(mode="json");candidate["slides"][0]["subtitle"]="새 후보"
    body={"candidate":candidate,"expected_source_fingerprint":current["sources_fingerprint"]}
    response=client.post("/api/projects/one/document-changes/preview",json=body,headers=headers)
    assert response.status_code==200,response.text
    preview=response.json()
    body.update(candidate=preview["candidate"],confirmation_token=preview["confirmation_token"],
                acknowledged_loss_ids=[i["id"] for i in preview["losses"]])
    store.write_source("one","unrelated.md","추가 합성 자료")
    assert client.post("/api/projects/one/document-changes/apply",json=body,headers=headers).status_code==409
    assert store.load_deck("one")==deck and not store.list_snapshots("one")


def test_explicit_migration_uses_old_evidence_hash_and_current_source(store):
    client,deck,sources=setup(store)
    old=deck.structure.story_plan.evidence[0]
    store.write_source("one","moved.md",old.excerpt)
    current,headers=basis(client,store)
    selection=old.model_dump(mode="json",exclude={"excerpt","source_revision"})
    selection.update(source_id="moved.md",locator={"line_start":1,"line_end":len(old.excerpt.splitlines())})
    body={"evidence_id":old.id,"new_selection":selection,"old_evidence_fingerprint":current["evidence_fingerprints"][old.id],
          "expected_source_fingerprint":current["sources_fingerprint"]}
    response=client.post("/api/projects/one/evidence-migrations/preview",json=body,headers=headers)
    assert response.status_code==200,response.text
    result=response.json()
    assert store.load_deck("one")==deck
    body.update(confirmation_token=result["confirmation_token"],acknowledged_loss_ids=[i["id"] for i in result["losses"]])
    applied=client.post("/api/projects/one/evidence-migrations/apply",json=body,headers=headers)
    assert applied.status_code==200,applied.text
    assert store.load_deck("one").structure.story_plan.evidence[0].source_id=="moved.md"
    assert len(store.list_snapshots("one"))==1
