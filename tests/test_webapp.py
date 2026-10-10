import hashlib
import http.client
import json
from pathlib import Path
import shutil
import threading

import pytest

from ermclip.models import Profile
from ermclip.util import atomic_json
from ermclip.webapp import Workspace, WorkspaceServer
from ermclip.worker import refresh_settings


@pytest.fixture
def web(settings, monkeypatch):
    config = settings.path / 'config/local.json'
    atomic_json(config, settings.model_dump())
    app = Workspace(settings.path)
    monkeypatch.setattr(app, 'start_worker', lambda: None)
    server = WorkspaceServer(('127.0.0.1', 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, data=None, headers=None, method=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
        body = json.dumps(data) if data is not None else None
        request_headers = {'Content-Type':'application/json', 'X-ERMCLIP-Token': app.token}
        request_headers.update(headers or {})
        connection.request(method or ('POST' if data is not None else 'GET'), path, body, request_headers)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw
        status, returned_headers = response.status, dict(response.getheaders())
        connection.close()
        return status, result, returned_headers
    yield app, request
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_bootstrap_and_settings_never_expose_private_settings(web):
    app, request = web
    status, body, headers = request('/api/bootstrap')
    assert status == 200 and body['app'] == 'ERMCLIP' and len(body['styles']) == 25
    assert 'hermes_home' not in body['settings'] and 'local_llm_url' not in body['settings']
    assert 'Content-Security-Policy' in headers and headers['X-Frame-Options'] == 'DENY'
    status, body, _ = request('/api/settings', {'encoder':'cpu', 'defaults':[Profile(count=2).model_dump()]})
    assert status == 200 and body['saved']
    assert app.settings().defaults[0].count == 2 and app.settings().additional_paid_api_budget == 0


@pytest.mark.parametrize('headers', [
    {'Host':'attacker.example'}, {'Origin':'https://attacker.example'},
    {'Sec-Fetch-Site':'cross-site'}, {'X-ERMCLIP-Token':''}, {'Content-Type':'text/plain'},
])
def test_foreign_or_unauthorized_mutations_do_not_change_settings(web, headers):
    app, request = web
    before = app.config_path.read_bytes()
    status, _, _ = request('/api/settings', {'encoder':'nvenc'}, headers)
    assert status == 403 and app.config_path.read_bytes() == before


@pytest.mark.parametrize('change', [{'root':'C:/Elsewhere'}, {'local_llm_url':'https://provider.example'},
                                     {'additional_paid_api_budget':1}, {'allow_model_download':True}, {'whisper_model':'medium'}])
def test_settings_cannot_change_roots_models_routes_or_download_missing_weights(web, change):
    app, request = web
    before = app.config_path.read_bytes()
    assert request('/api/settings', change)[0] == 400
    assert app.config_path.read_bytes() == before


def test_output_media_ranges_and_path_escape_protection(web):
    app, request = web
    path = app.root / 'output/clip.mp4'
    path.write_bytes(b'0123456789')
    (app.root / 'state/private.json').write_text('{"secret":"not-public"}')
    status, body, headers = request('/media/output/clip.mp4', headers={'Range':'bytes=2-5'})
    assert status == 206 and body == b'2345' and headers['Content-Range'] == 'bytes 2-5/10'
    assert request('/media/output/clip.mp4', headers={'Range':'bytes=-3'})[1] == b'789'
    assert request('/media/output/clip.mp4', headers={'Range':'bytes=99-'})[0] == 416
    assert request('/media/output/clip.mp4', method='HEAD')[1] == b''
    assert request('/media/output/%2e%2e/state/private.json')[0] == 404
    assert request('/media/output/../../config/local.json')[0] == 404


@pytest.mark.integration
def test_select_video_submit_duplicate_and_revision_preserve_source(web, source_video):
    app, request = web
    source = app.root / 'input/video.mp4'
    shutil.copyfile(source_video, source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert request('/api/sources')[1] == []  # Allowed reference files are not imported.
    source_id = request('/api/source/inspect', {'path':str(source), 'allow_new':True})[1]['id']
    status, inspected, _ = request('/api/source/inspect', {'source_id':source_id})
    assert status == 200 and inspected['has_audio'] and inspected['duration'] > 60
    data = {'source_id':source_id, 'instruction':'Create complete shorts.', 'profile':Profile(count=1).model_dump(), 'podcast':True, 'language':'en'}
    status, job, _ = request('/api/submit', data)
    assert status == 200 and job['created']
    duplicate = request('/api/submit', data)[1]
    assert duplicate['created'] is False and duplicate['job'] == job['job']
    stored = app.store.get(job['job'])
    assert stored['status'] == 'queued' and stored['spec']['profiles'][0]['framing'] == 'speaker'
    status, revision, _ = request('/api/jobs/'+job['job']+'/revise', {'instruction':'Create one clip of 30 seconds.'})
    assert status == 200 and revision['job'] != job['job']
    assert app.store.get(revision['job'])['spec']['revision_of'].startswith(job['job'])
    assert request('/api/jobs/'+revision['job']+'/cancel', {})[0] == 200
    assert app.store.get(revision['job'])['status'] == 'cancelled'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.integration
def test_video_picker_registration_permits_only_selected_file(web, source_video):
    app, request = web
    folder = app.root / 'other'
    folder.mkdir()
    video = folder / 'chosen.mp4'
    shutil.copyfile(source_video, video)
    assert request('/api/source/inspect', {'path':str(video)})[0] == 400
    status, body, _ = request('/api/source/inspect', {'path':str(video), 'allow_new':True})
    assert status == 200 and body['name'] == 'chosen.mp4'
    assert str(video) in app.settings().allowed_inputs
    assert str(folder) not in app.settings().allowed_inputs


def test_worker_reload_applies_engine_choices_without_changing_root(settings):
    path = settings.path / 'config/local.json'
    changed = settings.model_copy(update={'encoder':'nvenc','max_model_calls':12})
    atomic_json(path, changed.model_dump())
    reloaded = refresh_settings(settings, path)
    assert reloaded.encoder == 'nvenc' and reloaded.max_model_calls == 12
    assert settings.encoder == 'cpu'  # An active job keeps its original object.
    other = settings.path / 'unexpected-root'
    atomic_json(path, changed.model_copy(update={'root':str(other)}).model_dump())
    with pytest.raises(ValueError, match='root cannot change'):
        refresh_settings(settings, path)
    assert not other.exists()
