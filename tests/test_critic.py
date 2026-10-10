from pathlib import Path
import pytest

from ermclip.director import Matcher
from ermclip.models import Candidate,Duration,JobSpec,Profile,Segment
from ermclip.quality import evaluate,revise
from ermclip.subtitles import timeline
from conftest import synthetic_transcript


def setup(settings):
    transcript=synthetic_transcript(60)
    profile=Profile(duration=Duration(target=30,minimum=20,maximum=60))
    candidate=Candidate(id="clip_001",profile=profile.name,title="test",segments=[Segment(start=0,end=30,reason="test")],reason="test")
    spec=JobSpec(source="x",profiles=[profile])
    return transcript,profile,candidate,spec,Matcher(spec,transcript,settings,settings.path/"cache")


@pytest.mark.parametrize("score,hard,expected",[(90,False,"passed"),(80,False,"revision_required"),(60,False,"rejected"),(100,True,"rejected")])
def test_critic_score_thresholds_and_hard_gate(settings,monkeypatch,score,hard,expected):
    import ermclip.quality as module
    transcript,profile,candidate,spec,matcher=setup(settings)
    monkeypatch.setattr(module,"audiovisual",lambda *_,**__:([],{"limits":["metrics only"]}))
    class Model:
        enabled=True
        def json(self,*_):
            return {"scores":{k:score for k in ("relevance","coherence","hook_pacing","value","visual","audio_subtitles")},"findings":[],"hard_violation":hard}
    result=evaluate(spec,candidate,profile,transcript,{"duration":60},matcher,Path("fake.mp4"),timeline(transcript,candidate),settings,Model())
    assert result["status"]==expected


def test_critic_failure_is_visible_and_crop_revision(settings,monkeypatch):
    import ermclip.quality as module
    transcript,profile,candidate,spec,matcher=setup(settings)
    monkeypatch.setattr(module,"audiovisual",lambda *_,**__:([],{}))
    class Model:
        enabled=True
        def json(self,*_): raise RuntimeError("unavailable")
    result=evaluate(spec,candidate,profile,transcript,{"duration":60},matcher,Path("fake.mp4"),[],settings,Model())
    assert result["status"]=="review_required"
    assert any(f["code"]=="critic_unavailable" for f in result["findings"])
    revised=revise(candidate,[{"code":"cropping"}],transcript,profile,60)
    assert revised.framing=="pad" and revised.revision==1


def test_critic_uses_output_times_and_excludes_director_claims(settings,monkeypatch):
    import ermclip.quality as module
    transcript,profile,candidate,spec,matcher=setup(settings)
    candidate.segments=[Segment(start=30,end=60,reason="Director assertion should be excluded")]
    candidate.narrative=["Invented director story"]
    candidate.score=99
    monkeypatch.setattr(module,"audiovisual",lambda *_,**__:([],{"limits":["metrics only"]}))
    class Model:
        enabled=True
        def json(self,role,payload,schema):
            assert "timeline" not in payload
            assert all(0<=p["start"]<p["end"]<=30 for p in payload["selected_transcript"])
            assert "Invented director story" not in str(payload)
            assert set(schema["properties"]["scores"]["required"])==set(payload["criteria"])
            return {"scores":{k:90 for k in payload["criteria"]},"findings":[{"code":"missing_context","severity":"revision","start":50,"end":55,"issue":"Out of range","correction":"Do not auto repair this"}],"hard_violation":False}
    result=evaluate(spec,candidate,profile,transcript,{"duration":60},matcher,Path("fake.mp4"),[],settings,Model())
    assert result["status"]=="review_required"
    assert any(f["code"]=="critic_evidence_invalid" for f in result["findings"])


def test_review_only_findings_do_not_trigger_automatic_boundary_repairs(settings):
    transcript,profile,candidate,_,_=setup(settings)
    candidate.segments=[Segment(start=10,end=35,reason="Test")]
    assert revise(candidate,[{"code":"incomplete_statement","severity":"review"}],transcript,profile,60) is None


def test_critic_cannot_reuse_weights_as_quality_scores(settings,monkeypatch):
    import ermclip.quality as module
    transcript,profile,candidate,spec,matcher=setup(settings)
    monkeypatch.setattr(module,"audiovisual",lambda *_,**__:([],{}))
    class Model:
        enabled=True
        def json(self,role,payload,schema):
            assert isinstance(payload['criteria'],list)
            return {'scores':{'relevance':25,'coherence':25,'hook_pacing':15,'value':15,'visual':10,'audio_subtitles':10},'findings':[],'hard_violation':False}
    result=evaluate(spec,candidate,profile,transcript,{'duration':60},matcher,Path('fake.mp4'),[],settings,Model())
    assert result['status']=='review_required' and result['scores'] is None
    assert any(f['code']=='critic_unavailable' for f in result['findings'])


def test_speaker_evidence_is_seen_by_critic_and_remains_review(settings,monkeypatch):
    import ermclip.quality as module
    transcript,profile,candidate,spec,matcher=setup(settings)
    profile.framing='speaker'
    monkeypatch.setattr(module,"audiovisual",lambda *_,**__:([],{}))
    class Model:
        enabled=True
        def json(self,role,payload,schema):
            evidence=payload['audiovisual_metrics']['speaker_tracking'][0]
            assert evidence['coverage']==.8 and 'points' not in evidence
            return {'scores':{k:95 for k in payload['criteria']},'findings':[],'hard_violation':False}
    audit={'segments':[{'coverage':.8,'points':[{'time':0}],'key':'private-cache-key'}]}
    result=evaluate(spec,candidate,profile,transcript,{'duration':60},matcher,Path('fake.mp4'),[],settings,Model(),speaker_tracking=audit)
    assert result['status']=='review_required'
    assert revise(candidate,[{'code':'cropping','severity':'revision'}],transcript,profile,60) is None
