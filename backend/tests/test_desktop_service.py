"""The desktop session guards all endpoints; ordinary web mode remains compatible."""
import json

import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

SESSION = 'a' * 64
INSTANCE = 'b' * 32


def desktop_app(tmp_path):
    ui = tmp_path / 'ui'
    ui.mkdir()
    (ui / 'index.html').write_text('<html>synthetic UI</html>')
    return create_app(FileProjectStore(tmp_path / 'projects'), static_dir=ui,
                      desktop_session_token=SESSION, desktop_instance_id=INSTANCE)


def test_desktop_blocks_read_write_and_ui_without_session(tmp_path):
    with TestClient(desktop_app(tmp_path)) as client:
        for method, path in [('get', '/api/health'), ('get', '/api/projects'),
                             ('get', '/'), ('post', '/api/projects')]:
            response = getattr(client, method)(path, headers={'X-Requested-With': 'SlideCaptain'})
            assert response.status_code == 403
            assert SESSION not in response.text
            assert INSTANCE not in response.text


def test_desktop_rejects_wrong_session_even_for_health(tmp_path):
    with TestClient(desktop_app(tmp_path)) as client:
        assert client.get('/api/health', headers={'X-SlideCaptain-Session': 'c' * 64}).status_code == 403


def test_authenticated_desktop_health_identifies_its_process_and_ui(tmp_path):
    with TestClient(desktop_app(tmp_path)) as client:
        response = client.get('/api/health', headers={'X-SlideCaptain-Session': SESSION})
        assert response.status_code == 200
        assert response.json()['desktop_instance_id'] == INSTANCE
        assert response.json()['product'] == 'slidecaptain'
        assert response.json()['ui_ready'] is True
        assert SESSION not in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert client.get('/', headers={'X-SlideCaptain-Session': SESSION}).status_code == 200


def test_session_does_not_bypass_existing_mutation_and_origin_protection(tmp_path):
    with TestClient(desktop_app(tmp_path)) as client:
        headers = {'X-SlideCaptain-Session': SESSION}
        assert client.post('/api/projects', headers=headers, json={'name': 'sample'}).status_code == 403
        headers.update({'X-Requested-With': 'SlideCaptain', 'Origin': 'https://untrusted.example'})
        assert client.post('/api/projects', headers=headers, json={'name': 'sample'}).status_code == 403


def test_web_health_works_without_desktop_header(tmp_path):
    with TestClient(create_app(FileProjectStore(tmp_path))) as client:
        response = client.get('/api/health')
        assert response.status_code == 200
        assert 'desktop_instance_id' not in response.json()


@pytest.mark.parametrize('token,instance', [(SESSION, None), (None, INSTANCE), ('short', INSTANCE)])
def test_desktop_startup_rejects_partial_or_weak_session_configuration(tmp_path, token, instance):
    with pytest.raises(ValueError, match='desktop'):
        create_app(FileProjectStore(tmp_path), desktop_session_token=token, desktop_instance_id=instance)
