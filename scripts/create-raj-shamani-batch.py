"""Plan or render additional shorts from the entire original episode, offline."""
import argparse
import json
from pathlib import Path
import shutil
from ermclip.config import load
from ermclip.director import Matcher, text_for
from ermclip.long_source import plan_full_source
from ermclip.media import probe
from ermclip.models import Duration, JobSpec, Transcript
from ermclip.provider import LocalModel
from ermclip.request import source_context
from ermclip.store import Store
from ermclip.util import atomic_json, fingerprint
from ermclip.worker import submit, worker, worker_lock


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('phase',choices=['plan','render']); args=parser.parse_args()
    s=load(); s.stable_seconds=0
    folder=s.path/'output/raj-shamani-batch'; folder.mkdir(parents=True,exist_ok=True)
    analysis=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
    source=Path(analysis['source']); identity=analysis['fingerprint']
    if fingerprint(source)!=identity: raise ValueError('Source changed')
    store=Store(s.path/'state/jobs.sqlite3')
    assert not any(j['status'] in ('queued','running','retry') for j in store.list()),'Finish existing jobs first'
    plan_path=folder/'editing-plan.json'; request_path=folder/'request.json'
    if args.phase=='plan':
        transcript=Transcript.model_validate_json((folder/'full-transcript.json').read_text(encoding='utf-8'))
        spec=JobSpec(source=str(source), instruction='Create five more useful podcast shorts from the full Raj Shamani and Sravanth Aluru episode. Use distinct, complete practical stories about startups, AI, timing, business or entrepreneurship. Keep the question and full answer when needed. Avoid teaser montages and incomplete claims. Do not repeat the existing startup-path and founder-mindset shorts. Center the active speaker. Keep all processing local and leave outputs for review.',
            transcript=str(folder/'full-transcript.json'),transcript_language='en',podcast_mode='on',revision_of='full-episode-batch-v1')
        spec=source_context(spec,s)
        p=spec.profiles[0]; p.count=5; p.duration=Duration(target=60,minimum=40,maximum=90)
        p.layout.credit='Sravanth Aluru | EP 572'
        spec=JobSpec.model_validate(spec.model_dump())
        model=LocalModel(s)
        with worker_lock(s.path/'state/worker.lock'):
            plan=plan_full_source(spec,transcript,probe(source),identity,s,Path(analysis['cache']),model,
                Matcher(spec,transcript,s,Path(analysis['cache'])),excluded=[(308.36,341.2),(2994.54,3083.68)])
        atomic_json(plan_path,plan.model_dump())
        spec.approved_plan=str(plan_path); atomic_json(request_path,spec.model_dump())
        atomic_json(folder/'selection-usage.json',model.usage)
        for c in plan.candidates:
            print(json.dumps({'id':c.id,'title':c.title,'segments':[x.model_dump() for x in c.segments],
                              'actual_speech':text_for(transcript,c)},ensure_ascii=False),flush=True)
    else:
        spec=JobSpec.model_validate_json(request_path.read_text(encoding='utf-8'))
        assert all(p.framing=='speaker' and p.layout.preset=='podcast_hero' and p.captions.preset=='short_yellow' for p in spec.profiles), 'Podcast batch requires the requested style and tracker'
        job,created=submit(spec,s,store); print('Batch job: '+job,flush=True)
        atomic_json(folder/'job.json',{'job':job})
        if created: worker(s,once=True)
        row=store.get(job); print('Job status: '+row['status'],flush=True)
        assert row['status'] in ('completed','review_required'),row.get('error')
        manifest=json.loads((Path(row['output'])/'manifest.json').read_text(encoding='utf-8'))
        outputs=[]
        for record in manifest['outputs']:
            if not record['path']: continue
            base=Path(record['path']).with_suffix(''); dest=folder/record['id']
            for suffix in ('.mp4','.ass','.srt','.md','_source_map.json','_speaker_tracking.json','_quality.json'):
                path=base.with_name(base.name+suffix)
                if path.exists(): shutil.copyfile(path,dest.with_name(dest.name+suffix))
            outputs.append({**record,'batch_path':str(dest.with_suffix('.mp4'))})
        assert fingerprint(source)==identity
        assert manifest['additional_paid_api_cost']==0
        evidence=json.loads(plan_path.read_text(encoding='utf-8'))['constraints']['coverage_evidence']
        shutil.copyfile(evidence,folder/'selection-evidence.json')
        atomic_json(folder/'validation.json',{'job':job,'source_unchanged':True,'source_sha256':identity,
            'outputs':outputs,'model_usage':manifest['model_usage_this_attempt'],'additional_paid_api_cost':0,
            'review_required':True,'selection_evidence':str(folder/'selection-evidence.json')})
        print(json.dumps({'outputs':[x['batch_path'] for x in outputs],'paid_api_cost':0}),flush=True)


if __name__=='__main__': main()
