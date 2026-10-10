from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from .models import Candidate, Profile
from .util import run


def probe(path: Path) -> dict:
    info = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], timeout=60).stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("No video stream found")
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    duration = float(info["format"].get("duration", video.get("duration", 0)))
    if duration <= 0 or not __import__("math").isfinite(duration):
        raise ValueError("Source has no valid duration")
    rotation = next((x.get("rotation", 0) for x in video.get("side_data_list", []) if "rotation" in x), 0)
    width, height = int(video["width"]), int(video["height"])
    if abs(int(rotation)) % 180 == 90:
        width, height = height, width
    return {"duration":duration, "width":width, "height":height, "audio":bool(audio), "video":video, "audio_stream":audio, "bytes":path.stat().st_size}


def gpu():
    try:
        raw = run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"], timeout=15).stdout.strip().splitlines()[0]
        name, total, free, driver = [v.strip() for v in raw.split(",")]
        return {"name":name, "total_mb":int(total), "free_mb":int(free), "driver":driver}
    except (OSError, RuntimeError, TimeoutError, ValueError, IndexError):
        return None


def ensure_space(folder: Path, minimum_gb: float, estimate: int = 0):
    if shutil.disk_usage(folder).free < max(minimum_gb * 1024**3, estimate):
        raise RuntimeError("Insufficient free disk space for this job")


def scan_visuals(path: Path, info: dict, cache: Path, timeout: int, check_cancel=None, scenes=True):
    import cv2
    capture = cv2.VideoCapture(str(path))
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    samples = []
    try:
        count = min(120, max(3, int(info["duration"] / 15)))
        for i in range(count):
            if check_cancel and check_cancel():
                from .util import Cancelled
                raise Cancelled()
            t = min(info["duration"] - 0.05, (i+0.5)*info["duration"]/count)
            capture.set(cv2.CAP_PROP_POS_MSEC, t*1000)
            ok, frame = capture.read()
            if not ok:
                continue
            small = cv2.resize(frame, (640, max(1, round(frame.shape[0]*640/frame.shape[1]))))
            grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(24,24))
            samples.append({"time":t, "faces":[{"x":float((x+w/2)/small.shape[1]), "y":float((y+h/2)/small.shape[0]), "area":float(w*h/(small.shape[0]*small.shape[1]))} for x,y,w,h in faces], "luma":float(grey.mean()), "sharpness":float(cv2.Laplacian(grey, cv2.CV_64F).var())})
    finally:
        capture.release()
    boundaries = []
    warnings = []
    if scenes:
        # FFmpeg scene detection is bounded by the same media timeout and cancellation.
        result = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "scale=320:-2,select=gt(scene\\,0.35),showinfo", "-an", "-f", "null", "-"], timeout=timeout, check_cancel=check_cancel)
        boundaries = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", result.stderr)]
    return {"engine":"opencv-haar + ffmpeg-scene", "samples":samples, "scene_boundaries":boundaries, "warnings":warnings, "limitations":["Sparse face samples do not identify speakers or recognise actions.", "Framing is fixed per segment; continuous face tracking is not implemented."]}


def framing_filter(profile: Profile, source: dict, segment, visuals: dict, override=None):
    w,h = profile.width,profile.height
    framing = override or profile.framing
    if framing == "speaker":
        raise ValueError("Speaker framing requires audiovisual tracking; use render()")
    if framing == "original":
        if abs(source["width"]/source["height"] - w/h) > 0.015:
            raise ValueError("Original framing requires a profile matching the source ratio")
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if framing == "pad":
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if framing == "blur":
        return f"split=2[bg][fg];[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[b];[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[f];[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1"
    center = 0.5
    if framing == "smart":
        faces = [face for sample in visuals.get("samples", []) if segment.start <= sample["time"] <= segment.end for face in sample["faces"]]
        if faces:
            import statistics
            center = statistics.median(f["x"] for f in faces)
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:max(0\\,min(iw-ow\\,iw*{center:.5f}-ow/2)):(ih-oh)/2,setsar=1"


def render(source: Path, info: dict, candidate: Candidate, profile: Profile, ass: Path, output: Path, settings, visuals, check_cancel=None):
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (candidate.id + "_work")
    work.mkdir(exist_ok=True)
    encoders = ["h264_nvenc", "libx264"] if settings.encoder == "auto" and gpu() else ["h264_nvenc" if settings.encoder == "nvenc" else "libx264"]
    selected_encoder = None
    tracking = []
    try:
        if (candidate.framing or profile.framing) == "speaker":
            from .speaker import analyse
            from .util import fingerprint
            identity = fingerprint(source)
            for segment in candidate.segments:
                tracking.append(analyse(source, segment, info, settings, identity, check_cancel))
        for encoder in encoders:
            pieces = []
            try:
                for index, segment in enumerate(candidate.segments):
                    piece = work / f"part_{index:03}.mp4"
                    from .layouts import body_profile, frame_graph
                    body = body_profile(profile)
                    if tracking:
                        from .speaker import filter_graph
                        graph = filter_graph(body, info, tracking[index], work/f"speaker_{index:03}.cmd")
                    else:
                        vf = framing_filter(body, info, segment, visuals, candidate.framing)
                        graph = f"[0:v]{vf}[v]"
                    graph = frame_graph(graph,profile)
                    args = ["ffmpeg", "-hide_banner", "-y", "-ss", f"{segment.start:.6f}", "-i", str(source)]
                    if not info["audio"]:
                        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                    args += ["-t", f"{segment.end-segment.start:.6f}", "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0" if info["audio"] else "1:a:0", "-r", "30", "-c:v", encoder]
                    args += ["-preset", "p4", "-cq", "22"] if encoder == "h264_nvenc" else ["-preset", "fast", "-crf", "22", "-threads", "4"]
                    args += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k", "-movflags", "+faststart", str(piece)]
                    run(args, cwd=work, timeout=settings.process_timeout, check_cancel=check_cancel)
                    pieces.append(piece)
                selected_encoder = encoder
                break
            except RuntimeError:
                if encoder == encoders[-1]:
                    raise
        # Controlled basenames avoid FFmpeg filter and concat quoting issues on Windows.
        listing = work / "concat.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in pieces), encoding="utf-8")
        if ass.exists():
            shutil.copyfile(ass, work / "captions.ass")
        vf = "ass=captions.ass" if ass.exists() and (profile.captions.burn or profile.layout.preset != "plain") else "null"
        af = "loudnorm=I=-16:TP=-1.5:LRA=11" if profile.normalize_audio else "anull"
        if profile.fades:
            af += f",afade=t=in:d=0.04,afade=t=out:st={max(0,candidate.duration-0.06):.3f}:d=0.06"
        temporary = output.with_name(output.stem + ".partial.mp4")
        args = ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "1", "-i", "concat.txt", "-vf", vf, "-af", af, "-t", f"{candidate.duration:.6f}", "-c:v", selected_encoder]
        args += ["-preset", "p4", "-cq", "22"] if selected_encoder == "h264_nvenc" else ["-preset", "fast", "-crf", "22", "-threads", "4"]
        args += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "160k", "-movflags", "+faststart", str(temporary)]
        run(args, cwd=work, timeout=settings.process_timeout, check_cancel=check_cancel)
        rendered = probe(temporary)
        if rendered["duration"] > 900.05 or abs(rendered["duration"]-candidate.duration) > 0.12 or (rendered["width"], rendered["height"]) != (profile.width, profile.height):
            raise RuntimeError("Rendered output does not match the validated timeline")
        # A 900-second output is capped to 27000 video frames by -t, AAC container padding can be larger.
        if float(rendered["video"].get("duration", rendered["duration"])) > 900.001:
            raise RuntimeError("Rendered video stream exceeds 900 seconds")
        os.replace(temporary, output)
        result = {"encoder":selected_encoder, "probe":rendered}
        if tracking:
            audit = {"source_fingerprint":identity,"segments":tracking,"review_required":True,
                     "output_offsets":[],"additional_paid_api_cost":0}
            offset = 0
            for segment in candidate.segments:
                audit["output_offsets"].append(round(offset,6))
                offset += segment.end-segment.start
            from .util import atomic_json
            atomic_json(output.with_name(output.stem+"_speaker_tracking.json"),audit)
            result["speaker_tracking"] = audit
        else:
            output.with_name(output.stem+"_speaker_tracking.json").unlink(missing_ok=True)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
        output.with_name(output.stem + ".partial.mp4").unlink(missing_ok=True)


def thumbnail(video: Path, output: Path, t: float, timeout=60):
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-update", "1", str(output)], timeout=timeout)
