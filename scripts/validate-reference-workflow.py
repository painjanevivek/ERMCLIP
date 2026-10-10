"""Render and check the user-supplied podcast reference style, without cloud calls."""
import json
from pathlib import Path
import shutil

from ermclip.config import load
from ermclip.models import Candidate, Duration, EditingPlan, JobSpec, Layout, Profile, Segment, Transcript
from ermclip.store import Store
from ermclip.util import atomic_json, fingerprint
from ermclip.worker import submit, worker


def main():
    s=load(); s.stable_seconds=0
    folder=s.path/'output/reference-style'
    original=Path(r'C:\Users\ASUS\Downloads\Startup Ideas Timing AI How To Build The Next Big Thing Sravanth Aluru FO572 Raj Shamani.mp4')
    identity=fingerprint(original)
    raw=Transcript.model_validate_json((folder/'source-transcript-en.json').read_text(encoding='utf-8'))
    mapped=raw.model_copy(deep=True)
    for p in mapped.passages:
        # Do not use assignment validation while translating nested timestamps.
        for w in p.words:
            object.__setattr__(w,'start',w.start+2992)
            object.__setattr__(w,'end',w.end+2992)
        object.__setattr__(p,'start',p.start+2992)
        object.__setattr__(p,'end',p.end+2992)
    mapped.warnings.append('Only source seconds 2992–3088 were transcribed for this reference edit. This is not a full-episode selection benchmark.')
    transcript=folder/'mapped-source-transcript.json'
    atomic_json(transcript,Transcript.model_validate(mapped.model_dump()).model_dump())
    profiles=[]; candidates=[]
    cuts=[(2.54,8.06),(48.5,75.36),(77.04,91.68)]
    for preset in ('reference_window','podcast_hero'):
        p=Profile(name=preset,framing='speaker',strategy='compilation',count=1,
            duration=Duration(target=47.02,minimum=40,maximum=60),
            layout=Layout(preset=preset,headline='Every Entrepreneur Will Relate' if preset=='podcast_hero' else 'Every Entrepreneur Will Relate to This',
                highlight='Entrepreneur' if preset=='podcast_hero' else None,
                credit='Sravanth Aluru | EP 572' if preset=='podcast_hero' else None))
        p.captions.preset='short_yellow'; p.captions.size=52; p.captions.max_chars=24
        profiles.append(p)
        candidates.append(Candidate(id='clip_001',profile=preset,title='Every Entrepreneur Will Relate: The Battle in Your Head',
            segments=[Segment(start=a+2992,end=b+2992,reason=reason) for (a,b),reason in zip(cuts,[
                'Complete opening claim matched to the supplied reference.',
                'Founder mindset explanation. Retain all speech.',
                'Remove a long spoken pause and end after the complete expectation/control conclusion.'])],
            reason='Use the same original podcast speech as the reference. Retain the claim, explanation and conclusion; do not copy its outro or stock footage.',
            narrative=['Entrepreneurs can give up before they need to.','Founders face an internal battle.','Expectations are in your control; outcomes are not.']))
        atomic_json(folder/(preset+'-profile.json'),p.model_dump())
    spec=JobSpec(source=str(original),instruction='Create a podcast short in the supplied reference style. Use the verified founder-mindset hook and full expectation/control conclusion. Preserve the speech, center the visible active speaker, and use short yellow captions. Keep all work local and leave it for review.',
        profiles=profiles,transcript=str(transcript),podcast_mode='on',transcript_language='en',revision_of='reference-style-v3')
    plan=EditingPlan(instruction=spec.instruction,source=str(original),fingerprint=identity,source_duration=7522,
        mode=spec.mode,profiles=spec.profiles,candidates=candidates,director='reference audio match + verified word boundaries',
        warnings=mapped.warnings, constraints={'paid_budget':0,'reference_source_offset':2992})
    plan_path=s.path/'state/requests/reference-style-plan.json'; atomic_json(plan_path,plan.model_dump())
    spec.approved_plan=str(plan_path)
    atomic_json(s.path/'state/requests/reference-style-job.json',spec.model_dump())
    store=Store(s.path/'state/jobs.sqlite3')
    assert not any(j['status'] in ('queued','running','retry') for j in store.list()),'Finish existing jobs before the demo.'
    job,created=submit(spec,s,store)
    print('Reference job: '+job,flush=True)
    if created: worker(s,once=True)
    row=store.get(job)
    print('Job status: '+row['status'],flush=True)
    assert row['status'] in ('completed','review_required'),row.get('error')
    manifest=json.loads((Path(row['output'])/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['additional_paid_api_cost']==0
    outputs=[]
    for record in manifest['outputs']:
        assert record['path'] and record['status']=='review_required',record
        base=Path(record['path']).with_suffix('')
        dest=folder/record['profile'].replace('_','-')
        for suffix in ('.mp4','.ass','.srt','.md','_source_map.json','_speaker_tracking.json','_quality.json','_thumbnail.jpg'):
            path=base.with_name(base.name+suffix)
            if path.exists(): shutil.copyfile(path,dest.with_name(dest.name+suffix))
        quality=json.loads(base.with_name(base.name+'_quality.json').read_text(encoding='utf-8'))
        assert not any(f['severity']=='hard' for f in quality['findings']),quality['findings']
        outputs.append({**record,'demo_path':str(dest.with_suffix('.mp4')),'findings':quality['findings']})
    unchanged=fingerprint(original)==identity
    assert unchanged
    atomic_json(folder/'validation.json',{'job':job,'source':str(original),'source_sha256':identity,'source_unchanged':unchanged,
        'outputs':outputs,'plan':plan.model_dump(),'reference_match':json.loads((folder/'reference-source-matches.json').read_text(encoding='utf-8')),
        'model_usage':manifest['model_usage_this_attempt'],'additional_paid_api_cost':0,'review_required':True})
    print(json.dumps({'job':job,'outputs':[x['demo_path'] for x in outputs],'cost':0}),flush=True)


if __name__=='__main__': main()
