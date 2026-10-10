import json
from pathlib import Path
import sys
import time
import pytest

from ermclip.models import JobSpec
from ermclip.store import Store
from ermclip.util import Cancelled,atomic_json,run
from ermclip.worker import Watcher,worker


def test_subprocess_timeout_and_cancellation():
    with pytest.raises(TimeoutError): run([sys.executable,"-c","import time; time.sleep(20)"],timeout=0.2)
    with pytest.raises(Cancelled): run([sys.executable,"-c","import time; time.sleep(20)"],check_cancel=lambda:True)


def test_worker_retries_are_bounded(settings,monkeypatch):
    import ermclip.worker as module
    store=Store(settings.path/"state"/"jobs.sqlite3")
    job,_=store.submit(JobSpec(source="x.mp4"),"failure")
    settings.retries=2
    def fail(*_,**__): raise RuntimeError("fixture failure")
    monkeypatch.setattr(module,"process",fail)
    for expected in ("retry","retry","failed"):
        store.update(job,available=0)
        worker(settings,once=True)
        assert store.get(job)["status"]==expected
    assert store.get(job)["attempts"]==3


@pytest.mark.integration
def test_watcher_only_queues_stable_allowed_media(settings,source_video):
    import shutil
    source=settings.path/"input"/"watched.mp4"
    shutil.copyfile(source_video,source)
    settings.watch_folders=[str(source.parent)]
    settings.stable_seconds=0
    store=Store(settings.path/"state"/"jobs.sqlite3")
    watcher=Watcher(settings,store)
    watcher.poll()
    assert not store.list()
    watcher.poll()
    assert len(store.list())==1
    watcher.poll()
    assert len(store.list())==1
    other=Watcher(settings,store)
    other.poll()
    other.poll()
    assert len(store.list())==1


def test_model_call_budget_survives_restart(settings):
    from ermclip.provider import LocalModel
    settings.local_llm_url="http://127.0.0.1:1/v1"
    settings.director_model="fixture"
    settings.max_model_calls=1
    persisted=[]
    model=LocalModel(settings,on_call=persisted.append)
    with pytest.raises(OSError): model.json("director",{},{})
    assert persisted==[1]
    restarted=LocalModel(settings,initial_calls=persisted[-1])
    with pytest.raises(RuntimeError): restarted.json("critic",{},{})


def test_on_demand_worker_exits_and_releases_model_when_queue_is_empty(settings,monkeypatch):
    import ermclip.local_runtime as runtime
    settings.poll_seconds=.1
    settings.local_llm_url='http://127.0.0.1:8088/v1'
    settings.director_model='ermclip-qwen35-9b'
    settings.critic_model='ermclip-qwen35-9b'
    settings.managed_local_model=True
    released=[]
    monkeypatch.setattr(runtime,'stop',lambda s:released.append(s.path))
    worker(settings,idle_exit=.02)
    assert released==[settings.path]
    health=json.loads((settings.path/'state/health.json').read_text())
    assert health['status']=='stopped' and health['active_job'] is None


def test_idle_timeout_keeps_delayed_retry_in_queue(settings,monkeypatch):
    import ermclip.worker as module
    store=Store(settings.path/'state/jobs.sqlite3')
    job,_=store.submit(JobSpec(source='x.mp4'),'delayed')
    store.update(job,status='retry',available=time.time()+3600)
    settings.poll_seconds=.1
    polls=[]
    def poll(_):
        polls.append(True)
        if len(polls)==4:store.control('stop','1')
    monkeypatch.setattr(module.Watcher,'poll',poll)
    worker(settings,idle_exit=.01)
    assert len(polls)==4
    assert store.get(job)['status']=='retry'
