import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest


spec = importlib.util.spec_from_file_location('desktop_launcher', Path(__file__).resolve().parents[1] / 'scripts/launch-ermclip.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_restart_loads_engine_only_for_unpaused_pending_work(settings):
    from ermclip.store import Store
    from ermclip.models import JobSpec
    store=Store(settings.path/'state/jobs.sqlite3')
    assert not launcher.pending_work(settings.path)
    job,_=store.submit(JobSpec(source='fixture.mp4'),'restart-fixture')
    assert launcher.pending_work(settings.path)
    store.control('pause','1')
    assert not launcher.pending_work(settings.path)
    store.control('pause','0')
    store.update(job,status='running')
    assert launcher.pending_work(settings.path)
    store.update(job,status='completed')
    assert not launcher.pending_work(settings.path)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture
def existing_server(tmp_path):
    folder = tmp_path / 'actual'
    folder.mkdir()
    (folder / 'index.html').write_text('<title>Actual local page</title>')
    port = free_port()
    process = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1', '--directory', str(folder)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=launcher.NO_WINDOW)
    url = f'http://127.0.0.1:{port}/'
    try:
        deadline = time.monotonic() + 10
        while not launcher.matches_page(url, folder):
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.1)
        yield folder, port, process
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_repeated_launch_reuses_matching_server(existing_server, tmp_path, monkeypatch):
    folder, port, process = existing_server
    def no_duplicate(*args, **kwargs):
        pytest.fail('A matching server must not spawn another process')
    monkeypatch.setattr(launcher.subprocess, 'Popen', no_duplicate)
    for _ in range(2):
        url, started = launcher.ensure_page(folder, port, Path(sys.executable), tmp_path / 'logs')
        assert started is False and url == f'http://127.0.0.1:{port}/'
    assert process.poll() is None


def test_occupied_port_does_not_reuse_or_stop_other_server(existing_server, tmp_path):
    _, port, process = existing_server
    requested = tmp_path / 'requested'
    requested.mkdir()
    (requested / 'index.html').write_text('<title>Different requested page</title>')
    with pytest.raises(RuntimeError, match='belongs to another page'):
        launcher.ensure_page(requested, port, Path(sys.executable), tmp_path / 'logs')
    assert process.poll() is None


def test_missing_page_does_not_start_server(tmp_path):
    with pytest.raises(RuntimeError, match='page is missing'):
        launcher.ensure_page(tmp_path, free_port(), Path(sys.executable), tmp_path / 'logs')
