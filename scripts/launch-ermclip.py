"""Open one native ERMCLIP window. Start only its small loopback service at sign-in."""
from __future__ import annotations

import argparse
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def matches_page(url: str, folder: Path) -> bool:
    """Reuse only a server that returns this page, without using a proxy."""
    try:
        expected = (folder / 'index.html').read_bytes()
        if len(expected) > 2 * 1024 * 1024:
            return False
        with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=2) as response:
            return response.status == 200 and response.read(len(expected) + 1) == expected
    except (OSError, ValueError):
        return False


def ensure_page(folder: Path, port: int, python: Path, logs: Path) -> tuple[str, bool]:
    url = f'http://127.0.0.1:{port}/'
    if not (folder / 'index.html').is_file():
        raise RuntimeError(f'The local page is missing: {folder / "index.html"}')
    if matches_page(url, folder):
        return url, False
    try:
        connection = socket.create_connection(('127.0.0.1', port), timeout=1)
    except OSError:
        pass
    else:
        connection.close()
        raise RuntimeError(f'Port {port} belongs to another page. No process was stopped.')
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / f'local-page-{port}.log').open('ab') as stream:
        process = subprocess.Popen(
            [str(python), '-m', 'http.server', str(port), '--bind', '127.0.0.1',
             '--directory', str(folder)],
            cwd=folder, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
            creationflags=NO_WINDOW,
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if matches_page(url, folder):
            return url, True
        if process.poll() is not None:
            break
        time.sleep(0.2)
    # This is the specific child started above, never an existing page server.
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    raise RuntimeError(f'Page {port} did not start. Check logs/local-page-{port}.log.')


def workspace_ready(root: Path):
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open('http://127.0.0.1:8090/api/bootstrap', timeout=3) as response:
            body = json.loads(response.read(2_000_000))
        return body.get('app') == 'ERMCLIP' and body.get('instance') == hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    except (OSError, ValueError):
        return False


def ensure_workspace(root: Path, python: Path):
    url = 'http://127.0.0.1:8090/'
    if workspace_ready(root):
        return url, False
    try:
        connection = socket.create_connection(('127.0.0.1', 8090), timeout=1)
    except OSError:
        pass
    else:
        connection.close()
        raise RuntimeError('Port 8090 belongs to another application. No process was stopped.')
    environment = dict(os.environ, PYTHONPATH=str(root / 'src'))
    with (root / 'logs/workspace.log').open('ab') as log:
        process = subprocess.Popen([str(python), '-m', 'ermclip.webapp'], cwd=root, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=NO_WINDOW)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if workspace_ready(root):
            return url, True
        if process.poll() is not None:
            break
        time.sleep(.2)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    raise RuntimeError('The workspace did not start. Check logs/workspace.log.')


@contextmanager
def launch_lock(root: Path):
    """Serialize a sign-in launch and a desktop click without duplicate servers."""
    import msvcrt
    lock_path = root / 'state' / 'pages-launch.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Another ERMCLIP launcher is still starting the pages.')
                time.sleep(0.2)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def ensure_worker(root: Path):
    # Task Scheduler owns the installed worker. IgnoreNew prevents duplicate jobs.
    with (root / 'logs/desktop-worker-start.log').open('ab') as stream:
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy',
             'Bypass', '-File', str(root / 'scripts/start-desktop-worker.ps1')],
            cwd=root, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
            creationflags=NO_WINDOW,
        )


def pending_work(root: Path):
    """Resume persisted work after restart, without loading an idle model."""
    database = root / 'state/jobs.sqlite3'
    if not database.is_file():
        return False
    try:
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
            paused = db.execute("SELECT value FROM controls WHERE key='pause'").fetchone()
            if paused and paused[0] == '1':
                return False
            return bool(db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','retry','running') AND cancel=0 LIMIT 1").fetchone())
    except sqlite3.Error:
        return False


def open_window(root: Path):
    """Use the installed Edge WebView2 runtime; do not launch a browser."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    handle = kernel.CreateMutexW(None, False, 'Local\\ERMCLIPDesktop-' + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if ctypes.get_last_error() == 183:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user.FindWindowW.restype = wintypes.HWND
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.SetForegroundWindow.argtypes = [wintypes.HWND]
            window = user.FindWindowW(None, 'ERMCLIP — Local Video Studio')
            if window:
                user.ShowWindow(window, 9)
                user.SetForegroundWindow(window)
            return
        import webview
        storage = root / 'cache/desktop-webview'
        storage.mkdir(parents=True, exist_ok=True)
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
        webview.settings['ALLOW_DOWNLOADS'] = True
        # No bridge exposes filesystem or shell commands to the page.
        webview.create_window('ERMCLIP — Local Video Studio', 'http://127.0.0.1:8090/',
                              width=1260, height=880, min_size=(900, 660),
                              background_color='#edf1f4', text_select=True)
        (root / 'state/desktop-window.json').write_text(json.dumps({
            'pid': os.getpid(), 'time': time.time(), 'engine': 'edgechromium',
            'title': 'ERMCLIP — Local Video Studio', 'browser_opened': False}), encoding='utf-8')
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(storage), debug=False)
    finally:
        kernel.CloseHandle(handle)


def launch(root: Path, background: bool):
    if os.name != 'nt':
        raise RuntimeError('The desktop launcher requires Windows.')
    python = root / '.venv/Scripts/python.exe'
    if not python.is_file():
        raise RuntimeError('Run scripts/setup.ps1 before installing the desktop launcher.')
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    ready, errors = [], []
    with launch_lock(root):
        url, started = ensure_workspace(root, python)
        ready.append({'url': url, 'started': started})
        if pending_work(root):
            ensure_worker(root)
        report = {'time': time.time(), 'pages': ready, 'errors': errors, 'background': background}
        (root / 'state/local-pages.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not background:
        open_window(root)
    if errors:
        raise RuntimeError('\n'.join(errors))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--background', action='store_true', help='Start only the loopback UI service. Do not load models.')
    args = parser.parse_args()
    try:
        report = launch(ROOT, args.background)
        if sys.stdout:
            print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        (ROOT / 'logs').mkdir(parents=True, exist_ok=True)
        with (ROOT / 'logs/desktop-launcher.log').open('a', encoding='utf-8') as stream:
            stream.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {type(exc).__name__}: {exc}\n')
        if not args.background and os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(exc), 'ERMCLIP could not open all pages', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
