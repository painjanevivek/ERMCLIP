"""Resolve a few ASR disagreements with a focused local vocabulary pass."""
import json
import subprocess
import sys
from ermclip.config import load
from ermclip.util import run, atomic_json

s=load(); folder=s.path/'output/raj-shamani-batch/speech-check'
for name,start,end in [('agility',3292.76,3327.04),('leaders',4498.18,4518.64),('sales',7399.99,7423.35)]:
    target=folder/name; target.mkdir(parents=True,exist_ok=True)
    audio=target/'source.wav'
    run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',s.podcast_sources[0],'-t',str(end-start),'-vn','-ar','16000','-ac','1',str(audio)],timeout=120)
    task={'audio':str(audio),'model':'medium','device':'cuda','download':False,'models':str(s.path/'cache/models'),
          'output':str(target/'transcript.json'),'language':'en','beam_size':10,
          'initial_prompt':'A business podcast in English. Vocabulary: advisors, CTOs, AI, OpenAI, incumbents, startups, leaders, layoffs, return on investment, ROI, low ASP products, video sells more.'}
    atomic_json(target/'task.json',task)
    run([sys.executable,'-m','ermclip.transcribe',str(target/'task.json')],timeout=180)
    t=json.loads((target/'transcript.json').read_text(encoding='utf-8'))
    print(name+': '+' '.join(p['text'] for p in t['passages']),flush=True)
