import json
from pathlib import Path
import shutil
import pytest

from ermclip.models import Candidate,Duration,EditingPlan,JobSpec,Profile,Segment
from ermclip.pipeline import process
from ermclip.store import Store
from ermclip.util import fingerprint
from conftest import synthetic_transcript


@pytest.mark.integration
def test_revision_budget_stops_persistent_critic_findings(settings,source_video,monkeypatch):
    # Isolate revision control from encoding cost. Real encoding is tested separately.
    import ermclip.pipeline as pipeline
    from ermclip.media import probe
    source=settings.path/"input"/"source.mp4"
    shutil.copyfile(source_video,source)
    transcript=synthetic_transcript(70)
    profile=Profile(name="landscape",ratio="16:9",width=320,height=180,duration=Duration(target=30,minimum=15,maximum=60),count=1)
    candidate=Candidate(id="clip_001",profile=profile.name,title="Budget test",segments=[Segment(start=45,end=65,reason="fixture")],reason="fixture")
    spec=JobSpec(source=str(source),profiles=[profile])
    editing=EditingPlan(instruction=spec.instruction,source=str(source),fingerprint=fingerprint(source),source_duration=70,mode="AUTO",profiles=[profile],candidates=[candidate],director="fixture")
    info=probe(source)
    monkeypatch.setattr(pipeline,"analyse",lambda *_,**__:(info,transcript,{"engine":"fixture"},settings.path/"cache",False))
    monkeypatch.setattr(pipeline.director,"plan",lambda *_,**__:editing)
    renders=[]
    def render(_,__,c,___,____,output,*args,**kwargs):
        renders.append(c.revision)
        shutil.copyfile(source,output)
        return {"encoder":"fixture","probe":{"duration":c.duration,"video":{"duration":c.duration}}}
    def evaluate(_,c,*args,**kwargs):
        code="incomplete_statement" if c.revision==0 else "missing_context"
        return {"status":"revision_required","weighted_score":80,"findings":[{"code":code,"severity":"revision","start":0,"end":5,"issue":"Fixture critic still requests context","correction":"Extend the boundary"}]}
    monkeypatch.setattr(pipeline.media,"render",render)
    monkeypatch.setattr(pipeline.quality,"evaluate",evaluate)
    store=Store(settings.path/"state"/"jobs.sqlite3")
    job,_=store.submit(spec,"revision-test")
    result=process(store.claim(),settings,store)
    assert renders==[0,1,2]
    assert result["status"]=="review_required"
    record=result["outputs"][0]
    assert record["revision"]==2
    q=json.loads(Path(record["path"]).with_name("clip_001_quality.json").read_text(encoding="utf-8"))
    assert q["remaining_revision_issues"] and len(q["history"])==3
