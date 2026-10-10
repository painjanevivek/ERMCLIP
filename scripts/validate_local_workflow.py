"""Opt-in live CUDA/LLM/render validation using our own narrated test footage."""
import json
from pathlib import Path
import sys
import time
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ermclip.config import load
from ermclip.director import Matcher
from ermclip.local_runtime import ensure
from ermclip.media import gpu, probe
from ermclip.models import Candidate, Conditions, Duration, EditingPlan, JobSpec, Profile, Segment, Transcript
from ermclip.quality import pre_render
from ermclip.store import Store
from ermclip.util import atomic_json, atomic_text, fingerprint, run
from ermclip.worker import submit, worker
from make_sample import TEXT


def main():
    settings=load()
    settings.stable_seconds=0
    settings.whisper_device="cuda"
    assert settings.additional_paid_api_budget==0 and not settings.telegram_enabled
    root=settings.path
    # Reproducible source different from the older demo, forcing fresh ASR once.
    source=root/"input"/"ermclip_local_model_test.mp4"
    if not source.exists():
        build=root/"cache"/"local-model-test-source"
        build.mkdir(exist_ok=True)
        atomic_text(build/"narration.txt",TEXT+" This test runs the Director and Critic on the local computer. No paid inference service is used.")
        run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","flite=textfile=narration.txt:voice=slt","-ar","48000","narration.wav"],cwd=build,timeout=120)
        run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=640x360:rate=30","-i",str(build/"narration.wav"),"-c:v","libx264","-preset","fast","-threads","4","-c:a","aac","-b:a","160k","-shortest","-movflags","+faststart",str(source)],timeout=300)
    identity=fingerprint(source)
    ensure(settings)
    print("Local CUDA server ready; generating real edit jobs",flush=True)
    samples=[]
    done=threading.Event()
    def monitor():
        while not done.is_set():
            card=gpu()
            if card: samples.append({"time":time.time(),**card})
            done.wait(1)
    thread=threading.Thread(target=monitor,daemon=True)
    thread.start()
    store=Store(root/"state"/"jobs.sqlite3")
    assert not any(j["status"] in ("queued","running","retry") for j in store.list()), "Finish or cancel pending work before this validation"
    store.control("pause","0")
    records=json.loads((root/"state"/"local-test-progress.json").read_text(encoding="utf-8"))["jobs"] if "--resume" in sys.argv else []
    stamp=str(time.time_ns())
    portrait=Profile(name="local_portrait",ratio="9:16",width=360,height=640,duration=Duration(target=30,minimum=20,maximum=45),count=1,framing="pad")
    portrait.captions.size=30
    landscape=portrait.model_copy(deep=True,update={"name":"local_landscape","ratio":"16:9","width":640,"height":360})
    def execute(label,spec):
        saved=next((r for r in records if r["label"]==label),None)
        if saved:
            row=store.get(saved["job"])
            for key in ("source","instruction","mode","conditions","profiles","transcript","approved_plan"):
                assert row["spec"][key]==spec.model_dump()[key], f"Cannot resume changed {key}"
            manifest=json.loads(Path(saved["manifest"]).read_text(encoding="utf-8"))
            assert manifest["fingerprint"]==identity and manifest["director_model"]==settings.director_model
            print(f"{label}: reused validated job {saved['job']}",flush=True)
            return manifest,saved["reports"]
        spec.revision_of="local-validation-"+stamp+"-"+label
        path=root/"state"/("local-test-"+label+".json")
        atomic_json(path,spec.model_dump())
        job,created=submit(spec,settings,store)
        assert created
        print(f"{label}: queued {job}",flush=True)
        worker(settings,once=True)
        row=store.get(job)
        assert row["status"] in ("completed","review_required","no_matches"), row
        manifest=json.loads((Path(row["output"])/"manifest.json").read_text(encoding="utf-8"))
        assert manifest["additional_paid_api_cost"]==0 and manifest["model_calls"]<=settings.max_model_calls
        reports=[]
        for output in manifest["outputs"]:
            media=Path(output["path"])
            quality=json.loads(media.with_name(media.stem+"_quality.json").read_text(encoding="utf-8"))
            assert quality["critic"]=="local-isolated-text", quality
            assert not any(f["code"]=="critic_unavailable" for f in quality["findings"])
            assert media.with_suffix(".srt").is_file() and media.with_suffix(".md").is_file()
            assert media.with_name(media.stem+"_thumbnail.jpg").is_file()
            assert probe(media)["audio"]
            reports.append({"path":str(media),"status":quality["status"],"history":quality["history"],"scores":quality["scores"],"encoder":quality["render_encoder"]})
        records.append({"label":label,"job":job,"manifest":str(Path(row["output"])/"manifest.json"),"status":manifest["status"],"model_calls":manifest["model_calls"],"usage":manifest["model_usage_this_attempt"],"analysis_reused":manifest["analysis_reused"],"reports":reports})
        print(f"{label}: {manifest['status']}; calls={manifest['model_calls']}; outputs={len(reports)}",flush=True)
        return manifest,reports
    try:
        auto=JobSpec(source=str(source),instruction="Select one complete explanation with a clear opening and ending for each profile. Prefer the section that explains why context matters. Keep all speech intact.",profiles=[portrait,landscape])
        manifest,reports=execute("auto",auto)
        assert len(reports)==2
        assert any(u["role"]=="director" for u in manifest["model_usage_this_attempt"])
        cache=Path(manifest["analysis_cache"])
        transcript=Transcript.model_validate_json((cache/"transcript.json").read_text(encoding="utf-8"))
        assert transcript.engine.endswith("/cuda"), transcript.engine
        atomic_json(root/"docs"/"local-model-asr.json",{"engine":transcript.engine,"passages":len(transcript.passages),"words":sum(len(p.words) for p in transcript.passages),"warnings":transcript.warnings,"cache":str(cache)})
        targeted=JobSpec(source=str(source),instruction="Find one complete explanation mentioning context. Exclude cryptocurrency.",mode="TARGETED",conditions=Conditions(keywords=["context"],exclude=["cryptocurrency"]),profiles=[portrait])
        execute("targeted",targeted)
        # Supply a valid operator plan with deliberately incomplete speech boundaries.
        first=next(i for i,p in enumerate(transcript.passages) if "why does context" in p.text.lower())
        start=transcript.passages[first].start+0.7
        end=transcript.passages[first+5].end-0.7
        profile=portrait.model_copy(deep=True,update={"name":"local_revision","duration":Duration(target=30,minimum=10,maximum=60)})
        spec=JobSpec(source=str(source),instruction="Keep the full explanation of why context matters. Repair cuts that remove part of a spoken statement.",profiles=[profile])
        candidate=Candidate(id="clip_001",profile=profile.name,title="Why context matters",segments=[Segment(start=start,end=end,reason="Intentional incomplete boundaries for revision validation")],reason="Test source boundaries")
        info=probe(source)
        matcher=Matcher(spec,transcript,settings,cache)
        before=pre_render(spec,candidate,profile,transcript,info,matcher)
        assert any(f.code=="incomplete_statement" for f in before)
        plan=EditingPlan(instruction=spec.instruction,source=str(source),fingerprint=identity,source_duration=info["duration"],mode=spec.mode,profiles=spec.profiles,candidates=[candidate],director="operator-revision-test")
        plan_path=root/"state"/"local-revision-input-plan.json"
        atomic_json(plan_path,plan.model_dump())
        spec.approved_plan=str(plan_path)
        _,revision_reports=execute("revision",spec)
        history=revision_reports[0]["history"]
        assert len(history)>=2 and history[1]["revision"]==1
        assert any(f["code"]=="incomplete_statement" for f in history[0]["findings"])
        assert not any(f["code"]=="incomplete_statement" for f in history[-1]["findings"]), history
        no_match=JobSpec(source=str(source),instruction="Select only spoken cryptocurrency discussion; return no clips when absent.",mode="TARGETED",conditions=Conditions(keywords=["cryptocurrency"]),profiles=[portrait])
        empty,_=execute("no-match",no_match)
        assert empty["status"]=="no_matches" and not empty["outputs"]
        assert fingerprint(source)==identity
        install=json.loads((root/"cache"/"local-llm"/"install.json").read_text(encoding="utf-8"))
        record={"passed":True,"time":time.time(),"source":str(source),"source_sha256":identity,"source_unchanged":True,"runtime_build":install["build"],"model":install["model"],"context_tokens":16384,"endpoint":settings.local_llm_url,"paid_api_cost":0,"asr_engine":transcript.engine,"jobs":records,"gpu_samples":samples,"limitations":["Test footage is a generated pattern with original TTS, not a real talking-head recording.","Critic is a text model. It reviews transcript and measured AV evidence; it cannot see image pixels or hear audio.","Scores are uncalibrated. Human review is still required before publication.","Large transcripts above the director input budget use deterministic planning with an explicit warning."]}
        atomic_json(root/"docs"/"local-model-validation.json",record)
        print("LIVE VALIDATION PASSED. Source unchanged; paid cost 0.",flush=True)
    finally:
        done.set()
        thread.join(timeout=5)
        atomic_json(root/"state"/"local-test-progress.json",{"jobs":records,"gpu_samples":samples})


if __name__=="__main__":
    main()
