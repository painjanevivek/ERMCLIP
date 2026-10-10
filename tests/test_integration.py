import hashlib
import json
from pathlib import Path
import shutil
import pytest

from ermclip.media import probe,render
from ermclip.models import Candidate, Duration, JobSpec, Profile, Segment
from ermclip.pipeline import process
from ermclip.store import Store
from ermclip.subtitles import write
from ermclip.util import atomic_json,fingerprint,run
from ermclip.worker import submit
from conftest import synthetic_transcript


@pytest.mark.integration
@pytest.mark.parametrize("duration",[30,60])
def test_real_render(duration,source_video,settings):
    info=probe(source_video)
    profile=Profile(name="test",ratio="16:9",width=320,height=180,duration=Duration(target=duration,minimum=duration,maximum=duration,strict=True),framing="pad")
    candidate=Candidate(id="clip_001",profile="test",title="test",segments=[Segment(start=0,end=duration,reason="fixture")],reason="fixture")
    base=settings.path/"output"/"clip_001"
    ass,_=write(synthetic_transcript(70),candidate,profile,base)
    result=render(source_video,info,candidate,profile,ass,base.with_suffix(".mp4"),settings,{})
    actual=probe(base.with_suffix(".mp4"))
    assert abs(float(actual["video"]["duration"])-duration)<0.05
    assert (actual["width"],actual["height"])==(320,180)
    assert result["encoder"]=="libx264"
    run(["ffmpeg","-hide_banner","-loglevel","error","-i",str(base.with_suffix(".mp4")),"-f","null","-"],timeout=120)


@pytest.mark.integration
def test_pipeline_multi_profile_cache_metadata_and_original(source_video,settings):
    source=settings.path/"input"/"fixture.mp4"
    shutil.copyfile(source_video,source)
    before=fingerprint(source)
    transcript=settings.path/"input"/"fixture.json"
    atomic_json(transcript,synthetic_transcript(70).model_dump())
    profiles=[Profile(name="landscape",ratio="16:9",width=320,height=180,duration=Duration(target=30,minimum=30,maximum=30,strict=True),count=1,framing="pad"),Profile(name="square",ratio="1:1",width=256,height=256,duration=Duration(target=30,minimum=30,maximum=30,strict=True),count=1,framing="blur")]
    spec=JobSpec(source=str(source),transcript=str(transcript),profiles=profiles)
    store=Store(settings.path/"state"/"jobs.sqlite3")
    job_id,created=submit(spec,settings,store)
    assert created
    assert submit(spec,settings,store)==(job_id,False)
    manifest=process(store.claim(),settings,store)
    assert len(manifest["outputs"])==2
    assert manifest["status"]=="review_required"
    assert len(list((settings.path/"cache"/"analysis").glob("*/transcript.json")))==1
    for record in manifest["outputs"]:
        video=Path(record["path"])
        assert video.with_suffix(".md").exists()
        assert video.with_suffix(".srt").exists()
        doc=video.with_suffix(".md").read_text(encoding="utf-8")
        assert "## YouTube Studio Tags" in doc and "## Description hashtags" in doc
        quality=json.loads(video.with_name(video.stem+"_quality.json").read_text(encoding="utf-8"))
        assert quality["evidence"]["sampled_frames"]
        assert quality["evidence"]["stream_start_delta"]<=0.1
    assert fingerprint(source)==before
    other=spec.model_copy(update={"revision_of":"next"})
    submit(other,settings,store)
    next_manifest=process(store.claim(),settings,store)
    assert next_manifest["analysis_reused"]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("duration",[300,600,900])
def test_long_duration_render(duration,long_video,settings):
    settings.encoder="auto"
    profile=Profile(name="long",ratio="16:9",width=320,height=180,duration=Duration(target=duration,minimum=duration,maximum=duration,strict=True),framing="pad")
    candidate=Candidate(id="clip_001",profile="long",title="long test",segments=[Segment(start=0,end=duration,reason="duration fixture")],reason="duration fixture")
    base=settings.path/"output"/"clip_001"
    ass,_=write(synthetic_transcript(920),candidate,profile,base)
    render(long_video,probe(long_video),candidate,profile,ass,base.with_suffix(".mp4"),settings,{})
    rendered=probe(base.with_suffix(".mp4"))
    assert float(rendered["video"]["duration"])<=900
    assert abs(float(rendered["video"]["duration"])-duration)<0.05


@pytest.mark.integration
def test_compilation_custom_ratio(source_video,settings):
    profile=Profile(name="custom",ratio="7:5",width=350,height=250,strategy="compilation",duration=Duration(target=30,minimum=30,maximum=30,strict=True),framing="center")
    candidate=Candidate(id="clip_001",profile="custom",title="test",segments=[Segment(start=0,end=10,reason="first"),Segment(start=30,end=50,reason="second")],reason="fixture compilation")
    base=settings.path/"output"/"clip_001"
    ass,cues=write(synthetic_transcript(70),candidate,profile,base)
    render(source_video,probe(source_video),candidate,profile,ass,base.with_suffix(".mp4"),settings,{})
    actual=probe(base.with_suffix(".mp4"))
    assert (actual["width"],actual["height"])==(350,250)
    assert cues[-1].end==30
