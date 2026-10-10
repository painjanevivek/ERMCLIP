"""Check actual media, subtitle word retention, timing, and speaker-track evidence."""
import html
import json
from pathlib import Path
import cv2
import numpy as np
from ermclip.config import load
from ermclip.director import text_for
from ermclip.media import probe
from ermclip.models import EditingPlan, Transcript
from ermclip.subtitles import timeline
from ermclip.transcribe import import_transcript
from ermclip.util import atomic_json, atomic_text

s=load(); folder=s.path/'output/raj-shamani-batch'
validation=json.loads((folder/'validation.json').read_text(encoding='utf-8'))
plan=EditingPlan.model_validate_json((folder/'editing-plan.json').read_text(encoding='utf-8'))
t=Transcript.model_validate_json((folder/'caption-transcript.json').read_text(encoding='utf-8'))
reports=[]; covers=[]; cards=[]
for record in validation['outputs']:
    path=Path(record['batch_path']); base=path.with_suffix('')
    candidate=next(c for c in plan.candidates if c.id==record['id'])
    # A worker revision may adjust boundaries; use its final source map if present.
    row_output=Path(record['path']).parents[1]/'editing_plan.json'
    actual=EditingPlan.model_validate_json(row_output.read_text(encoding='utf-8'))
    candidate=next(c for c in actual.candidates if c.id==record['id'])
    p=next(p for p in actual.profiles if p.name==candidate.profile)
    cues=timeline(t,candidate,p.captions.max_chars,3,join_passages=True)
    words=' '.join(cue.text for cue in cues).split()
    source_words=text_for(t,candidate).split()
    assert words==source_words, 'Caption words were dropped or reordered'
    assert all(0<=cue.start<cue.end<=candidate.duration+.2 for cue in cues)
    info=probe(path); assert (info['width'],info['height'])==(1080,1920) and info['audio']
    actual_srt=import_transcript(base.with_suffix('.srt'),info['duration'])
    assert ' '.join(p.text for p in actual_srt.passages).split()==source_words
    assert len(actual_srt.passages)==len(cues)
    assert all(abs(p.start-c.start)<=.001 and abs(p.end-c.end)<=.001 for p,c in zip(actual_srt.passages,cues))
    q=json.loads(base.with_name(base.name+'_quality.json').read_text(encoding='utf-8'))
    track=json.loads(base.with_name(base.name+'_speaker_tracking.json').read_text(encoding='utf-8'))
    assert not any(f['severity']=='hard' for f in q['findings'])
    cap=cv2.VideoCapture(str(path)); frames=[]
    for at in (3,candidate.duration*.3,candidate.duration*.6,candidate.duration-3):
        cap.set(cv2.CAP_PROP_POS_MSEC,at*1000); ok,frame=cap.read(); assert ok
        frames.append(cv2.resize(frame,(270,480)))
    cv2.imwrite(str(base.with_name(base.name+'-frames.jpg')),np.hstack(frames))
    focused=[point['time'] for segment in track['segments'] for point in segment['points'] if not point['fallback'] and 3<=point['time']<candidate.duration-2]
    cover_time=min(focused,key=lambda at:abs(at-10)) if focused else 3
    cap.set(cv2.CAP_PROP_POS_MSEC,cover_time*1000); ok,cover=cap.read(); assert ok
    cap.release(); cover=cv2.resize(cover,(270,480))
    cv2.imwrite(str(base.with_name(base.name+'-cover.jpg')),cover)
    covers.append(cover)
    reports.append({'id':candidate.id,'title':candidate.title,'duration':candidate.duration,
        'caption_words_retained':True,'actual_srt_verified':True,'cover_time':cover_time,'caption_cues':len(cues),
        'minimum_cue_seconds':min(c.end-c.start for c in cues),
        'fast_cues':[{'start':c.start,'end':c.end,'text':c.text} for c in cues if len(c.text)/(c.end-c.start)>28],
        'actual_speech':text_for(t,candidate),'speaker_tracking':track,'findings':q['findings'],
        'review_required':True})
    cards.append(f'<article><h2>{html.escape(candidate.title)}</h2><video controls preload="metadata" poster="{candidate.id}-cover.jpg" src="{candidate.id}.mp4"></video><p>{candidate.duration:.1f} seconds · Caption and speaker review required</p><a href="{candidate.id}.srt">Subtitles</a> · <a href="{candidate.id}_quality.json">Checks</a></article>')
if covers: cv2.imwrite(str(folder/'batch-covers.jpg'),np.hstack(covers))
atomic_json(folder/'caption-and-frame-checks.json',{'source_unchanged':validation['source_unchanged'],
    'additional_paid_api_cost':0,'checks':reports,'limits':['Word retention checks verify the transcript mapping, not perfect speech recognition.','Speaker activity and text critic scores remain uncalibrated.']})
atomic_text(folder/'index.html','<!doctype html><meta charset="utf-8"><title>Raj Shamani · Local shorts</title><style>body{margin:40px;background:#101010;color:#eee;font:16px Arial}main{display:flex;gap:24px;flex-wrap:wrap}article{width:270px}h2{font-size:20px;min-height:50px}video{width:270px;height:480px;background:black}a{color:#ffdf35}p{line-height:1.5}</style><h1>Five more stories from the full episode</h1><p>Local models only · Paid API cost: zero · Review before publication</p><main>'+''.join(cards)+'</main>')
print(json.dumps([{**{k:r[k] for k in ('id','title','duration','caption_words_retained','actual_srt_verified')},'fast_groups':len(r['fast_cues'])} for r in reports]),flush=True)
