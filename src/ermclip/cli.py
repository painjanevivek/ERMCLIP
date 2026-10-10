from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import time

from .config import ROOT, load
from .models import JobSpec, Profile
from .notifications import authorised_sender, send
from .request import interpret
from .store import Store
from .util import atomic_json
from .worker import submit, worker


def parser():
    p=argparse.ArgumentParser(prog="ermclip",description="Persistent local video editor. Primary modes: AUTO and TARGETED.")
    p.add_argument("--config",help="Path to settings JSON")
    p.add_argument("--sender",help="Telegram sender ID; required for commands invoked by the Hermes Telegram skill")
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("init")
    sub.add_parser("caption-styles", help="List the local caption preset IDs and looks")
    gallery=sub.add_parser('caption-gallery', help='Render the local caption style picker')
    gallery.add_argument('--output', help='Local output directory')
    doctor=sub.add_parser("doctor")
    doctor.add_argument("--save",action="store_true")
    s=sub.add_parser("submit")
    s.add_argument("paths",nargs="*")
    s.add_argument("--instruction",default="Create the best clips from this video.")
    s.add_argument("--spec")
    s.add_argument("--transcript")
    s.add_argument("--profile",help="Profile JSON file, object or list")
    s.add_argument("--plan")
    s.add_argument("--podcast", action="store_true", help="Center the visible active speaker using local audio and face analysis")
    from .caption_styles import PRESET_IDS
    s.add_argument("--caption-style", choices=PRESET_IDS, help="Apply one preset to all output profiles")
    s.add_argument("--force",action="store_true",help="Explicitly create a new regeneration job")
    analysis=sub.add_parser("analyze")
    analysis.add_argument("source")
    analysis.add_argument("--transcript")
    planning=sub.add_parser("plan")
    planning.add_argument("--spec",required=True)
    planning.add_argument("--output",required=True)
    validation=sub.add_parser("validate-plan")
    validation.add_argument("--spec",required=True)
    validation.add_argument("--plan",required=True)
    w=sub.add_parser("worker")
    w.add_argument("--once",action="store_true")
    sub.add_parser("status").add_argument("job",nargs="?")
    for name in ("pause","resume","stop","health"):
        sub.add_parser(name)
    sub.add_parser("cancel").add_argument("job")
    events=sub.add_parser("events")
    events.add_argument("job",nargs="?")
    feedback=sub.add_parser("feedback")
    feedback.add_argument("job")
    feedback.add_argument("clip")
    feedback.add_argument("rating",type=int)
    feedback.add_argument("notes")
    sub.add_parser("delete-feedback")
    tags=sub.add_parser("tags")
    tags.add_argument("job")
    tags.add_argument("clip")
    tags.add_argument("--profile")
    regen=sub.add_parser("regenerate")
    regen.add_argument("job")
    regen.add_argument("--instruction",required=True)
    sub.add_parser("schemas")
    default=sub.add_parser("defaults")
    default.add_argument("--profiles",required=True)
    sub.add_parser("notify-test")
    sub.add_parser("telegram-status", help="Check local Telegram readiness without exposing the token")
    telegram=sub.add_parser("connect-telegram", help="Verify the existing Hermes bot and enable owner-only notifications")
    telegram.add_argument('--user-id', required=True)
    telegram.add_argument('--bot-username', required=True)
    clean=sub.add_parser("clean-cache")
    clean.add_argument("--apply",action="store_true")
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        settings=load(args.config)
        if args.sender and not authorised_sender(args.sender,settings):
            raise ValueError("Telegram sender is not authorised")
        store=Store(settings.path/"state"/"jobs.sqlite3")
        result=None
        if args.command=='telegram-status':
            from .telegram_setup import status
            result=status(settings)
        elif args.command=='connect-telegram':
            from .telegram_setup import connect
            result=connect(settings, store, Path(args.config) if args.config else ROOT/'config/local.json', args.user_id, args.bot_username)
        elif args.command=='caption-gallery':
            from .caption_gallery import build
            result=build(Path(args.output) if args.output else settings.path/'output'/'caption-gallery')
        elif args.command=='caption-styles':
            from .caption_styles import catalog
            result={'styles':catalog(), 'legacy_presets':['highlight','plain','pop']}
        elif args.command=="init":
            target=Path(args.config) if args.config else ROOT/"config"/"local.json"
            if not target.exists():
                atomic_json(target,settings.model_dump())
            result={"config":str(target),"root":str(settings.path)}
        elif args.command=="doctor":
            import importlib.metadata
            import psutil
            from .media import gpu
            from .speaker import ready as speaker_ready
            packages={}
            for name in ("pydantic","psutil","faster-whisper","opencv-python-headless","scenedetect","sentence-transformers","torch","python-speech-features","scipy"):
                try: packages[name]=importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError: packages[name]=None
            from .notifications import hermes_telegram
            token,chat,users=hermes_telegram(settings.hermes_home)
            result={"python":__import__("sys").version,"ffmpeg":shutil.which("ffmpeg"),"ffprobe":shutil.which("ffprobe"),"gpu":gpu(),"ram_gb":round(psutil.virtual_memory().total/1024**3,2),"cpu_threads":psutil.cpu_count(),"free_disk_gb":round(shutil.disk_usage(settings.path).free/1024**3,2),"packages":packages,"model_downloads_allowed":settings.allow_model_download,"local_llm_configured":bool(settings.local_llm_url),"telegram":{"enabled":settings.telegram_enabled,"token_present":bool(token),"destination_present":bool(settings.telegram_chat_id or chat),"authorised_users":len(settings.telegram_allowed_users or users)}}
            result["speaker_tracking"]={"ready":bool(speaker_ready(settings.path)),"device":"cpu","model":"Light-ASD TalkSet + YuNet","paid_api_cost":0}
            if args.save:
                atomic_json(settings.path/"docs"/"environment.json",result)
        elif args.command=="submit":
            specs=[]
            if args.spec:
                specs=[JobSpec.model_validate_json(Path(args.spec).read_text(encoding="utf-8-sig"))]
            else:
                profiles=settings.defaults
                if args.profile:
                    data=json.loads(Path(args.profile).read_text(encoding="utf-8-sig"))
                    profiles=[Profile.model_validate(d) for d in (data if isinstance(data,list) else [data])]
                for entry in args.paths:
                    path=Path(entry)
                    paths=sorted(p for p in path.iterdir() if p.suffix.lower() in (".mp4",".mkv",".mov",".webm",".avi",".m4v")) if path.is_dir() else [path]
                    for path in paths:
                        spec=interpret(str(path),args.instruction,profiles)
                        spec.transcript=args.transcript
                        spec.approved_plan=args.plan
                        if args.force: spec.revision_of=f"manual-{time.time_ns()}"
                        specs.append(spec)
            if not specs:
                raise ValueError("Provide video paths, a folder, or --spec")
            if args.podcast:
                specs = [JobSpec.model_validate(s.model_copy(update={"podcast_mode":"on"}).model_dump()) for s in specs]
            if args.caption_style:
                from .request import source_context
                specs = [source_context(s, settings) for s in specs]
                for spec in specs:
                    for profile in spec.profiles:
                        profile.captions.preset=args.caption_style
            result=[]
            for spec in specs:
                job,created=submit(spec,settings,store)
                result.append({"job":job,"created":created})
        elif args.command=="worker":
            worker(settings,args.once)
        elif args.command in ("analyze","plan","validate-plan"):
            from .pipeline import analyse
            from .util import fingerprint,validate_input
            from .provider import LocalModel
            from .director import plan
            spec=JobSpec(source=args.source,transcript=args.transcript) if args.command=="analyze" else JobSpec.model_validate_json(Path(args.spec).read_text(encoding="utf-8-sig"))
            spec.source=str(validate_input(spec.source,settings.allowed_inputs))
            from .request import source_context
            spec=source_context(spec,settings)
            identity=fingerprint(Path(spec.source))
            # Use the same lock as the background worker for all GPU-heavy operations.
            from .worker import worker_lock
            with worker_lock(settings.path/"state"/"worker.lock"):
                info,transcript,visuals,cache,reused=analyse(spec,settings,identity)
                if args.command=="analyze":
                    result={"source":spec.source,"fingerprint":identity,"duration":info["duration"],"cache":str(cache),"transcript":str(cache/"transcript.json"),"reused":reused}
                else:
                    if args.command=="validate-plan": spec.approved_plan=args.plan
                    editing=plan(spec,transcript,info,identity,settings,cache,LocalModel(settings),store.preferences())
                    if args.command=="plan": atomic_json(Path(args.output),editing.model_dump())
                    result={"valid":True,"candidates":len(editing.candidates),"plan":args.output if args.command=="plan" else args.plan,"warnings":editing.warnings}
        elif args.command=="status":
            result=store.get(args.job) if args.job else store.list()
        elif args.command=="events":
            with store.connect() as db:
                result=[dict(r) for r in db.execute("SELECT * FROM events WHERE (? IS NULL OR job_id=?) ORDER BY id DESC LIMIT 100",(args.job,args.job))]
        elif args.command in ("pause","resume","stop"):
            store.control("stop" if args.command=="stop" else "pause", "0" if args.command=="resume" else "1")
            result={"queue":args.command,"note":"Pause takes effect before the next job; stop interrupts the current media process and preserves checkpoints."}
        elif args.command=="cancel":
            store.cancel(args.job)
            result={"cancelled":args.job}
        elif args.command=="health":
            path=settings.path/"state"/"health.json"
            result=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status":"not_started"}
            if result.get("status")=="running":
                result["stale"]=time.time()-result["time"]>15
        elif args.command=="feedback":
            store.feedback(args.job,args.clip,args.rating,args.notes)
            result={"saved":True}
        elif args.command=="delete-feedback":
            store.delete_feedback()
            result={"deleted":True}
        elif args.command=="tags":
            job=store.get(args.job)
            if not job["output"]: raise ValueError("Job has no output package yet")
            manifest=json.loads((Path(job["output"])/"manifest.json").read_text(encoding="utf-8"))
            matches=[r for r in manifest["outputs"] if r["id"]==args.clip and (not args.profile or r["profile"]==args.profile)]
            if len(matches)!=1: raise ValueError("Clip is missing or ambiguous; specify --profile")
            result={"tags":", ".join(matches[0].get("tags",[]))}
        elif args.command=="regenerate":
            old=store.get(args.job)
            spec=interpret(old["spec"]["source"],args.instruction,[Profile.model_validate(p) for p in old["spec"]["profiles"]])
            spec.transcript=old["spec"].get("transcript")
            spec.revision_of=args.job+f"-{time.time_ns()}"
            job,created=submit(spec,settings,store)
            result={"job":job,"created":created,"revision_of":args.job}
        elif args.command=="schemas":
            from .models import EditingPlan
            for name,schema in (("job",JobSpec),("editing_plan",EditingPlan),("settings",type(settings))):
                atomic_json(settings.path/"config"/(name+".schema.json"),schema.model_json_schema())
            result={"schemas":str(settings.path/"config")}
        elif args.command=="defaults":
            data=json.loads(Path(args.profiles).read_text(encoding="utf-8-sig"))
            settings.defaults=[Profile.model_validate(p) for p in (data if isinstance(data,list) else [data])]
            atomic_json(Path(args.config) if args.config else ROOT/"config"/"local.json",settings.model_dump())
            result={"saved_defaults":[p.name for p in settings.defaults]}
        elif args.command=="notify-test":
            send(settings,"ERMCLIP connection test. The local worker is ready.")
            result={"sent":True}
        elif args.command=="clean-cache":
            # Only unused analysis caches; never models, source files, or active checkpoints.
            referenced=set()
            with store.connect() as db:
                for row in db.execute("SELECT checkpoint FROM jobs"):
                    target=json.loads(row[0]).get("analysis_cache")
                    if target: referenced.add(Path(target).resolve())
            parent=(settings.path/"cache"/"analysis").resolve()
            paths=[p for p in parent.glob("*") if p.is_dir() and not p.is_symlink() and p.resolve().is_relative_to(parent) and p.resolve() not in referenced and time.time()-p.stat().st_mtime>settings.cache_days*86400]
            if args.apply:
                for path in paths: shutil.rmtree(path)
            result={"unused_analysis_caches":[str(p) for p in paths],"removed":args.apply}
        if result is not None:
            print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
        return 0
    except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
        print(json.dumps({"error":str(exc)},ensure_ascii=False))
        raise SystemExit(1)
