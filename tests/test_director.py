from pathlib import Path
import pytest

from ermclip.director import Matcher,plan
from ermclip.models import Candidate, Conditions, Duration, JobSpec, Passage, Profile, Segment, Transcript, Word
from ermclip.provider import LocalModel
from ermclip.quality import revise,pre_render
from ermclip.subtitles import escape,timeline,write
from ermclip.util import UnsupportedRequest
from conftest import synthetic_transcript


def make_plan(settings,mode="AUTO",conditions=None,strategy="continuous",target=30):
    transcript=synthetic_transcript(120)
    p=Profile(duration=Duration(target=target,minimum=target,maximum=target,strict=True),count=2,strategy=strategy)
    spec=JobSpec(source="fixture.mp4",mode=mode,conditions=conditions or Conditions(),profiles=[p])
    cache=Path(settings.root)/"cache"
    return plan(spec,transcript,{"duration":120},"hash",settings,cache,LocalModel(settings),[]),transcript,spec


def test_auto_selects_context_and_avoids_overlap(settings):
    editing,_,_=make_plan(settings)
    assert len(editing.candidates)==2
    a,b=editing.candidates
    assert a.duration==30 and b.duration==30
    assert max(a.segments[0].start,b.segments[0].start)>=min(a.segments[0].end,b.segments[0].end)
    assert editing.director=="deterministic"


def test_targeted_exclusion_no_match(settings):
    editing,_,_=make_plan(settings,"TARGETED",Conditions(keywords=["AMD"]))
    assert not editing.candidates
    editing,_,_=make_plan(settings,"TARGETED",Conditions(keywords=["NVIDIA"],exclude=["CUDA"]))
    assert not editing.candidates


def test_exact_keyword_boundaries(settings):
    t=Transcript(engine="test",passages=[Passage(start=0,end=10,text="An invalid aid is here")])
    spec=JobSpec(source="x",mode="TARGETED",conditions=Conditions(keywords=["AI"]))
    matcher=Matcher(spec,t,settings,Path(settings.root)/"cache")
    assert not matcher.matches_passage(t.passages[0])


def test_semantic_and_speaker_fail_closed(settings):
    t=synthetic_transcript(60)
    for c in (Conditions(topics=["AI predictions"]),Conditions(speaker="guest"),Conditions(visual_events=["robot falls"])):
        with pytest.raises(UnsupportedRequest): Matcher(JobSpec(source="x",mode="TARGETED",conditions=c),t,settings,settings.path/"cache")


def test_compilation_order(settings):
    editing,_,_=make_plan(settings,strategy="compilation",target=60)
    assert editing.candidates
    s=editing.candidates[0].segments
    assert all(a.end<=b.start for a,b in zip(s,s[1:]))


def test_subtitle_mapping_and_injection(settings):
    t=Transcript(engine="test",passages=[Passage(start=10,end=12,text="Hello world",words=[Word(start=10,end=11,text="Hello"),Word(start=11,end=12,text="world")]),Passage(start=20,end=22,text="Second part",words=[Word(start=20,end=21,text="Second"),Word(start=21,end=22,text="part")])])
    c=Candidate(id="clip_001",profile="test",title="test",segments=[Segment(start=10,end=12,reason="test"),Segment(start=20,end=22,reason="test")],reason="test")
    cues=timeline(t,c)
    assert cues[0].start==0 and cues[1].start==2 and cues[-1].end==4
    assert "{" not in escape("{\\pos(0,0)}danger")
    ass,_=write(t,c,Profile(),settings.path/"output"/"clip_001")
    assert "\\kf100" in ass.read_text(encoding="utf-8")


def test_actionable_findings_and_revision(settings):
    t=synthetic_transcript(60)
    profile=Profile(duration=Duration(target=25,minimum=15,maximum=60))
    c=Candidate(id="clip_001",profile=profile.name,title="test",segments=[Segment(start=5,end=25,reason="test")],reason="test")
    spec=JobSpec(source="x",profiles=[profile])
    matcher=Matcher(spec,t,settings,settings.path/"cache")
    findings=pre_render(spec,c,profile,t,{"duration":60},matcher)
    assert any(f.code=="incomplete_statement" and f.correction for f in findings)
    revised=revise(c,[f.model_dump() for f in findings],t,profile,60)
    assert revised.revision==1 and revised.segments[0].start==0 and revised.segments[0].end==30
    strict=Profile(duration=Duration(target=20,minimum=20,maximum=20,strict=True))
    assert revise(c,[f.model_dump() for f in findings],t,strict,60) is None
