from pathlib import Path
import os
import shutil

import pytest

from ermclip.config import Settings
from ermclip.models import Passage, Transcript, Word
from ermclip.util import atomic_json, run


@pytest.fixture
def settings(tmp_path):
    config=Settings(root=str(tmp_path),allowed_inputs=[str(tmp_path/"input")],stable_seconds=0,min_free_gb=0,encoder="cpu",scene_analysis=False,whisper_device="cpu")
    config.prepare()
    return config


def synthetic_transcript(duration):
    passages=[]
    i=0
    while i*10+10<=duration:
        start=i*10
        text=f"NVIDIA CUDA tools explain problem {i+1}. A useful example shows how AI agents can solve this task."
        tokens=text.split()
        step=10/len(tokens)
        words=[Word(start=start+j*step,end=start+(j+1)*step,text=token) for j,token in enumerate(tokens)]
        passages.append(Passage(start=start,end=start+10,text=text,words=words))
        i+=1
    return Transcript(engine="synthetic-fixture-not-speech-recognition",language="en",passages=passages)


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def source_video(media_dir):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is unavailable")
    source=media_dir/"sample.mp4"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=10:duration=70","-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=70","-c:v","libx264","-preset","ultrafast","-c:a","aac","-shortest",str(source)],timeout=180)
    return source


@pytest.fixture(scope="session")
def long_video(media_dir):
    source=media_dir/"long.mp4"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=10:duration=920","-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=920","-c:v","libx264","-preset","ultrafast","-c:a","aac","-shortest",str(source)],timeout=300)
    return source
