"""Opt-in local editing and revision test on the user-specified car video."""
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ermclip.config import load
from ermclip.director import Matcher
from ermclip.local_runtime import ensure
from ermclip.media import gpu, probe
from ermclip.models import Candidate, Conditions, Duration, EditingPlan, JobSpec, Profile, Segment, Transcript
from ermclip.quality import pre_render
from ermclip.store import Store
from ermclip.util import atomic_json, fingerprint
from ermclip.worker import submit, worker


def main():
    settings=load()
    settings.stable_seconds=0
    settings.scene_analysis=False
    source_record=json.loads((settings.path/'state'/'real-demo-source.json').read_text())
    source=Path(source_record['source'])
    identity=fingerprint(source)
    assert identity==source_record['sha256']
    assert settings.director_model=='ermclip-qwen35-9b'
    assert settings.additional_paid_api_budget==0 and not settings.allow_model_download
    ensure(settings)
    store=Store(settings.path/'state'/'jobs.sqlite3')
    assert not any(j['status'] in ('queued','running','retry') for j in store.list())
    store.control('pause','0')
    stamp=str(time.time_ns())
    records=[]
    samples=[]
    done=threading.Event()
    def monitor():
        while not done.is_set():
            card=gpu()
            if card: samples.append({'time':time.time(),**card})
            done.wait(2)
    thread=threading.Thread(target=monitor,daemon=True)
    thread.start()
    def execute(label,spec):
        spec.revision_of='real-demo-'+stamp+'-'+label
        path=settings.path/'state'/('real-demo-'+label+'.json')
        atomic_json(path,spec.model_dump())
        job,created=submit(spec,settings,store)
        assert created
        print(label+': queued '+job,flush=True)
        worker(settings,once=True)
        row=store.get(job)
        assert row['status'] in ('completed','review_required','no_matches'),row
        manifest_path=Path(row['output'])/'manifest.json'
        manifest=json.loads(manifest_path.read_text())
        assert manifest['additional_paid_api_cost']==0
        reports=[]
        for output in manifest['outputs']:
            video=Path(output['path'])
            quality=json.loads(video.with_name(video.stem+'_quality.json').read_text())
            assert quality['critic']=='local-isolated-text'
            assert not any(f['code']=='critic_unavailable' for f in quality['findings'])
            assert video.with_suffix('.srt').is_file() and video.with_suffix('.md').is_file()
            assert probe(video)['audio']
            reports.append({'path':str(video),'status':quality['status'],'score':quality['weighted_score'],'history':quality['history'],'encoder':quality['render_encoder']})
        records.append({'label':label,'job':job,'manifest':str(manifest_path),'status':manifest['status'],'model_calls':manifest['model_calls'],'usage':manifest['model_usage_this_attempt'],'analysis_reused':manifest['analysis_reused'],'reports':reports})
        atomic_json(settings.path/'state'/'real-demo-progress.json',{'jobs':records})
        print(f"{label}: {manifest['status']}; outputs={len(reports)}; scores={[r['score'] for r in reports]}",flush=True)
        return manifest,reports,json.loads((Path(row['output'])/'editing_plan.json').read_text())
    try:
        profile=Profile(name='highlighter_16x9',ratio='16:9',width=1280,height=720,duration=Duration(target=35,minimum=20,maximum=55),count=1,framing='pad')
        profile.captions.preset='highlighter'
        profile.captions.max_chars=30
        auto=JobSpec(source=str(source),instruction='Select one entertaining, complete technical explanation from the car build. Prefer a clear challenge, an explanation of how the build solves it, and a complete conclusion. Preserve the full car in frame and all selected speech. Avoid sponsor messages and merchandise pitches.',profiles=[profile])
        execute('auto',auto)
        profile=profile.model_copy(deep=True,update={'name':'bold_lime_16x9'})
        profile.captions.preset='bold_lime'
        targeted=JobSpec(source=str(source),instruction='Select one complete explanation of why the car is ten feet wide and how special permits affect its use. Include the width choice and its practical conclusion. Keep all speech intact.',mode='TARGETED',conditions=Conditions(keywords=['10 feet']),profiles=[profile])
        manifest,reports,editing_data=execute('targeted',targeted)
        assert reports
        editing=EditingPlan.model_validate(editing_data)
        original=editing.candidates[0]
        cache=Path(manifest['analysis_cache'])
        transcript=Transcript.model_validate_json((cache/'transcript.json').read_text())
        portrait=profile.model_copy(deep=True,update={'name':'momentum_9x16','ratio':'9:16','width':1080,'height':1920,'framing':'blur'})
        portrait.captions.preset='momentum'
        digital=portrait.model_copy(deep=True,update={'name':'digital_highlights_9x16'})
        digital.captions.preset='digital_highlights'
        spec=targeted.model_copy(deep=True,update={'profiles':[portrait,digital]})
        candidates=[original.model_copy(deep=True,update={'profile':p.name}) for p in spec.profiles]
        plan=EditingPlan(instruction=spec.instruction,source=str(source),fingerprint=identity,source_duration=editing.source_duration,mode=spec.mode,profiles=spec.profiles,candidates=candidates,director='same-local-director-selection-restyled')
        plan_path=settings.path/'state'/'real-demo-style-plan.json'
        atomic_json(plan_path,plan.model_dump()); spec.approved_plan=str(plan_path)
        execute('style-variants',spec)
        revision_profile=profile.model_copy(deep=True,update={'name':'repaired_highlighter_16x9','duration':Duration(target=35,minimum=15,maximum=75)})
        revision_profile.captions.preset='highlighter'
        spec=targeted.model_copy(deep=True,update={'profiles':[revision_profile],'instruction':'Keep the full explanation of the ten-foot width and special permits. Repair cuts that remove part of a spoken statement.'})
        candidate=original.model_copy(deep=True,update={'profile':revision_profile.name,'revision':0})
        candidate.segments[0].start+=0.35
        candidate.segments[-1].end-=0.35
        before=pre_render(spec,candidate,revision_profile,transcript,probe(source),Matcher(spec,transcript,settings,cache))
        assert any(f.code=='incomplete_statement' for f in before)
        plan=EditingPlan(instruction=spec.instruction,source=str(source),fingerprint=identity,source_duration=editing.source_duration,mode=spec.mode,profiles=spec.profiles,candidates=[candidate],director='operator-deliberate-cut-test')
        plan_path=settings.path/'state'/'real-demo-revision-plan.json'
        atomic_json(plan_path,plan.model_dump()); spec.approved_plan=str(plan_path)
        _,revisions,_=execute('revision',spec)
        history=revisions[0]['history']
        assert len(history)>=2 and history[1]['revision']==1
        assert any(f['code']=='incomplete_statement' for f in history[0]['findings'])
        assert not any(f['code']=='incomplete_statement' for f in history[-1]['findings'])
        spec=targeted.model_copy(deep=True,update={'conditions':Conditions(keywords=['ERMCLIP_UNSPOKEN_TEST_TOKEN']),'instruction':'Return no clips if this exact test token is not spoken.'})
        empty,_,_=execute('no-match',spec)
        assert empty['status']=='no_matches' and empty['model_calls']==0
        assert fingerprint(source)==identity
        result={'passed':True,'time':time.time(),'source':str(source),'source_sha256':identity,'source_unchanged':True,'model':settings.director_model,'asr':transcript.engine,'passages':len(transcript.passages),'words':sum(len(p.words) for p in transcript.passages),'paid_api_cost':0,'jobs':records,'gpu_samples':samples,'limits':['Scores are uncalibrated. The isolated Critic reviews text and metrics, not pixels or sound.','Long-source selection uses a heuristic shortlist; omitted moments are not ranked by the model.','Caption previews approximate the references with installed font families.']}
        atomic_json(settings.path/'docs'/'real-demo-validation.json',result)
        print('REAL DEMO VALIDATION PASSED. Source unchanged. Paid API cost: 0.',flush=True)
    finally:
        done.set(); thread.join(timeout=5)
        atomic_json(settings.path/'state'/'real-demo-progress.json',{'jobs':records,'gpu_samples':samples})


if __name__=='__main__': main()
