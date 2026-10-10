from concurrent.futures import ThreadPoolExecutor
import time

from ermclip.models import JobSpec
from ermclip.store import Store
from ermclip.worker import worker_lock
import pytest


def test_idempotent_and_atomic_claim(settings):
    store=Store(settings.path/"state"/"jobs.sqlite3")
    first,created=store.submit(JobSpec(source="input.mp4"),"same")
    second,again=store.submit(JobSpec(source="input.mp4"),"same")
    assert created and not again and first==second
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims=list(executor.map(lambda _:store.claim(),range(4)))
    assert sum(bool(c) for c in claims)==1


def test_recovery_cancel_pause_retry(settings):
    store=Store(settings.path/"state"/"jobs.sqlite3")
    job,_=store.submit(JobSpec(source="input.mp4"),"same")
    store.control("pause","1")
    assert store.claim() is None
    store.control("pause","0")
    assert store.claim()["id"]==job
    store.update(job,checkpoint={"outputs":[{"id":"clip_001"}]})
    store.recover()
    assert store.get(job)["status"]=="queued"
    assert store.get(job)["checkpoint"]["outputs"][0]["id"]=="clip_001"
    store.update(job,status="retry",available=time.time()+60)
    assert store.claim() is None
    store.cancel(job)
    store.recover()
    assert store.get(job)["status"]=="cancelled"


def test_feedback_delete(settings):
    store=Store(settings.path/"state"/"jobs.sqlite3")
    job,_=store.submit(JobSpec(source="input.mp4"),"same")
    store.feedback(job,"clip_001",4,"More context")
    assert len(store.preferences())==1
    store.delete_feedback()
    assert not store.preferences()


def test_worker_single_instance(settings):
    with worker_lock(settings.path/"state"/"worker.lock"):
        with pytest.raises(RuntimeError):
            with worker_lock(settings.path/"state"/"worker.lock"): pass
