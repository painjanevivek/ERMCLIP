"""Rebuild only the corrected short, then retain the four completed exports."""
import json
from pathlib import Path
import shutil
from ermclip.config import load
from ermclip.models import EditingPlan, JobSpec
from ermclip.store import Store
from ermclip.util import atomic_json, fingerprint
from ermclip.worker import submit, worker

s=load(); s.stable_seconds=0; folder=s.path/'output/raj-shamani-batch'
master=EditingPlan.model_validate_json((folder/'editing-plan.json').read_text(encoding='utf-8'))
spec=JobSpec.model_validate_json((folder/'request.json').read_text(encoding='utf-8'))
profile=spec.profiles[0].model_copy(deep=True); profile.count=1
spec.profiles=[profile]; spec.instruction='Revise only clip_005. Retain the video economics story, source boundaries, speaker tracking and thumbnail layout. Restore the recognized ASR word we in the final captions. Keep all work local and mark the output for review.'
spec.revision_of='full-episode-clip005-token-retention'
editing=master.model_copy(deep=True,update={'profiles':[profile],'instruction':spec.instruction,
    'candidates':[c for c in master.candidates if c.id=='clip_005']})
editing=EditingPlan.model_validate(editing.model_dump())
plan_path=folder/'clip005-caption-revision-plan.json'; atomic_json(plan_path,editing.model_dump())
spec.approved_plan=str(plan_path)
atomic_json(folder/'clip005-caption-revision-request.json',JobSpec.model_validate(spec.model_dump()).model_dump())
store=Store(s.path/'state/jobs.sqlite3')
assert not any(j['status'] in ('queued','running','retry') for j in store.list())
job,created=submit(spec,s,store); print('Caption revision job: '+job,flush=True)
if created: worker(s,once=True)
row=store.get(job); assert row['status'] in ('completed','review_required'),row.get('error')
manifest=json.loads((Path(row['output'])/'manifest.json').read_text(encoding='utf-8'))
record=manifest['outputs'][0]; assert record['id']=='clip_005' and record['path']
base=Path(record['path']).with_suffix(''); dest=folder/'clip_005'
for suffix in ('.mp4','.ass','.srt','.md','_source_map.json','_speaker_tracking.json','_quality.json'):
    shutil.copyfile(base.with_name(base.name+suffix),dest.with_name(dest.name+suffix))
validation=json.loads((folder/'validation.json').read_text(encoding='utf-8'))
validation['outputs']=[{**record,'batch_path':str(dest.with_suffix('.mp4'))} if r['id']=='clip_005' else r for r in validation['outputs']]
validation['caption_revision_job']=job; validation['caption_revision_usage']=manifest['model_usage_this_attempt']
assert fingerprint(Path(spec.source))==validation['source_sha256']
atomic_json(folder/'validation.json',validation)
print('Corrected clip_005; four earlier exports retained.',flush=True)
