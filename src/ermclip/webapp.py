"""Loopback-only desktop workspace. No cloud calls, uploads, or shell commands from users."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import unquote, urlsplit

from .caption_styles import catalog, PRESET_IDS
from .config import ROOT, Settings, load
from .models import Conditions, JobSpec, Profile
from .store import Store
from .util import atomic_json, validate_input

VIDEOS = {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}
PUBLIC_OUTPUTS = VIDEOS | {'.srt', '.ass', '.jpg', '.jpeg', '.png', '.json', '.md'}


class Workspace:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.config_path = self.root / 'config/local.json'
        self.settings = lambda: load(self.config_path)
        self.store = Store(self.root / 'state/jobs.sqlite3')
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.picker_lock = threading.Lock()
        self.inspections = {}
        self.model_check = (0, False)

    def save_settings(self, changes):
        permitted = {'defaults', 'encoder', 'whisper_model', 'whisper_device', 'max_model_calls'}
        if not isinstance(changes, dict) or not changes or not changes.keys() <= permitted:
            raise ValueError('Only the displayed output and engine settings can be changed.')
        with self.lock:
            current = self.settings()
            if 'whisper_model' in changes and changes['whisper_model'] != current.whisper_model:
                if changes['whisper_model'] not in self.cached_speech_models():
                    raise ValueError('Download these speech weights locally before selecting this model.')
            updated = Settings.model_validate({**current.model_dump(), **changes})
            if updated.path != self.root:
                raise ValueError('The application root cannot be changed here.')
            atomic_json(self.config_path, updated.model_dump())
        return {'saved': True, 'message': 'Saved. Changes apply before the next job.', 'settings': self.public_settings()}

    def cached_speech_models(self):
        found = []
        for model in ('base', 'small', 'medium', 'large-v3'):
            folders = (self.root / 'cache/models').glob(f'models--*--faster-whisper-{model}/snapshots/*/model.bin')
            if any(f.is_file() for f in folders):
                found.append(model)
        return found

    def public_settings(self):
        s = self.settings()
        return {key: getattr(s, key) for key in ('encoder', 'whisper_model', 'whisper_device', 'max_model_calls')} | {
            'defaults': [p.model_dump() for p in s.defaults], 'director_model': s.director_model,
            'critic_model': s.critic_model, 'telegram_enabled': s.telegram_enabled,
            'paid_api_cost': 0, 'cached_speech_models': self.cached_speech_models(),
        }

    def sources(self):
        import hashlib
        s = self.settings()
        # The allow-list is an access boundary, not a pre-populated UI library.
        # Only files deliberately imported in this interface appear here.
        try:
            paths = set(json.loads((self.root / 'state/ui-imports.json').read_text()))
        except (OSError, ValueError, TypeError):
            paths = set()
        result = []
        known = {str(Path(p).resolve()) for p in s.podcast_sources}
        for item in sorted(paths):
            try:
                p = validate_input(item, s.allowed_inputs)
                result.append({'id': hashlib.sha256(str(p).encode()).hexdigest()[:20], 'path': str(p),
                               'name': p.name, 'bytes': p.stat().st_size, 'podcast': str(p) in known})
            except (ValueError, OSError):
                continue
        return sorted(result, key=lambda r: r['name'].lower())

    def source(self, source_id):
        for item in self.sources():
            if item['id'] == source_id:
                return item
        raise ValueError('Select a video from the local library first.')

    def inspect_source(self, data):
        if set(data) - {'source_id', 'path', 'allow_new'}:
            raise ValueError('Unknown source selection fields.')
        if data.get('source_id'):
            p = Path(self.source(data['source_id'])['path'])
        else:
            p = Path(str(data.get('path', ''))).expanduser().resolve(strict=True)
        if not p.is_file() or p.suffix.lower() not in VIDEOS:
            raise ValueError('Select a complete local video file.')
        settings = self.settings()
        try:
            validate_input(p, settings.allowed_inputs)
        except ValueError:
            if data.get('allow_new') is not True:
                raise ValueError('Use Add video to permit this exact file in the local library.')
        from .media import probe
        stamp = (str(p), p.stat().st_size, p.stat().st_mtime_ns)
        info = self.inspections.get(stamp)
        if info is None:
            info = probe(p)
            self.inspections[stamp] = info
        with self.lock:
            settings = self.settings()
            try:
                validate_input(p, settings.allowed_inputs)
            except ValueError:
                if data.get('allow_new') is not True:
                    raise
                settings.allowed_inputs.append(str(p))  # Permit one file, not its entire folder.
                atomic_json(self.config_path, settings.model_dump())
            imports = {item['path'] for item in self.sources()}
            imports.add(str(p))
            atomic_json(self.root / 'state/ui-imports.json', sorted(imports))
        item = next(item for item in self.sources() if item['path'] == str(p))
        thumb = self.root / 'cache/ui' / f'{item["id"]}-{stamp[2]}.jpg'
        if not thumb.exists():
            from .util import run
            thumb.parent.mkdir(parents=True, exist_ok=True)
            try:
                run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(min(10, info['duration']/2)),
                     '-i', str(p), '-frames:v', '1', '-vf', 'scale=960:-2', str(thumb)], timeout=30)
            except (RuntimeError, OSError, TimeoutError):
                pass
        return {**item, 'duration': info['duration'], 'width': info['width'], 'height': info['height'],
                'has_audio': bool(info.get('audio')), 'video_url': f'/media/source/{item["id"]}',
                'thumbnail_url': f'/media/thumbnail/{item["id"]}' if thumb.exists() else None}

    def native_picker(self):
        if os.name != 'nt':
            raise ValueError('Paste a local video path on this platform.')
        if not self.picker_lock.acquire(blocking=False):
            raise ValueError('The Windows video picker is already open.')
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-WindowStyle', 'Hidden',
                                     '-ExecutionPolicy', 'Bypass', '-File', str(self.root / 'scripts/pick-video.ps1')],
                                    capture_output=True, text=True, encoding='utf-8', timeout=300,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise ValueError('The video picker timed out. Try again or paste a full video path.') from None
        finally:
            self.picker_lock.release()
        if result.returncode:
            raise ValueError('The video picker did not open. Paste the full video path instead.')
        path = result.stdout.strip()
        return {'cancelled': True} if not path else self.inspect_source({'path': path, 'allow_new': True})

    def status(self):
        try:
            health = json.loads((self.root / 'state/health.json').read_text())
            health['stale'] = time.time() - health.get('time', 0) > 15
        except (OSError, ValueError):
            health = {'status': 'not_started', 'stale': True, 'active_job': None}
        now = time.monotonic()
        if now - self.model_check[0] > 5:
            s = self.settings()
            if s.managed_local_model:
                from .local_runtime import ready
                model_ready = ready(s)
            else:
                model_ready = None
            self.model_check = (now, model_ready)
        jobs = self.store.list(100)
        return {'worker': health, 'paused': self.store.control('pause') == '1',
                'model_ready': self.model_check[1], 'model': self.settings().director_model,
                'queued': sum(j['status'] in ('queued', 'retry') for j in jobs), 'paid_api_cost': 0}

    def jobs(self):
        with self.store.connect() as db:
            rows = db.execute('SELECT id,status,stage,created,updated,error,output,spec FROM jobs ORDER BY created DESC LIMIT 60').fetchall()
        result = []
        for row in rows:
            item = dict(row)
            spec = json.loads(item.pop('spec'))
            item.update(source=Path(spec['source']).name, instruction=spec['instruction'], profiles=spec['profiles'])
            result.append(item)
        return result

    def submit(self, data):
        if set(data) - {'source_id', 'instruction', 'profile', 'podcast', 'language', 'conditions'}:
            raise ValueError('Unknown editing request fields.')
        source = self.source(data['source_id'])
        spec = JobSpec(source=source['path'], instruction=data['instruction'], profiles=[Profile.model_validate(data['profile'])],
                       podcast_mode='on' if data.get('podcast') else 'off', transcript_language=data.get('language') or None,
                       conditions=Conditions.model_validate(data.get('conditions', {})),
                       mode='TARGETED' if data.get('conditions', {}).get('keywords') else 'AUTO')
        from .worker import submit
        job, created = submit(spec, self.settings(), self.store)
        self.start_worker()
        return {'job': job, 'created': created, 'message': 'Editing job added to the queue.' if created else 'This request is already in the queue.'}

    def start_worker(self):
        if os.name == 'nt':
            with (self.root / 'logs/ui-worker-start.log').open('ab') as log:
                subprocess.Popen(['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass',
                                  '-File', str(self.root / 'scripts/start-desktop-worker.ps1')],
                                 stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    def job_action(self, job_id, action, data):
        if not re.fullmatch('[a-f0-9]{16}', job_id):
            raise ValueError('Invalid job ID.')
        old = self.store.get(job_id)
        if action == 'cancel':
            self.store.cancel(job_id)
            return {'cancelled': job_id}
        if action == 'feedback':
            notes = str(data.get('notes', ''))
            if len(notes) > 5000:
                raise ValueError('Keep feedback below 5,000 characters.')
            self.store.feedback(job_id, data['clip'], int(data['rating']), notes)
            return {'saved': True}
        if action == 'revise':
            from .request import interpret
            from .worker import submit
            instruction = data.get('instruction', '').strip()
            if not instruction:
                raise ValueError('Describe the change you need.')
            spec = interpret(old['spec']['source'], instruction, [Profile.model_validate(p) for p in old['spec']['profiles']])
            spec.transcript = old['spec'].get('transcript')
            spec.transcript_language = old['spec'].get('transcript_language')
            spec.revision_of = job_id + f'-ui-{time.time_ns()}'
            spec.podcast_mode = old['spec'].get('podcast_mode', 'auto')
            job, created = submit(spec, self.settings(), self.store)
            self.start_worker()
            return {'job': job, 'created': created}
        raise ValueError('Unsupported job action.')

    def output_path(self, relative):
        base = (self.root / 'output').resolve()
        p = (base / relative).resolve(strict=True)
        if not p.is_relative_to(base) or not p.is_file() or p.suffix.lower() not in PUBLIC_OUTPUTS:
            raise ValueError('This file is not a public output artifact.')
        return p

    def artifact_url(self, path):
        from urllib.parse import quote
        p = Path(path).resolve()
        self.output_path(str(p.relative_to((self.root / 'output').resolve())))
        return '/media/output/' + quote(p.relative_to((self.root / 'output').resolve()).as_posix())

    def outputs(self):
        result, seen = [], set()
        paths = []  # Exports come from job manifests, never from a fixed demo folder.
        for job in self.store.list(40):
            if not job['output']:
                continue
            try:
                folder = Path(job['output']).resolve()
                if not folder.is_relative_to((self.root / 'output').resolve()):
                    continue
                manifest = json.loads((folder / 'manifest.json').read_text())
                for record in manifest.get('outputs', []):
                    if record.get('path'):
                        paths.append((Path(record['path']), 'Job ' + job['id'][:8], job['id']))
            except (OSError, ValueError, KeyError):
                continue
        for path, collection, job in paths:
            try:
                path = self.output_path(str(path.resolve().relative_to((self.root / 'output').resolve())))
                if path in seen:
                    continue
                seen.add(path)
                notes = path.with_suffix('.md')
                title = notes.read_text(encoding='utf-8').splitlines()[0].lstrip('# ') if notes.exists() else path.stem
                quality_path = path.with_name(path.stem + '_quality.json')
                quality = json.loads(quality_path.read_text()) if quality_path.exists() else {}
                cover = next((p for p in (path.with_name(path.stem+'-cover.jpg'), path.with_name(path.stem+'_thumbnail.jpg')) if p.exists()), None)
                srt = path.with_suffix('.srt')
                result.append({'id': self.artifact_url(path), 'name': path.stem, 'title': title, 'collection': collection, 'job': job,
                               'video_url': self.artifact_url(path), 'poster_url': self.artifact_url(cover) if cover else None,
                               'subtitle_url': self.artifact_url(srt) if srt.exists() else None,
                               'quality_url': self.artifact_url(quality_path) if quality_path.exists() else None,
                               'status': quality.get('status', 'review_required'), 'findings': quality.get('findings', []),
                               'bytes': path.stat().st_size})
            except (OSError, ValueError, IndexError):
                continue
        return result[:100]


class WorkspaceServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, workspace):
        if address[0] != '127.0.0.1':
            raise ValueError('The workspace must bind to loopback.')
        self.workspace = workspace
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'ERMCLIP/0.1'
    def setup(self):
        super().setup()
        self.connection.settimeout(30)
    def log_message(self, *_):
        pass  # No source paths, tokens, or request bodies in HTTP logs.

    def guard(self, mutation=False):
        host = self.headers.get('Host', '')
        if host not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
            raise PermissionError('Open the local application address.')
        origin = self.headers.get('Origin')
        if (origin and origin != 'http://' + host) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PermissionError('Cross-site requests are blocked.')
        if mutation:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise PermissionError('Use a JSON request from the application.')
            if not secrets.compare_digest(self.headers.get('X-ERMCLIP-Token', ''), self.server.workspace.token):
                raise PermissionError('Reload the application before making this change.')

    def response_headers(self, status, content_type, length=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.response_headers(status, 'application/json; charset=utf-8', len(raw))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def file(self, path):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        value = self.headers.get('Range')
        if value:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
            if not match or not any(match.groups()):
                self.response_headers(416, 'text/plain', 0)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
            a, b = match.groups()
            if a:
                start, end = int(a), min(int(b), size-1) if b else size-1
            else:
                start = max(0, size-int(b))
            if start > end or start >= size:
                self.response_headers(416, 'text/plain', 0)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
            status = 206
        length = max(0, end-start+1)
        kind = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self.response_headers(status, kind, length)
        self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with path.open('rb') as stream:
            stream.seek(start)
            while length:
                block = stream.read(min(length, 256*1024))
                if not block:
                    break
                self.wfile.write(block)
                length -= len(block)

    def dispatch_get(self):
        self.guard()
        app = self.server.workspace
        path = unquote(urlsplit(self.path).path)
        if path == '/api/bootstrap':
            return self.json({'app': 'ERMCLIP', 'instance': hashlib.sha256(str(app.root).encode()).hexdigest(), 'token': app.token, 'settings': app.public_settings(), 'sources': app.sources(), 'styles': catalog(), 'status': app.status()})
        if path == '/api/status':
            return self.json(app.status())
        if path == '/api/jobs':
            return self.json(app.jobs())
        if path == '/api/outputs':
            return self.json(app.outputs())
        if path == '/api/sources':
            return self.json(app.sources())
        if path.startswith('/api/jobs/'):
            job_id = path.rsplit('/', 1)[-1]
            job = app.store.get(job_id)
            with app.store.connect() as db:
                events = [dict(r) for r in db.execute('SELECT kind,time,payload FROM events WHERE job_id=? ORDER BY id DESC LIMIT 30', (job_id,))]
            return self.json({'job': job, 'events': events})
        if path.startswith('/media/output/'):
            return self.file(app.output_path(path[len('/media/output/'):]))
        if path.startswith('/media/source/'):
            return self.file(Path(app.source(path.rsplit('/', 1)[-1])['path']))
        if path.startswith('/media/thumbnail/'):
            item = app.source(path.rsplit('/', 1)[-1])
            p = Path(item['path'])
            return self.file(app.root / 'cache/ui' / f'{item["id"]}-{p.stat().st_mtime_ns}.jpg')
        if path.startswith('/caption/'):
            name = path.rsplit('/', 1)[-1]
            if name.removesuffix('.png') not in PRESET_IDS or not name.endswith('.png'):
                raise ValueError('Unknown caption preview.')
            return self.file(app.root / 'output/caption-gallery' / name)
        static = {'/': 'index.html', '/app.js': 'app.js', '/app.css': 'app.css', '/wizard.css': 'wizard.css', '/favicon.svg': 'favicon.svg'}
        if path in static:
            return self.file(Path(__file__).parent / 'web' / static[path])
        self.json({'error': 'Page not found.'}, 404)

    def do_GET(self):
        try:
            self.dispatch_get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except PermissionError as exc:
            self.json({'error': str(exc)}, 403)
        except (ValueError, OSError, KeyError) as exc:
            self.json({'error': str(exc)}, 404)

    do_HEAD = do_GET

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 65536:
                raise ValueError('The request is empty or too large.')
            raw = self.rfile.read(length)
            self.guard(mutation=True)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('Use a JSON object.')
            app = self.server.workspace
            path = urlsplit(self.path).path
            if path == '/api/source/inspect':
                result = app.inspect_source(data)
            elif path == '/api/browse':
                result = app.native_picker()
            elif path == '/api/submit':
                result = app.submit(data)
            elif path == '/api/settings':
                result = app.save_settings(data)
            elif path == '/api/control':
                action = data.get('action')
                if action in ('pause', 'resume'):
                    app.store.control('pause', '1' if action == 'pause' else '0')
                elif action == 'start':
                    app.start_worker()
                else:
                    raise ValueError('Unknown queue action.')
                result = {'action': action}
            elif re.fullmatch(r'/api/jobs/[a-f0-9]{16}/(cancel|revise|feedback)', path):
                _, _, _, job, action = path.split('/')
                result = app.job_action(job, action, data)
            else:
                raise ValueError('Unknown application action.')
            self.json(result)
        except PermissionError as exc:
            self.json({'error': str(exc)}, 403)
        except (ValueError, OSError, KeyError, RuntimeError, TimeoutError) as exc:
            self.json({'error': str(exc)}, 400)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8090)
    args = p.parse_args()
    app = Workspace()
    with WorkspaceServer(('127.0.0.1', args.port), app) as server:
        print(f'ERMCLIP workspace: http://127.0.0.1:{server.server_port}/', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
