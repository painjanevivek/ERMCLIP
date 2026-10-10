from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from . import director, media, metadata, quality, subtitles
from .models import EditingPlan, JobSpec, Transcript
from .provider import LocalModel
from .transcribe import import_transcript, transcribe
from .util import Cancelled, atomic_json, atomic_text, fingerprint, slug, validate_input


def analysis_key(identity, spec, settings):
    data={"source":identity,"whisper_model":settings.whisper_model,"scene_analysis":settings.scene_analysis,"transcript_hash":fingerprint(Path(spec.transcript)) if spec.transcript else None,"schema":1}
    if spec.transcript_language:
        data["language"] = spec.transcript_language
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def analyse(spec,settings,identity,check_cancel=None):
    source=Path(spec.source)
    info=media.probe(source)
    cache=settings.path/"cache"/"analysis"/analysis_key(identity,spec,settings)
    cache.mkdir(parents=True,exist_ok=True)
    transcript_path=cache/"transcript.json"
    reused=transcript_path.exists()
    if reused:
        transcript=Transcript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
    elif spec.transcript:
        transcript=import_transcript(Path(spec.transcript),info["duration"])
        atomic_json(transcript_path,transcript.model_dump())
    elif info["audio"]:
        transcript=transcribe(source,cache,settings,check_cancel,language=spec.transcript_language)
        atomic_json(transcript_path,transcript.model_dump())
    else:
        transcript=Transcript(engine="no-audio",passages=[],warnings=["No source audio. Visual-only selection is not supported."])
        atomic_json(transcript_path,transcript.model_dump())
    visuals_path=cache/"visuals.json"
    if visuals_path.exists():
        visuals=json.loads(visuals_path.read_text(encoding="utf-8"))
    else:
        visuals=media.scan_visuals(source,info,cache,settings.process_timeout,check_cancel,settings.scene_analysis)
        atomic_json(visuals_path,visuals)
    atomic_json(cache/"source.json",{"source":str(source),"fingerprint":identity,"probe":info})
    return info,transcript,visuals,cache,reused


def process(job,settings,store,shutdown=None):
    started=time.monotonic()
    spec=JobSpec.model_validate(job["spec"])
    source=validate_input(spec.source,settings.allowed_inputs)
    initial_stat=(source.stat().st_size,source.stat().st_mtime_ns)
    identity=fingerprint(source)
    checkpoint=job["checkpoint"]
    if checkpoint.get("source_fingerprint") and checkpoint["source_fingerprint"]!=identity:
        raise ValueError("Source changed after job submission")
    output=settings.path/"output"/slug(source.stem)/job["id"]
    output.mkdir(parents=True,exist_ok=True)
    media.ensure_space(output,settings.min_free_gb, max(50*1024**2,sum(p.width*p.height*p.duration.maximum*(p.count or 3)//6 for p in spec.profiles)))
    def cancelled():
        return bool(store.get(job["id"])["cancel"] or (shutdown and shutdown()))
    def stage(name):
        if cancelled(): raise Cancelled()
        store.update(job["id"],stage=name,checkpoint=checkpoint,output=str(output))
        store.event(job["id"],name,{"source":source.name})
    stage("analysis")
    info,transcript,visuals,cache,reused=analyse(spec,settings,identity,cancelled)
    checkpoint["analysis_cache"]=str(cache)
    stage("planning")
    def record_model_call(count):
        checkpoint["model_calls"]=count
        store.update(job["id"],checkpoint=checkpoint)
    model=LocalModel(settings,checkpoint.get("model_calls",0),record_model_call)
    plan_path=output/"editing_plan.json"
    if plan_path.exists():
        editing=EditingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if editing.fingerprint!=identity:
            raise ValueError("Saved plan source identity mismatch")
    else:
        editing=director.plan(spec,transcript,info,identity,settings,cache,model,store.preferences())
        atomic_json(plan_path,editing.model_dump())
    atomic_json(output/"analysis_reference.json",{"cache":str(cache),"reused":reused,"transcript_engine":transcript.engine,"visual_engine":visuals["engine"]})
    matcher=director.Matcher(spec,transcript,settings,cache)
    results=checkpoint.get("outputs",[])
    # Resume only packages with matching plan, valid files, and saved final evaluation.
    existing={(r["profile"],r["id"]):r for r in results}
    stage("rendering")
    for index,original in enumerate(editing.candidates):
        if cancelled(): raise Cancelled()
        profile=next(p for p in editing.profiles if p.name==original.profile)
        base=output/profile.name/original.id
        base.parent.mkdir(parents=True,exist_ok=True)
        saved=existing.get((profile.name,original.id))
        if saved and base.with_suffix(".mp4").exists() and base.with_suffix(".md").exists() and base.with_name(base.name+"_quality.json").exists():
            media.probe(base.with_suffix(".mp4"))
            continue
        candidate=original.model_copy(deep=True)
        before=quality.pre_render(spec,candidate,profile,transcript,info,matcher)
        if any(f.severity=="hard" for f in before):
            report={"status":"rejected","findings":[f.model_dump() for f in before],"rendered":False}
            atomic_json(base.with_name(base.name+"_quality.json"),report)
            record={"id":candidate.id,"profile":profile.name,"status":"rejected","duration":candidate.duration,"path":None,"reason":"Pre-render hard violation"}
        else:
            history=[]
            while True:
                ass,cues=subtitles.write(transcript,candidate,profile,base)
                rendered=media.render(source,info,candidate,profile,ass,base.with_suffix(".mp4"),settings,visuals,cancelled)
                report=quality.evaluate(spec,candidate,profile,transcript,info,matcher,base.with_suffix(".mp4"),cues,settings,model,cancelled,rendered.get("speaker_tracking"))
                history.append({"revision":candidate.revision,"status":report["status"],"weighted_score":report["weighted_score"],"findings":report["findings"]})
                atomic_json(base.with_name(base.name+f"_quality_v{candidate.revision}.json"),report)
                if report["status"] not in ("revision_required","rejected") or candidate.revision>=settings.revisions:
                    break
                revised=quality.revise(candidate,report["findings"],transcript,profile,info["duration"])
                if revised is None or not matcher.validates_candidate(transcript,revised):
                    break
                # Revalidate the complete plan before a revised render.
                proposed=editing.model_copy(deep=True)
                proposed.candidates[index]=revised
                editing=EditingPlan.model_validate(proposed.model_dump())
                candidate=revised
                atomic_json(plan_path,editing.model_dump())
            if report["status"]=="revision_required":
                report["status"]="review_required"
                report["remaining_revision_issues"]=True
            report["history"]=history
            report["render_encoder"]=rendered["encoder"]
            atomic_json(base.with_name(base.name+"_quality.json"),report)
            duration=float(rendered["probe"]["video"].get("duration",rendered["probe"]["duration"]))
            tags=metadata.write(base,candidate,profile,spec,transcript,duration,report)
            media.thumbnail(base.with_suffix(".mp4"),base.with_name(base.name+"_thumbnail.jpg"),min(5,duration/2))
            atomic_json(base.with_name(base.name+"_source_map.json"),{"segments":[s.model_dump() for s in candidate.segments],"source_fingerprint":identity,"source":str(source),"output_duration":duration})
            record={"id":candidate.id,"profile":profile.name,"status":report["status"],"duration":duration,"path":str(base.with_suffix(".mp4")),"metadata":str(base.with_suffix(".md")),"tags":tags,"revision":candidate.revision}
        results=[r for r in results if (r["profile"],r["id"])!=(record["profile"],record["id"])]+[record]
        checkpoint["outputs"]=results
        store.update(job["id"],checkpoint=checkpoint)
        store.event(job["id"],"output_ready",{"clip":candidate.id,"profile":profile.name,"status":record["status"],"duration":record["duration"],"path":record["path"]})
    if (source.stat().st_size,source.stat().st_mtime_ns)!=initial_stat:
        raise ValueError("Source changed during processing; results require resubmission")
    status="no_matches" if not results else "completed" if all(r["status"]=="passed" for r in results) else "review_required"
    manifest={"schema":1,"job_id":job["id"],"source":str(source),"fingerprint":identity,"status":status,"outputs":results,"warnings":editing.warnings,"analysis_cache":str(cache),"analysis_reused":reused,"processing_seconds":round(time.monotonic()-started,3),"model_calls":model.calls,"model_usage_this_attempt":model.usage,"model_endpoint":settings.local_llm_url,"director_model":settings.director_model,"critic_model":settings.critic_model,"additional_paid_api_cost":0}
    atomic_json(output/"manifest.json",manifest)
    summary=f"# ERMCLIP result\n\nSource: {source.name}\n\nStatus: {status}\n\nProcessing time: {manifest['processing_seconds']} seconds\n\n"
    summary+="\n".join(f"- {r['profile']}/{r['id']}: {r['duration']:.2f}s; {r['status']}; {r['path']}" for r in results)
    summary+="\n\n"+"\n".join(f"- {w}" for w in editing.warnings)+"\n"
    if not results:
        summary+="\nNo qualifying source material met the request and duration constraints.\n"
    atomic_text(output/"summary.md",summary)
    store.update(job["id"],status=status,stage="done",error=None,checkpoint=checkpoint)
    store.event(job["id"],"finished",{"status":status,"outputs":len(results),"durations":[round(r["duration"],2) for r in results],"output":str(output),"seconds":manifest["processing_seconds"],"issues":editing.warnings})
    return manifest
