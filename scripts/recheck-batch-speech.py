"""Second offline ASR pass on only the chosen source audio; flag disagreements."""
import difflib
import json
import re
from pathlib import Path
from ermclip.config import load
from ermclip.director import text_for
from ermclip.local_runtime import stop
from ermclip.models import EditingPlan, Transcript
from ermclip.transcribe import transcribe
from ermclip.util import atomic_json, run
from ermclip.worker import worker_lock

s=load(); folder=s.path/'output/raj-shamani-batch'
s.whisper_model='medium'
plan=EditingPlan.model_validate_json((folder/'editing-plan.json').read_text(encoding='utf-8'))
t=Transcript.model_validate_json((folder/'full-transcript.json').read_text(encoding='utf-8'))
checks=[]
def tokens(text): return re.findall(r"[\w']+",text.lower())
with worker_lock(s.path/'state/worker.lock'):
    stop(s)
    for c in plan.candidates:
        target=folder/'speech-check'/c.id; target.mkdir(parents=True,exist_ok=True)
        saved=target/'transcript.json'
        if saved.exists(): second=Transcript.model_validate_json(saved.read_text(encoding='utf-8'))
        else:
            segment=c.segments[0]; audio=target/'selected.wav'
            run(['ffmpeg','-v','error','-y','-ss',str(segment.start),'-i',plan.source,'-t',str(c.duration),'-vn','-ac','1','-ar','16000',str(audio)],timeout=120)
            second=transcribe(audio,target,s,language='en'); atomic_json(saved,second.model_dump())
        first=text_for(t,c); actual=' '.join(p.text for p in second.passages)
        left,right=tokens(first),tokens(actual)
        sm=difflib.SequenceMatcher(None,left,right,autojunk=False)
        differences=[{'first':' '.join(left[i:j]),'second':' '.join(right[k:l])} for tag,i,j,k,l in sm.get_opcodes() if tag!='equal']
        checks.append({'id':c.id,'agreement':round(sm.ratio(),4),'first_speech':first,'second_speech':actual,
            'differences':differences,'engine':second.engine,'paid_api_cost':0,'review_required':True})
        atomic_json(folder/'speech-checks.json',checks)
        print(json.dumps({'id':c.id,'agreement':checks[-1]['agreement'],'differences':differences}),flush=True)
