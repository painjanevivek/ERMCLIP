from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import os

from .models import Passage, Transcript, Word
from .util import atomic_json, run


def import_transcript(path: Path, duration: float) -> Transcript:
    if path.suffix.lower() == ".json":
        transcript = Transcript.model_validate_json(path.read_text(encoding="utf-8-sig"))
    elif path.suffix.lower() == ".srt":
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        passages = []
        def timestamp(value):
            h,m,s = value.replace(",", ".").split(":")
            return float(h)*3600+float(m)*60+float(s)
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = block.splitlines()
            time_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if time_index is None:
                raise ValueError("Invalid SRT block")
            start,end = lines[time_index].split("-->")
            passages.append(Passage(start=timestamp(start.strip()), end=timestamp(end.strip().split()[0]), text=" ".join(lines[time_index+1:])))
        transcript = Transcript(engine="imported-srt", passages=passages, warnings=["SRT has no verified word alignment; captions use passage timing."])
    else:
        raise ValueError("Transcript must be JSON or SRT")
    if any(p.end > duration + 0.1 for p in transcript.passages):
        raise ValueError("Transcript timestamps exceed source duration")
    if any(a.start > b.start for a,b in zip(transcript.passages, transcript.passages[1:])):
        raise ValueError("Transcript passages must be in source order")
    return transcript


def transcribe(source: Path, cache: Path, settings, check_cancel=None, language=None) -> Transcript:
    audio = cache / "speech.wav"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(audio)], timeout=settings.process_timeout, check_cancel=check_cancel)
    from .media import gpu
    card = gpu()
    device = settings.whisper_device
    # Larger local language models share this 8 GB GPU with transcription.
    # Release only our managed server; the Director restarts it after ASR.
    if settings.managed_local_model and device in ('auto','cuda') and card and card['free_mb']<settings.min_gpu_free_mb:
        from .local_runtime import stop
        stop(settings)
        card=gpu()
    devices = ["cuda", "cpu"] if device == "auto" and card and card["free_mb"] >= settings.min_gpu_free_mb else ["cpu" if device == "auto" else device]
    result = cache / "transcription_result.json"
    errors = []
    try:
        for device in devices:
            task = {"audio":str(audio), "model":settings.whisper_model, "device":device, "download":settings.allow_model_download, "models":str(settings.path / "cache" / "models"), "output":str(result), "language":language}
            task_path = cache / "transcription_task.json"
            atomic_json(task_path, task)
            try:
                run([sys.executable, "-m", "ermclip.transcribe", str(task_path)], timeout=settings.process_timeout, check_cancel=check_cancel)
                transcript = Transcript.model_validate_json(result.read_text(encoding="utf-8"))
                transcript.warnings.extend(errors)
                return transcript
            except RuntimeError as exc:
                errors.append(f"{device} transcription unavailable: {str(exc)[-1200:]}")
        raise RuntimeError("Transcription failed. " + " ".join(errors))
    finally:
        audio.unlink(missing_ok=True)


def aligned_words(raw):
    """Retain zero-length tokens in an adjoining verified span, without fake timing."""
    words=[]; prefix=''; prefix_start=None; merged=False
    for w in raw:
        if w.end<=w.start:
            prefix+=w.word; prefix_start=w.start if prefix_start is None else min(prefix_start,w.start)
            merged=True; continue
        words.append(Word(start=min(w.start,prefix_start) if prefix_start is not None else w.start,
                          end=w.end,text=prefix+w.word))
        prefix=''; prefix_start=None
    if prefix and words:
        words[-1].text+=prefix
        if prefix_start is not None and prefix_start>words[-1].end: words[-1].end=prefix_start
    return words,merged


def child(task):
    # Load project-local NVIDIA DLLs without modifying global PATH or CUDA installs.
    dll_handles=[]
    if os.name=="nt" and task["device"]=="cuda":
        import site
        directories=[]
        for root in site.getsitepackages():
            for component in ("cublas","cudnn","cuda_nvrtc"):
                directory=Path(root)/"nvidia"/component/"bin"
                if directory.is_dir():
                    directories.append(str(directory))
                    dll_handles.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"]=os.pathsep.join(directories+[os.environ.get("PATH","")])
    from faster_whisper import WhisperModel
    model = WhisperModel(task["model"], device=task["device"], compute_type="int8_float16" if task["device"] == "cuda" else "int8", download_root=task["models"], local_files_only=not task["download"], cpu_threads=4)
    segments,info = model.transcribe(task["audio"], language=task.get("language"), word_timestamps=True, vad_filter=True,
        beam_size=task.get('beam_size',5), initial_prompt=task.get('initial_prompt'))
    passages = []; merged_tokens=False
    for s in segments:
        words,merged=aligned_words(s.words or []); merged_tokens=merged_tokens or merged
        if s.end > s.start:
            passages.append(Passage(start=s.start, end=s.end, text=s.text.strip(), words=words))
        if len(passages) % 25 == 0:
            atomic_json(Path(task["output"]).with_name("transcription_progress.json"),
                        {"through_seconds": s.end, "duration": info.duration, "passages": len(passages)})
    transcript = Transcript(language=info.language, engine=f"faster-whisper/{task['model']}/{task['device']}", passages=passages)
    if merged_tokens: transcript.warnings.append('Zero-length ASR tokens share an adjoining word span. Their independent timing is not verified; inspect captions.')
    atomic_json(Path(task["output"]), transcript.model_dump())
    atomic_json(Path(task["output"]).with_name("transcription_progress.json"),
                {"through_seconds":info.duration,"duration":info.duration,"passages":len(passages),"completed":True})


if __name__ == "__main__":
    child(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
