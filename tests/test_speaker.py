import json
from pathlib import Path

import pytest

from ermclip.config import Settings
from ermclip.models import Candidate, Duration, JobSpec, Profile, Segment
from ermclip.request import interpret
from ermclip.speaker import FaceTracks, SpeakerChoice, analyse, filter_graph, valid_points
from ermclip.util import Cancelled, UnsupportedRequest, run


def face(tid, x, score):
    return {"id":tid,"x":x,"score":score}


def test_audio_score_wins_over_face_size_and_switch_is_stable():
    chooser = SpeakerChoice()
    # A listener could have a much larger face. Size is not an input to selection.
    a = [face(1,.2,.93),face(2,.8,.12)]
    assert chooser.choose(0,a)["fallback"]
    assert chooser.choose(.2,a)["fallback"]
    assert chooser.choose(.4,a)["speaker"] == 1
    b = [face(1,.2,.1),face(2,.8,.94)]
    assert chooser.choose(.6,b)["fallback"]
    assert chooser.choose(.8,a)["speaker"] == 1  # Brief score noise cannot switch.
    assert chooser.choose(1,b)["fallback"]
    assert chooser.choose(1.4,b)["speaker"] == 2
    assert chooser.center == .8


@pytest.mark.parametrize("faces,speech", [([],True),([face(1,.2,.95)],False),
    ([face(1,.2,.69)],True),([face(1,.2,.91),face(2,.8,.85)],True)])
def test_uncertain_offscreen_silence_overlap_keeps_full_frame(faces,speech):
    chooser=SpeakerChoice(current=1)
    assert chooser.choose(5,faces,speech)["fallback"]
    assert chooser.current is None


def test_scene_cut_resets_choice_and_face_identity():
    tracks=FaceTracks()
    first=next(iter(tracks.update([(10,10,30,30)])))
    assert next(iter(tracks.update([(12,10,30,30)]))) == first
    tracks.reset()
    assert next(iter(tracks.update([(12,10,30,30)]))) != first
    chooser=SpeakerChoice(current=1)
    assert chooser.choose(3,[face(1,.2,.95)],scene_cut=True)["fallback"]


def test_confirmed_speaker_tolerates_small_score_dips_but_not_listener_or_silence():
    chooser=SpeakerChoice()
    chooser.choose(0,[face(1,.3,.95)])
    assert chooser.choose(.4,[face(1,.3,.95)])["speaker"]==1
    assert chooser.choose(.6,[face(1,.3,.65)])["speaker"]==1
    assert chooser.choose(.8,[face(1,.3,.65),face(2,.8,.7)])["fallback"]
    chooser.choose(1,[face(1,.3,.95)])
    chooser.choose(1.4,[face(1,.3,.95)])
    assert chooser.choose(1.6,[face(1,.3,.95)],speech=False)["fallback"]


def test_podcast_routing_preserves_defaults_and_operator_full_frame():
    default=Profile(framing="pad")
    spec=interpret("episode.mp4","Create the best podcast clips with the active speaker centered",[default])
    assert spec.profiles[0].framing == "speaker"
    assert default.framing == "pad"
    assert JobSpec(source="my podcast.mp4").profiles[0].framing == "speaker"
    assert JobSpec(source="podcast.mp4",podcast_mode="off").profiles[0].framing == "smart"
    assert JobSpec(source="podcast.mp4",instruction="Keep the full frame").profiles[0].framing == "smart"
    with pytest.raises(UnsupportedRequest):
        interpret("episode.mp4","Create clips with speaker John only",[default])


def test_bad_timeline_and_crop_bounds(tmp_path):
    assert not valid_points([{"time":0,"center":float('nan'),"fallback":False}],2)
    assert not valid_points([{"time":2,"center":.5,"fallback":False}],2)
    assert not valid_points([{"time":0,"center":.5,"fallback":False}]*2,2)
    p=Profile(ratio="1:1",width=200,height=200,framing="speaker")
    track={"source_start":10,"source_end":12,"points":[
        {"time":0,"center":0,"fallback":False},{"time":1,"center":1,"fallback":False}]}
    command=tmp_path/"speaker.cmd"
    filter_graph(p,{"width":400,"height":200},track,command)
    assert "crop@focus x 0" in command.read_text()
    assert "crop@focus x 200" in command.read_text()


def test_known_podcast_source_is_automatic_and_explicit_off_is_preserved(settings):
    from ermclip.request import source_context
    path=settings.path/'input'/'episode.mp4'
    settings.podcast_sources=[str(path)]
    spec=JobSpec(source=str(path),profiles=[Profile(framing='pad')])
    result=source_context(spec,settings)
    assert result.podcast_mode=='on' and result.profiles[0].framing=='speaker'
    assert spec.profiles[0].framing=='pad'
    disabled=JobSpec(source=str(path),podcast_mode='off',profiles=[Profile(framing='pad')])
    assert source_context(disabled,settings).profiles[0].framing=='pad'
    other=JobSpec(source=str(path.with_name('other.mp4')),profiles=[Profile(framing='pad')])
    assert source_context(other,settings).profiles[0].framing=='pad'


def test_missing_assets_fallback_is_reported_and_cancel_is_not_swallowed(settings):
    s=Segment(start=10,end=15,reason="test")
    result=analyse(Path("unused"),s,{"audio":True},settings,"identity")
    assert result["coverage"] == 0 and result["warning"] and result["review_required"]
    with pytest.raises(Cancelled):
        analyse(Path("unused"),s,{"audio":False},settings,"identity",lambda:True)


def test_tracking_cache_is_reused_only_for_identical_cuts(settings,monkeypatch):
    import ermclip.speaker as speaker
    calls=[]
    monkeypatch.setattr(speaker,"ready",lambda root:True)
    monkeypatch.setattr(speaker,"network",lambda root:None)
    def detect(source,start,end,*args):
        calls.append((start,end))
        return {"points":[{"time":0,"center":.3,"speaker":1,"fallback":False}],"counts":{}}
    monkeypatch.setattr(speaker,"_analyse",detect)
    one=Segment(start=10,end=15,reason="first")
    a=analyse(Path("unused"),one,{"audio":True},settings,"sha")
    b=analyse(Path("unused"),one,{"audio":True},settings,"sha")
    assert a["coverage"]==1 and not a["cache_reused"] and b["cache_reused"]
    analyse(Path("unused"),Segment(start=20,end=25,reason="second"),{"audio":True},settings,"sha")
    analyse(Path("unused"),one,{"audio":True},settings,"different-source")
    assert calls==[(10,15),(20,25),(10,15)]


@pytest.mark.integration
def test_actual_crop_changes_and_fallback_without_audio_cuts(tmp_path,settings,monkeypatch):
    import cv2
    import numpy as np
    from ermclip.media import probe, render
    source=tmp_path/"panels.mp4"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",
         "color=c=black:s=640x360:r=25:d=4,drawbox=x=40:y=100:w=160:h=160:color=red:t=fill,drawbox=x=440:y=100:w=160:h=160:color=blue:t=fill",
         "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=4","-c:v","libx264","-preset","ultrafast","-c:a","aac","-shortest",str(source)])
    tracking={"source_start":1,"source_end":4,"points":[
        {"time":0,"center":.1875,"speaker":1,"fallback":False},
        {"time":1,"center":.8125,"speaker":2,"fallback":False},
        {"time":2,"center":.5,"speaker":None,"fallback":True}],"review_required":True}
    monkeypatch.setattr("ermclip.speaker.analyse",lambda *args,**kwargs:tracking)
    profile=Profile(ratio="1:1",width=180,height=180,framing="speaker",captions={"burn":False},normalize_audio=False,fades=False)
    candidate=Candidate(id="clip_001",profile=profile.name,title="test",reason="test",segments=[Segment(start=1,end=4,reason="test")])
    output=tmp_path/"clip.mp4"
    result=render(source,probe(source),candidate,profile,tmp_path/"none.ass",output,settings,{})
    cap=cv2.VideoCapture(str(output))
    frames=[]
    for t in (.5,1.5,2.5):
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
        ok, frame=cap.read(); assert ok
        frames.append(frame)
    cap.release()
    # Actual encoded pixels, not just filter text: center changes from red to blue.
    assert frames[0][90,90,2]>180 and frames[0][90,90,0]<30
    assert frames[1][90,90,0]>180 and frames[1][90,90,2]<30
    assert frames[2][90,34,2]>180 and frames[2][90,146,0]>180
    assert np.mean(frames[2][:30])<5  # Padded full frame, both panels visible.
    info=probe(output)
    assert abs(float(info["video"]["duration"])-3)<.05
    assert abs(float(info["audio_stream"]["duration"])-3)<.05
    assert result["speaker_tracking"]["output_offsets"] == [0]
    assert json.loads(output.with_name("clip_speaker_tracking.json").read_text())["segments"][0]["source_start"]==1
