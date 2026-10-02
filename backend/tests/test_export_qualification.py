"""Qualification requires independent proof for the exact published bytes."""

import hashlib
import hmac
import json
import io
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

from test_export_history import publish
from PIL import Image


def qualification_url(exported):
    return f"/api/projects/synthetic/exports/{quote(Path(exported['path']).stem, safe='')}/qualification"


def test_qualification_is_read_only_and_native_not_run_blocks_final(client, store):
    exported = publish(client, store)
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    response = client.get(qualification_url(exported))
    assert response.status_code == 200
    data = response.json()
    assert data['final_export_allowed'] is False
    assert data['render_status'] == 'not_run'
    assert data['independent_review_status'] == 'not_run'
    assert data['blockers']
    assert response.headers['cache-control'] == 'no-store'
    assert {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()} == before


def test_qualification_writes_require_explicit_basis_and_reject_client_approval(client, store):
    exported = publish(client, store)
    base = qualification_url(exported).removesuffix('/qualification')
    request = {'expected_input_fingerprint': exported['quality']['input_fingerprint'],
               'expected_artifact_sha256': exported['quality']['artifact_sha256']}
    assert client.post(base + '/render', json=request).status_code == 428
    assert client.post(base + '/render', json={**request, 'renderer':'PowerPoint'}).status_code == 422
    assert client.post(base + '/publish-final', json={**request, 'approved': True}).status_code == 422


def test_signature_requires_configured_independent_identity_and_exact_canonical_payload():
    from slidecaptain.export.qualification import QualificationConflict, canonical_receipt, verify_signature
    from slidecaptain.models.export_qualification import IndependentReceipt
    receipt = IndependentReceipt(
        receipt_type='independent-review', rule_version='independent-review-v1',
        reviewer_id='reader', run_id='b'*32, producer_run_id='a'*32,
        input_fingerprint='c'*64, artifact_sha256='d'*64, render_id='e'*32,
        render_fingerprint='7'*64,
        environment_fingerprint='f'*64, pages=[1],
        verdicts=[{'category': c, 'status': 'passed', 'note': '실제 전체 출력과 근거를 대조함'}
                  for c in ('narrative','evidence','representation','visual','target_renderer')], findings=[],
    )
    key = '01'*32
    signature = hmac.new(bytes.fromhex(key), canonical_receipt(receipt), hashlib.sha256).hexdigest()
    registry = {'version':1, 'reviewers': {'reader': {'key_hex':key,'role':'independent'}}}
    verify_signature(receipt, signature, registry)
    with pytest.raises(QualificationConflict):
        verify_signature(receipt.model_copy(update={'artifact_sha256':'a'*64}), signature, registry)
    with pytest.raises(QualificationConflict):
        verify_signature(receipt, signature, {'version':1,'reviewers':{}})
    with pytest.raises(QualificationConflict):
        verify_signature(receipt.model_copy(update={'reviewer_id':'slidecaptain'}), signature, registry)
    with pytest.raises(QualificationConflict):
        verify_signature(receipt.model_copy(update={'run_id':receipt.producer_run_id}), signature, registry)
    with pytest.raises(QualificationConflict):
        verify_signature(receipt, signature, {'version':1,'reviewers':{
            'reader': {'key_hex':key,'role':'independent'}, 'other': {'key_hex':key,'role':'independent'}}})


def ready_native(client, store, monkeypatch):
    from slidecaptain.export import renderer
    exported = publish(client, store)
    key = '12'*32
    (store.root/'review-trust.json').write_text(json.dumps({'version':1, 'reviewers':{
        'reader': {'key_hex':key, 'role':'independent'}}}), encoding='utf-8')
    environment = {'fingerprint':'f'*64, 'renderer':'Microsoft PowerPoint',
                   'powerpoint_version':'16.0', 'powerpoint_build':'1234',
                   'installed_fonts_sha256':'9'*64, 'executable_sha256':'8'*64}
    monkeypatch.setattr(renderer, 'current_environment', lambda: environment)
    stream = io.BytesIO()
    Image.new('RGB', (16,9), 'white').save(stream, format='PNG')
    png = stream.getvalue()
    monkeypatch.setattr(renderer, 'render_powerpoint', lambda source, destination, count: (environment,[png]*count))
    base = qualification_url(exported).removesuffix('/qualification')
    state = client.get(base+'/qualification').json()
    request = {'expected_input_fingerprint':state['input_fingerprint'], 'expected_artifact_sha256':state['artifact_sha256']}
    response = client.post(base+'/render', headers={'If-Match':state['base_etag']},json=request)
    assert response.status_code == 200, response.text
    rendered = response.json()
    assert rendered['render_status'] == 'rendered'
    return exported, base, rendered, request, key


def signed_request(state, request, key, **updates):
    from slidecaptain.export.qualification import canonical_receipt
    from slidecaptain.models.export_qualification import IndependentReceipt
    data = {'receipt_type':'independent-review','rule_version':'independent-review-v1','reviewer_id':'reader',
            'run_id':uuid.uuid4().hex,'producer_run_id':state['provenance']['producer_run_id'],
            'input_fingerprint':state['input_fingerprint'],'artifact_sha256':state['artifact_sha256'],
            'render_id':state['render']['id'],'environment_fingerprint':state['render']['environment_fingerprint'],
            'render_fingerprint':state['render']['render_fingerprint'],
            'pages':list(range(1,state['slide_count']+1)),
            'verdicts':[{'category':category,'status':'passed','note':'전체 페이지와 근거 대조 완료'}
                        for category in ('narrative','evidence','representation','visual','target_renderer')],
            'findings':[], **updates}
    receipt = IndependentReceipt.model_validate(data)
    signature = hmac.new(bytes.fromhex(key),canonical_receipt(receipt),hashlib.sha256).hexdigest()
    return {**request, 'receipt':receipt.model_dump(), 'signature':signature}


def import_review(client, base, state, body):
    return client.post(base+'/independent-reviews', headers={'If-Match':state['base_etag']},json=body)


def test_signed_review_allows_only_same_bytes_and_final_copy_has_independent_inode(client, store, monkeypatch):
    exported, base, state, request, key = ready_native(client, store, monkeypatch)
    body = signed_request(state, request, key)
    response = import_review(client,base,state,body)
    assert response.status_code == 200, response.text
    reviewed = response.json()
    assert reviewed['independent_review_status'] == 'passed'
    assert reviewed['final_export_allowed'] is True, reviewed['blockers']
    assert import_review(client,base,state,body).status_code == 409  # replayed run ID
    submitted = client.post(base+'/publish-final',headers={'If-Match':state['base_etag']},json=request)
    assert submitted.status_code == 200, submitted.text
    final = Path(submitted.json()['pptx_path'])
    original = Path(exported['path'])
    original_bytes = original.read_bytes()
    assert final.read_bytes() == original_bytes
    assert (final.stat().st_dev, final.stat().st_ino) != (original.stat().st_dev, original.stat().st_ino)
    assert Path(submitted.json()['receipt_path']).exists()
    original.write_bytes(original_bytes+b'changed')
    assert final.read_bytes() == original_bytes
    assert client.get(base+'/qualification').json()['final_export_allowed'] is False


def test_latest_signed_failure_and_render_failure_never_restore_old_pass(client, store, monkeypatch):
    from slidecaptain.export import renderer
    exported, base, state, request, key = ready_native(client, store, monkeypatch)
    assert import_review(client,base,state,signed_request(state,request,key)).json()['final_export_allowed'] is True
    failed = signed_request(state,request,key,findings=[{'code':'bad-evidence','severity':'critical',
                                                        'pages':[1],'note':'근거 누락','resolved':False}])
    response = import_review(client,base,state,failed)
    assert response.status_code == 200
    assert response.json()['independent_review_status'] == 'needs_revision'
    assert response.json()['final_export_allowed'] is False
    def unavailable(*args):
        raise renderer.RenderUnavailable('PowerPoint 환경 없음')
    monkeypatch.setattr(renderer,'render_powerpoint', unavailable)
    response = client.post(base+'/render',headers={'If-Match':state['base_etag']},json=request)
    assert response.status_code == 200
    assert response.json()['render_status'] == 'not_run'
    assert response.json()['final_export_allowed'] is False
    assert client.get(base+'/qualification').json()['render_status'] == 'not_run'


@pytest.mark.parametrize('kind',['signature','producer','artifact','pages','run','render','render_fingerprint','environment','identity'])
def test_signed_receipt_wrong_basis_or_signature_cannot_be_imported(client, store, monkeypatch,kind):
    exported, base, state, request, key = ready_native(client,store,monkeypatch)
    changes = {'producer':{'producer_run_id':'0'*32}, 'artifact':{'artifact_sha256':'0'*64},
               'pages':{'pages':[2]},'run':{'run_id':state['provenance']['producer_run_id']},
               'render':{'render_id':'0'*32},'environment':{'environment_fingerprint':'0'*64},
               'render_fingerprint':{'render_fingerprint':'0'*64},
               'identity':{'reviewer_id':'slidecaptain'}}
    body = signed_request(state,request,key,**changes.get(kind,{}))
    if kind == 'signature':
        body['signature']='0'*64
    assert import_review(client,base,state,body).status_code == 409
    assert client.get(base+'/qualification').json()['independent_review_status']=='not_run'


@pytest.mark.parametrize('damage',['registry','event','image','provenance','manual','preflight','environment'])
def test_damage_revocation_and_latest_manual_failure_fail_closed(client,store,monkeypatch,damage):
    from slidecaptain.export import renderer
    exported,base,state,request,key=ready_native(client,store,monkeypatch)
    assert import_review(client,base,state,signed_request(state,request,key)).json()['final_export_allowed'] is True
    directory=Path(exported['path']).parent
    if damage=='registry':
        (store.root/'review-trust.json').write_text('{"version":1,"reviewers":{}}')
    elif damage=='event':
        sorted(directory.glob('*.qualification.*.json'))[-1].write_text('{}')
    elif damage=='image':
        (directory/state['render']['pages'][0]['filename']).write_bytes(b'broken')
    elif damage=='provenance':
        Path(exported['path']).with_suffix('.provenance.json').unlink()
    elif damage=='manual':
        body={**request,'category':'visual','status':'needs_revision','reviewer':'reader', 'note':'읽기 어려움','pages':[1]}
        assert client.post(base+'/reviews',headers={'If-Match':state['base_etag']},json=body).status_code==200
    elif damage=='preflight':
        path=Path(exported['quality_path'])
        quality=json.loads(path.read_text())
        quality['checks'][0]['status']='failed'
        path.write_text(json.dumps(quality))
    else:
        monkeypatch.setattr(renderer,'current_environment',lambda:{'fingerprint':'0'*64})
    damaged=client.get(base+'/qualification').json()
    assert damaged['final_export_allowed'] is False
    assert client.post(base+'/publish-final',headers={'If-Match':state['base_etag']},json=request).status_code==409
    assert not list(directory.glob('*.final.*.pptx'))


@pytest.mark.parametrize('deleted_prefix',['qualification', 'qualification-witness'])
def test_latest_failure_event_or_witness_deletion_cannot_restore_old_pass(client,store,monkeypatch,deleted_prefix):
    exported,base,state,request,key=ready_native(client,store,monkeypatch)
    assert import_review(client,base,state,signed_request(state,request,key)).json()['final_export_allowed'] is True
    failed=signed_request(state,request,key,findings=[{'code':'critical','severity':'critical',
                                                      'pages':[1],'note':'실제 수정 필요','resolved':False}])
    assert import_review(client,base,state,failed).json()['final_export_allowed'] is False
    sorted(Path(exported['path']).parent.glob(f'*.{deleted_prefix}.*.json'))[-1].unlink()
    observed=client.get(base+'/qualification').json()
    assert observed['storage_status']=='invalid'
    assert observed['final_export_allowed'] is False
    assert client.post(base+'/publish-final',headers={'If-Match':state['base_etag']},json=request).status_code==409


def test_legacy_output_and_event_symlink_never_create_target_files(client,store,tmp_path):
    exported=publish(client,store)
    Path(exported['path']).with_suffix('.provenance.json').unlink()
    base=qualification_url(exported).removesuffix('/qualification')
    state=client.get(base+'/qualification').json()
    request={'expected_input_fingerprint':state['input_fingerprint'],'expected_artifact_sha256':state['artifact_sha256']}
    assert state['provenance'] is None and state['can_render'] is False
    assert client.post(base+'/render',headers={'If-Match':state['base_etag']},json=request).status_code==409
    outside=tmp_path/'outside.json'
    outside.write_text('{"foreign":true}')
    name=Path(exported['path']).parent/(Path(exported['path']).stem+'.qualification.00000001.json')
    try:
        name.symlink_to(outside)
    except OSError:
        pytest.skip('파일 심볼릭 링크를 만들 수 없는 디바이스')
    assert client.get(base+'/qualification').json()['storage_status']=='invalid'
    assert outside.read_text()=='{"foreign":true}'


def test_unexpected_native_io_failure_leaves_latest_failure_instead_of_old_pass(client,store,monkeypatch):
    from slidecaptain.export import renderer
    exported,base,state,request,key=ready_native(client,store,monkeypatch)
    assert import_review(client,base,state,signed_request(state,request,key)).json()['final_export_allowed'] is True
    def io_failed(*args):
        raise OSError('simulated native runner filesystem failure')
    monkeypatch.setattr(renderer,'render_powerpoint',io_failed)
    response=client.post(base+'/render',headers={'If-Match':state['base_etag']},json=request)
    assert response.status_code==200
    assert response.json()['render_status']=='failed'
    assert client.get(base+'/qualification').json()['final_export_allowed'] is False
