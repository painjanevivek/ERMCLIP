import json
from pathlib import Path

from ermclip.config import Settings
from ermclip.models import Passage, Transcript
from ermclip.transcribe import transcribe
from ermclip.util import atomic_json


def test_managed_llm_releases_gpu_before_local_asr(settings,monkeypatch,tmp_path):
    settings=Settings.model_validate({**settings.model_dump(),'local_llm_url':'http://127.0.0.1:8088/v1','director_model':'ermclip-qwen35-9b','critic_model':'ermclip-qwen35-9b','managed_local_model':True,'whisper_device':'auto','min_gpu_free_mb':2000})
    readings=iter([{'free_mb':500},{'free_mb':7500}])
    monkeypatch.setattr('ermclip.media.gpu',lambda:next(readings))
    stopped=[]
    monkeypatch.setattr('ermclip.local_runtime.stop',lambda s:stopped.append(s.director_model))
    def run(args,**kwargs):
        if args[0]=='ffmpeg': Path(args[-1]).write_bytes(b'fixture')
        else:
            task=json.loads(Path(args[-1]).read_text())
            assert task['device']=='cuda' and task['download'] is False
            atomic_json(Path(task['output']),Transcript(engine='faster-whisper/small/cuda',passages=[Passage(start=0,end=1,text='A source sentence.')]).model_dump())
    monkeypatch.setattr('ermclip.transcribe.run',run)
    result=transcribe(tmp_path/'source.mp4',tmp_path,settings)
    assert stopped==['ermclip-qwen35-9b'] and result.engine.endswith('/cuda')
    assert not (tmp_path/'speech.wav').exists()
