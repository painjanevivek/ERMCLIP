"""Use the larger local speech pass for selected cuts; retain full-source ASR."""
from pathlib import Path
from ermclip.config import load
from ermclip.models import EditingPlan, JobSpec, Transcript, Passage
from ermclip.util import atomic_json

s=load(); folder=s.path/'output/raj-shamani-batch'
plan=EditingPlan.model_validate_json((folder/'editing-plan.json').read_text(encoding='utf-8'))
original=Transcript.model_validate_json((folder/'full-transcript.json').read_text(encoding='utf-8'))
cuts=[segment for c in plan.candidates for segment in c.segments]
passages=[]
for p in original.passages:
    if not any(p.start<cut.end and p.end>cut.start for cut in cuts): passages.append(p)
    else:
        kept=[w for w in p.words if not any(w.start<cut.end and w.end>cut.start for cut in cuts)]
        if kept:
            passages.append(Passage(start=kept[0].start,end=kept[-1].end,text=' '.join(w.text.strip() for w in kept),words=kept))
for c in plan.candidates:
    raw=Transcript.model_validate_json((folder/'speech-check'/c.id/'transcript.json').read_text(encoding='utf-8'))
    # These two disagreements are confirmed by the full-source small model
    # and the focused medium pass with business vocabulary.
    words=[w for p in raw.passages for w in p.words]
    for index,w in enumerate(words):
        if c.id=='clip_003' and w.text.strip().lower()=='mostly' and index+1<len(words) and words[index+1].text.strip().lower()=='does':
            w.text=' most'; words[index+1].text=' leaders'
        if c.id=='clip_005' and w.text.strip().lower()=='sales': w.text=' sells'
    for p in raw.passages: p.text=' '.join(w.text.strip() for w in p.words)
    if c.id=='clip_005':
        # Original medium segment text and full-source ASR both recognize
        # "we are". Its zero-length "we" was previously filtered by the child.
        for w in words:
            if w.text.strip().lower()=='are' and 36<w.start<40:
                w.text=' we are'
        for p in raw.passages: p.text=' '.join(w.text.strip() for w in p.words)
    offset=c.segments[0].start
    for p in raw.passages:
        mapped=p.model_copy(deep=True)
        for w in mapped.words:
            object.__setattr__(w,'start',w.start+offset); object.__setattr__(w,'end',min(w.end+offset,c.segments[-1].end))
        object.__setattr__(mapped,'start',mapped.start+offset)
        object.__setattr__(mapped,'end',min(mapped.end+offset,c.segments[-1].end))
        if mapped.end>mapped.start:
            mapped.words=[w for w in mapped.words if w.end>w.start]
            passages.append(mapped)
checked=Transcript(language='en',engine='faster-whisper/small/full + medium/selected-cuts/cuda',
    passages=sorted(passages,key=lambda p:p.start),warnings=['Selected captions were re-transcribed offline with Whisper medium. Compare disagreements in speech-checks.json; recognition still requires review.'])
target=folder/'caption-transcript.json'; atomic_json(target,Transcript.model_validate(checked.model_dump()).model_dump())
spec=JobSpec.model_validate_json((folder/'request.json').read_text(encoding='utf-8')); spec.transcript=str(target)
atomic_json(folder/'request.json',spec.model_dump())
print(str(target),flush=True)
atomic_json(folder/'caption-corrections.json',{'engine':'Whisper medium, offline, CUDA',
    'corrections':[{'clip':'clip_003','from':'mostly does','to':'most leaders','evidence':'Small full-source ASR and focused medium vocabulary pass agree.'},
                   {'clip':'clip_005','from':'video sales more','to':'video sells more','evidence':'Small full-source ASR and focused medium vocabulary pass agree.'},
                   {'clip':'clip_001','edit':'End after the CTO-advisor example; omit the later ambiguous phrase.'},
                   {'clip':'clip_005','from':'are effectively','to':'we are effectively','evidence':'Both ASR segment texts recognize we. Retain it in the adjoining are span because its independent duration was zero.'}],
    'paid_api_cost':0,'review_required':True})
