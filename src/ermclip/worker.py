from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import time

from .models import JobSpec
from .notifications import flush
from .pipeline import process
from .store import Store
from .util import Cancelled, UnsupportedRequest, atomic_json, fingerprint, validate_input


@contextmanager
def worker_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open("a+b")
    try:
        stream.seek(0,2)
        if stream.tell()==0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError("Another ERMCLIP worker holds the local lock") from None
    try:
        yield
    finally:
        stream.seek(0)
        if os.name=="nt":
            msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            fcntl.flock(stream,fcntl.LOCK_UN)
        stream.close()


def submit(spec,settings,store):
    source=validate_input(spec.source,settings.allowed_inputs)
    # Transcript and plan are trusted local operator inputs, never taken from media metadata.
    spec=spec.model_copy(update={"source":str(source)})
    from .request import source_context
    spec=source_context(spec,settings)
    first=(source.stat().st_size,source.stat().st_mtime_ns)
    if settings.stable_seconds:
        time.sleep(settings.stable_seconds)
    if first!=(source.stat().st_size,source.stat().st_mtime_ns):
        raise ValueError("Input file is still changing; wait for the download to finish")
    from .media import probe
    probe(source)
    identity=fingerprint(source)
    key=hashlib.sha256((identity+spec.model_dump_json()+ (fingerprint(Path(spec.transcript)) if spec.transcript else "")+(fingerprint(Path(spec.approved_plan)) if spec.approved_plan else "")).encode()).hexdigest()
    job_id,created=store.submit(spec,key)
    if created:
        store.update(job_id,checkpoint={"source_fingerprint":identity})
    return job_id,created


class Watcher:
    def __init__(self,settings,store):
        self.settings=settings
        self.store=store
        self.observed={}

    def poll(self):
        for folder in self.settings.watch_folders:
            for path in Path(folder).glob("*"):
                if not path.is_file() or path.suffix.lower() not in (".mp4",".mkv",".mov",".webm",".avi",".m4v"):
                    continue
                resolved=validate_input(path,self.settings.allowed_inputs)
                stat=resolved.stat()
                signature=(stat.st_size,stat.st_mtime_ns)
                old=self.observed.get(str(resolved))
                if not old or old[0]!=signature:
                    self.observed[str(resolved)]=(signature,time.monotonic(),False)
                    continue
                if old[2] or time.monotonic()-old[1]<self.settings.stable_seconds:
                    continue
                identity=fingerprint(resolved)
                with self.store.connect() as db:
                    recorded=db.execute("SELECT fingerprint FROM watched WHERE path=?",(str(resolved),)).fetchone()
                if recorded and recorded[0]==identity:
                    self.observed[str(resolved)]=(signature,old[1],True)
                    continue
                # Job-level stability validation remains active. The watcher has already waited once.
                spec=JobSpec(source=str(resolved),profiles=self.settings.defaults)
                try:
                    submit(spec,self.settings,self.store)
                except (RuntimeError,ValueError,OSError):
                    logging.exception("watch_input_not_ready",extra={"source":str(resolved)})
                    continue
                with self.store.connect() as db:
                    db.execute("INSERT INTO watched VALUES (?,?) ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint",(str(resolved),identity))
                self.observed[str(resolved)]=(signature,old[1],True)


class JsonFormatter(logging.Formatter):
    def format(self,record):
        return json.dumps({"time":time.time(),"level":record.levelname,"message":record.getMessage(),"error":self.formatException(record.exc_info) if record.exc_info else None},ensure_ascii=False)


def worker(settings,once=False):
    store=Store(settings.path/"state"/"jobs.sqlite3")
    handler=logging.FileHandler(settings.path/"logs"/"worker.jsonl",encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    stop=[False]
    def request_stop(*_): stop[0]=True
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,request_stop)
    health=settings.path/"state"/"health.json"
    with worker_lock(settings.path/"state"/"worker.lock"):
        store.recover()
        store.control("stop","0")
        watcher=Watcher(settings,store)
        active=None
        def stopping():
            return stop[0] or store.control("stop")=="1"
        def heartbeat():
            atomic_json(health,{"pid":os.getpid(),"time":time.time(),"active_job":active,"status":"running"})
        # Heartbeats continue during long model and media calls.
        import threading
        done=threading.Event()
        def beat():
            while not done.wait(3):
                heartbeat()
        thread=threading.Thread(target=beat,daemon=True)
        thread.start()
        try:
            while not stopping():
                heartbeat()
                try:
                    watcher.poll()
                except (OSError,ValueError):
                    logging.exception("watcher_failed")
                job=store.claim()
                if job:
                    active=job["id"]
                    store.event(active,"started",{"attempt":job["attempts"]})
                    try:
                        process(job,settings,store,stopping)
                    except Cancelled:
                        user_cancel=store.get(active)["cancel"]
                        store.update(active,status="cancelled" if user_cancel else "queued",stage="interrupted")
                        store.event(active,"cancelled" if user_cancel else "interrupted",{})
                    except (UnsupportedRequest,ValueError) as exc:
                        logging.exception("invalid_request")
                        store.update(active,status="failed",error=str(exc),stage="failed")
                        store.event(active,"error",{"error":str(exc)[:1200]})
                    except Exception as exc:
                        logging.exception("job_failed")
                        retry=job["attempts"]<=settings.retries
                        store.update(active,status="retry" if retry else "failed",error=str(exc)[-3000:],available=time.time()+min(300,15*2**(job["attempts"]-1)))
                        store.event(active,"retry" if retry else "error",{"error":str(exc)[-1200:],"attempt":job["attempts"]})
                    finally:
                        active=None
                flush(settings,store)
                if once:
                    break
                done.wait(settings.poll_seconds)
        finally:
            done.set()
            thread.join(timeout=5)
            atomic_json(health,{"pid":os.getpid(),"time":time.time(),"active_job":None,"status":"stopped"})
            logging.getLogger().removeHandler(handler)
            handler.close()
