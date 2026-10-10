from pathlib import Path
import pytest
from pydantic import ValidationError

from ermclip.config import Settings
from ermclip.models import Candidate, Conditions, Duration, EditingPlan, JobSpec, Profile, Segment, seconds
from ermclip.request import interpret
from ermclip.util import UnsupportedRequest, validate_input
from ermclip.metadata import tag_length,tags_for


@pytest.mark.parametrize("value,expected",[(15,15),(30,30),(60,60),(300,300),(600,600),(900,900),("00:01:37",97),("8 minutes",480),("42.5s",42.5)])
def test_durations(value,expected):
    assert seconds(value)==expected


@pytest.mark.parametrize("value",[0,-1,901,"16 minutes","00:60:00","nan",float("inf"),"1:30"])
def test_invalid_duration(value):
    with pytest.raises(ValueError): seconds(value)


def test_ratio_and_dimensions():
    p=Profile(ratio="7:5",width=700,height=500)
    assert p.width==700
    for data in ({"width":701,"height":500,"ratio":"7:5"},{"ratio":"0:5"},{"width":1920,"height":1080,"ratio":"9:16"}):
        with pytest.raises(ValidationError): Profile(**data)


@pytest.mark.parametrize("text,target,count,strategy",[("Create 10 videos of 30 seconds each",30,10,"continuous"),("Make 5 videos, each 5 minutes",300,5,"continuous"),("Create three 10-minute videos",600,3,"continuous"),("Make one 15-minute compilation",900,1,"compilation")])
def test_natural_duration(text,target,count,strategy):
    spec=interpret("input.mp4",text,[Profile()])
    assert spec.profiles[0].duration.target==target
    assert spec.profiles[0].count==count
    assert spec.profiles[0].strategy==strategy


def test_natural_range_and_geometry():
    spec=interpret("input.mp4","Create 3 videos between 8 and 10 minutes in 16:9 at 720p",[Profile()])
    p=spec.profiles[0]
    assert (p.duration.minimum,p.duration.maximum,p.count)==(480,600,3)
    assert (p.width,p.height)==(1280,720)


def test_targeted_and_excluded():
    spec=interpret("input.mp4","Find moments discussing NVIDIA, CUDA, or AMD excluding cryptocurrency.",[Profile()])
    assert spec.mode=="TARGETED"
    assert spec.conditions.keywords==["NVIDIA","CUDA","AMD"]
    assert spec.conditions.exclude==["cryptocurrency"]


def test_unsupported_natural_request():
    with pytest.raises(UnsupportedRequest): interpret("input.mp4","Find scenes where the robot loses balance",[Profile()])


def test_loopback_only(settings):
    with pytest.raises(ValidationError): Settings(local_llm_url="https://api.openai.com/v1")
    with pytest.raises(ValidationError): Settings(additional_paid_api_budget=1)


def test_input_allowlist(settings):
    media=Path(settings.root)/"outside.mp4"
    media.write_bytes(b"x")
    with pytest.raises(ValueError): validate_input(media,settings.allowed_inputs)
    valid=Path(settings.root)/"input"/"safe.mp4"
    valid.write_bytes(b"x")
    assert validate_input(valid,settings.allowed_inputs)==valid.resolve()


def test_metadata_tags_count():
    assert tag_length(["Foo-Baz","Foo Baz"])==17
    tags=tags_for("NVIDIA CUDA machine learning AI agents "*100,Conditions(keywords=["NVIDIA"]))
    assert tag_length(tags)<=500
    assert all("#" not in t for t in tags)
    assert "NVIDIA" in tags


def test_invalid_plan_and_unknown_fields():
    p=Profile(duration=Duration(target=30,minimum=30,maximum=30,strict=True))
    c=Candidate(id="clip_001",profile=p.name,title="Test",segments=[Segment(start=0,end=31,reason="test")],reason="test")
    with pytest.raises(ValidationError):
        EditingPlan(instruction="test",source="x",fingerprint="x",source_duration=60,mode="AUTO",profiles=[p],candidates=[c],director="test")
    with pytest.raises(ValidationError): JobSpec(source="x",untrusted_command="delete everything")
