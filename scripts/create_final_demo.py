"""Make focused review copies after the full local workflow validation."""
import json
from pathlib import Path
import shutil
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ermclip.config import load
from ermclip.models import Conditions, Duration, EditingPlan, JobSpec, Profile
from ermclip.store import Store
from ermclip.util import atomic_json, fingerprint
from ermclip.worker import submit, worker


def main():
    s=load(); s.stable_seconds=0
    original=json.loads((s.path/'state'/'real-demo-source.json').read_text())
    source=original['source']; identity=original['sha256']
    store=Store(s.path/'state'/'jobs.sqlite3')
    assert not any(j['status'] in ('queued','running','retry') for j in store.list())
    records=[]
    previous=json.loads((s.path/'state'/'final-demo-progress.json').read_text())['jobs'] if '--resume' in sys.argv else []
    def execute(label,spec):
        saved=next((r for r in previous if r['label']==label),None)
        if saved and any(o['status']=='rejected' for o in saved['outputs']): saved=None
        if saved:
            old=store.get(saved['job'])['spec']
            for key in ('source','instruction','mode','conditions','profiles','approved_plan'):
                assert old[key]==spec.model_dump()[key],f'Cannot reuse changed {key}'
            records.append(saved)
            atomic_json(s.path/'state'/'final-demo-progress.json',{'jobs':records})
            print(label+': reused '+saved['job'],flush=True)
            return json.loads(Path(saved['manifest']).read_text()),EditingPlan.model_validate_json((Path(saved['manifest']).parent/'editing_plan.json').read_text())
        spec.revision_of='final-demo-'+str(time.time_ns())
        job,_=submit(spec,s,store); print(label+': '+job,flush=True)
        worker(s,once=True)
        row=store.get(job)
        assert row['status'] in ('completed','review_required'),row
        folder=Path(row['output'])
        manifest=json.loads((folder/'manifest.json').read_text())
        assert manifest['additional_paid_api_cost']==0
        records.append({'label':label,'job':job,'manifest':str(folder/'manifest.json'),'usage':manifest['model_usage_this_attempt'],'outputs':manifest['outputs']})
        atomic_json(s.path/'state'/'final-demo-progress.json',{'jobs':records})
        return manifest,EditingPlan.model_validate_json((folder/'editing_plan.json').read_text())
    p=Profile(name='highlighter_16x9',ratio='16:9',width=1280,height=720,duration=Duration(target=30,minimum=20,maximum=40),count=1,framing='pad')
    p.captions.preset='highlighter'; p.captions.max_chars=30
    spec=JobSpec(source=source,instruction='Select one entertaining, self-contained technical explanation of a challenge in building this unusually wide car. Include the challenge, the solution, and a clear conclusion. Avoid sponsor messages and merchandise pitches. Choose fewer clips if no useful material meets these rules.',conditions=Conditions(exclude=['sponsor','Bamboo','merch','propdepartment.com','X-Tool']),profiles=[p])
    execute('auto-corrected',spec)
    p=p.model_copy(deep=True,update={'name':'bold_lime_16x9','duration':Duration(target=26,minimum=20,maximum=32)})
    p.captions.preset='bold_lime'
    spec=JobSpec(source=source,instruction='Select the focused complete explanation of the ten-foot width choice and special permits. End after the practical conclusion about keeping things simple. Avoid the next discussion about floors, roofs or sheet metal. Keep all selected speech intact.',mode='TARGETED',conditions=Conditions(keywords=['10 feet'],exclude=['sheet metal','floor','roof','sponsor']),profiles=[p])
    manifest,editing=execute('focused-targeted',spec)
    assert len(editing.candidates)==1
    original_candidate=editing.candidates[0]
    portrait=p.model_copy(deep=True,update={'name':'momentum_9x16','ratio':'9:16','width':1080,'height':1920,'framing':'blur'})
    portrait.captions.preset='momentum'
    digital=portrait.model_copy(deep=True,update={'name':'digital_highlights_9x16'})
    digital.captions.preset='digital_highlights'
    spec=spec.model_copy(deep=True,update={'profiles':[portrait,digital]})
    plan=EditingPlan(instruction=spec.instruction,source=source,fingerprint=identity,source_duration=editing.source_duration,mode=spec.mode,profiles=spec.profiles,candidates=[original_candidate.model_copy(deep=True,update={'profile':p.name}) for p in spec.profiles],director='same-local-director-choice-restyled')
    path=s.path/'state'/'final-demo-style-plan.json'; atomic_json(path,plan.model_dump()); spec.approved_plan=str(path)
    execute('focused-styles',spec)
    exports=[]
    folder=s.path/'output'/'real-demo'; folder.mkdir(exist_ok=True)
    for record in records:
        for item in record['outputs']:
            source_video=Path(item['path'])
            report=json.loads(source_video.with_name(source_video.stem+'_quality.json').read_text())
            assert report['status']!='rejected',report
            stem=f"{len(exports)+1:02}_"+item['profile']
            for file in source_video.parent.glob(source_video.stem+'*'):
                if file.is_file(): shutil.copyfile(file,folder/(stem+file.name[len(source_video.stem):]))
            saved_plan=EditingPlan.model_validate_json((Path(record['manifest']).parent/'editing_plan.json').read_text())
            saved_candidate=next(c for c in saved_plan.candidates if c.profile==item['profile'] and c.id==item['id'])
            exports.append({'path':str(folder/(stem+'.mp4')),'profile':item['profile'],'job':record['job'],'status':report['status'],'score':report['weighted_score'],'duration':item['duration'],'source_segments':[seg.model_dump() for seg in saved_candidate.segments]})
    assert fingerprint(Path(source))==identity
    result={'source':source,'source_sha256':identity,'source_unchanged':True,'model':s.director_model,'paid_api_cost':0,'review_before_publication':True,'jobs':records,'exports':exports}
    atomic_json(s.path/'docs'/'final-demo.json',result)
    atomic_json(folder/'review-index.json',result)
    print('FOCUSED DEMO READY: '+str(folder),flush=True)


if __name__=='__main__':main()
