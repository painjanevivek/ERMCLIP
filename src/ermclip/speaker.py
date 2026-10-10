"""Offline audiovisual active-speaker tracking and bounded FFmpeg crop commands.

Light-ASD is a speech activity model, not identity recognition or diarization.
No face, audio, or transcript leaves the machine. No downloads occur here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time

from .util import Cancelled, atomic_json, atomic_text, fingerprint, run

ASD_SHA = "efc375833887eefa9d209dc92810e18519b04c3c73ea35a549f2a7f40b7d94d5"
FACE_SHA = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
VERSION = "light-asd-talkset-yunet-v5"
FPS = 25
_NETWORK = None


def assets(root: Path):
    folder = root / "cache" / "speaker-models"
    return folder / "light-asd-source/weight/finetuning_TalkSet.model", folder / "face_detection_yunet_2023mar.onnx"


def ready(root: Path):
    import importlib.util
    weights, face = assets(root)
    return (all(importlib.util.find_spec(p) for p in ("torch", "python_speech_features", "scipy"))
            and weights.is_file() and face.is_file()
            and fingerprint(weights) == ASD_SHA and fingerprint(face) == FACE_SHA)


def network(root: Path):
    global _NETWORK
    weights, face = assets(root)
    if fingerprint(weights) != ASD_SHA or fingerprint(face) != FACE_SHA:
        raise RuntimeError("Speaker model checksum mismatch; reinstall the pinned assets")
    if _NETWORK is None:
        import torch
        from ._light_asd.Model import ASD_Model
        torch.set_num_threads(4)
        model = ASD_Model().eval()
        classifier = torch.nn.Linear(128, 2).eval()
        state = torch.load(weights, map_location="cpu", weights_only=True)
        model.load_state_dict({k[6:]: v for k, v in state.items() if k.startswith("model.")}, strict=True)
        classifier.load_state_dict({k[10:]: v for k, v in state.items() if k.startswith("lossAV.FC.")}, strict=True)
        _NETWORK = model, classifier
    return _NETWORK


def _iou(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    area = max(0, min(ax+aw, bx+bw)-max(ax, bx)) * max(0, min(ay+ah, by+bh)-max(ay, by))
    return area / max(1e-8, aw*ah+bw*bh-area)


class FaceTracks:
    """One-to-one box association. Shot changes discard all prior identities."""
    def __init__(self):
        self.next_id = 0
        self.boxes = {}

    def reset(self):
        self.boxes = {}

    def update(self, detections):
        matches = sorted(((_iou(box, old), tid, i) for tid, old in self.boxes.items()
                          for i, box in enumerate(detections)), reverse=True)
        assigned, used = {}, set()
        for overlap, tid, i in matches:
            if overlap >= .3 and tid not in used and i not in assigned:
                # A close tie means association is uncertain. Reacquire a new track.
                alternatives = [_iou(detections[i], b) for t, b in self.boxes.items() if t != tid]
                if alternatives and overlap - max(alternatives) < .1:
                    continue
                assigned[i] = tid
                used.add(tid)
        for i in range(len(detections)):
            if i not in assigned:
                assigned[i] = self.next_id
                self.next_id += 1
        self.boxes = {assigned[i]: box for i, box in enumerate(detections)}
        return self.boxes


@dataclass
class SpeakerChoice:
    current: int | None = None
    pending: int | None = None
    pending_since: float = 0
    center: float = .5
    last_time: float = 0
    confirmed: bool = False

    def choose(self, t, faces, speech=True, scene_cut=False):
        """Scores are uncalibrated model softmax values. Never choose by face size."""
        if scene_cut:
            self.current = self.pending = None
            self.confirmed = False
        ordered = sorted(faces, key=lambda f: f["score"], reverse=True)
        best = ordered[0] if ordered else None
        # Similar scores and overlapping speech keep both people in view.
        retained = best is not None and best["id"] == self.current and self.confirmed
        threshold, margin = (.6,.1) if retained else (.75,.2)
        certain = (speech and best is not None and best["score"] >= threshold and
                   (len(ordered) == 1 or best["score"] - ordered[1]["score"] >= margin))
        wanted = best["id"] if certain else None
        if wanted is None:
            self.current = self.pending = None
            self.confirmed = False
            self.last_time = t
            reason = "low_audio_energy" if not speech else "no_scored_face" if best is None else "low_activity" if best["score"] < .75 else "ambiguous_faces"
            return {"time": round(t, 3), "speaker": None, "center": .5, "fallback": True,"reason":reason}
        if wanted != self.current:
            if self.pending != wanted:
                self.pending, self.pending_since = wanted, t
            if t-self.pending_since < .4-1e-6:
                self.last_time = t
                return {"time": round(t, 3), "speaker": None, "center": .5, "fallback": True,"reason":"speaker_settling"}
            self.current = wanted
            self.confirmed = True
            self.center = best["x"]  # A turn change cuts to the new speaker; no pan across listeners.
        else:
            self.pending = None
            dt = max(0, t-self.last_time)
            movement = (best["x"]-self.center) * (1-math.exp(-dt/.25))
            self.center += max(-.25*dt, min(.25*dt, movement))
        self.last_time = t
        return {"time": round(t, 3), "speaker": wanted, "center": round(self.center, 6),
                "score": round(best["score"], 4), "fallback": False}


def _face_crop(frame, box):
    import cv2
    import numpy as np
    x, y, w, h = box
    bs = max(w, h)/2
    cx, cy = x+w/2, y+h/2
    border = math.ceil(bs*1.8)+2
    padded = cv2.copyMakeBorder(frame, border, border, border, border, cv2.BORDER_CONSTANT, value=(110,110,110))
    # The authors' cropScale=.4, 224px preprocessing, then center 112px crop.
    face = padded[int(cy+border-bs):int(cy+border+bs*1.8),
                  int(cx+border-bs*1.4):int(cx+border+bs*1.4)]
    if not face.size:
        return np.zeros((112,112), dtype=np.uint8)
    return cv2.cvtColor(cv2.resize(face, (224,224)), cv2.COLOR_BGR2GRAY)[56:168,56:168]


def _analyse(source, start, end, info, settings, check_cancel):
    import cv2
    import numpy as np
    import torch
    from python_speech_features import mfcc
    from scipy.io import wavfile
    from scipy.ndimage import median_filter
    model, classifier = network(settings.path)
    detector = cv2.FaceDetectorYN.create(str(assets(settings.path)[1]), "", (640,360), .75, .3, 5000)
    choice, tracks = SpeakerChoice(), FaceTracks()
    points, counts = [], {"face_frames":0, "speech_frames":0, "analysed_frames":0}
    started = time.monotonic()

    def check():
        if check_cancel and check_cancel():
            raise Cancelled("Speaker analysis cancelled")
        if time.monotonic()-started > settings.process_timeout:
            raise TimeoutError("Speaker analysis exceeded the media timeout")

    with tempfile.TemporaryDirectory(prefix="speaker-", dir=settings.path/"cache") as temporary:
        folder = Path(temporary)
        # Decode a selected cut only. Bounded video/audio files keep RAM use constant.
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(source),
             "-t", str(end-start), "-an", "-vf", "scale=960:-2,fps=25", "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", "18", "-threads", "2", str(folder/"faces.mp4")],
            timeout=settings.process_timeout, check_cancel=check_cancel)
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(source),
             "-t", str(end-start), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(folder/"audio.wav")],
            timeout=settings.process_timeout, check_cancel=check_cancel)
        sr, audio = wavfile.read(folder/"audio.wav")
        features = mfcc(audio, sr, numcep=13, winlen=.025, winstep=.01).astype(np.float32)
        cap = cv2.VideoCapture(str(folder/"faces.mp4"))
        index, previous = 0, None
        done = False
        try:
            while not done:
                check()
                batch, per_track = [], {}
                for _ in range(150):
                    check()
                    ok, frame = cap.read()
                    if not ok:
                        done = True
                        break
                    if index/FPS >= end-start:
                        done = True
                        break
                    grey = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64,36))
                    cut = previous is not None and np.mean(cv2.absdiff(grey, previous)) > 38
                    previous = grey
                    if cut:
                        tracks.reset()
                    if index % 5 == 0 or cut:
                        detector.setInputSize((frame.shape[1], frame.shape[0]))
                        _, found = detector.detect(frame)
                        boxes = [] if found is None else [tuple(map(float, b[:4])) for b in found[:6]
                                  if b[2]>=16 and b[3]>=16]
                        tracks.update(boxes)
                    item = {"index":index, "cut":cut, "faces":[],"frame":frame}
                    for tid, box in tracks.boxes.items():
                        x, _, w, _ = box
                        per_track.setdefault(tid, []).append((len(batch), index, box, (x+w/2)/frame.shape[1]))
                    batch.append(item)
                    index += 1
                for tid, rows in per_track.items():
                    check()
                    # New/missing tracks have insufficient audiovisual context; use full frame.
                    if len(rows) < 15:
                        continue
                    first, last = rows[0][1], rows[-1][1]
                    if last-first+1 != len(rows):
                        continue
                    # Suppress detector box jitter before cropping, as in the
                    # authors' median-smoothed face preprocessing. Lip motion
                    # must not be confused with a jump in crop geometry.
                    boxes = median_filter(np.asarray([r[2] for r in rows]),size=(13,1),mode="nearest")
                    crops = [_face_crop(batch[r[0]]["frame"],box) for r,box in zip(rows,boxes)]
                    visual = torch.from_numpy(np.stack(crops).astype(np.float32)).unsqueeze(0)
                    acoustic = features[first*4:(last+1)*4]
                    if len(acoustic) < len(rows)*4:
                        acoustic = np.pad(acoustic, ((0,len(rows)*4-len(acoustic)),(0,0)), mode="edge") if len(acoustic) else np.zeros((len(rows)*4,13), np.float32)
                    with torch.inference_mode():
                        a = model.forward_audio_frontend(torch.from_numpy(acoustic.copy()).unsqueeze(0))
                        v = model.forward_visual_frontend(visual)
                        contexts = []
                        # Average short and long recurrent contexts. Six seconds of
                        # visual context also reduces artificial chunk-edge effects.
                        for window in (50,150):
                            parts = []
                            for begin in range(0,len(rows),window):
                                out = model.forward_audio_visual_backend(a[:,begin:begin+window],v[:,begin:begin+window])
                                parts.append(torch.softmax(classifier(out),dim=-1)[:,1].numpy())
                            contexts.append(np.concatenate(parts))
                        scores = np.mean(contexts,axis=0)
                    for i, (position, _, _, center) in enumerate(rows):
                        score = float(np.mean(scores[max(0,i-2):i+3]))
                        batch[position]["faces"].append({"id":tid,"x":center,"score":score})
                for item in batch:
                    i = item["index"]
                    # Short pauses between words must not reset the camera. This
                    # local 0.54s energy window still falls back during silence.
                    pcm = audio[max(0,i*640-4000):min(len(audio),(i+1)*640+4000)].astype(np.float32)/32768
                    speech = bool(len(pcm) and np.sqrt(np.mean(pcm*pcm)) > .006)
                    counts["analysed_frames"] += 1
                    counts["face_frames"] += bool(item["faces"])
                    counts["speech_frames"] += speech
                    point = choice.choose(i/FPS, item["faces"], speech, item["cut"])
                    point["activity"] = item["faces"]
                    # Camera commands run at 5Hz, with immediate cut/fallback state changes.
                    if i%5 == 0 or item["cut"] or not points or point["fallback"] != points[-1]["fallback"] or point["speaker"] != points[-1]["speaker"]:
                        points.append(point)
        finally:
            cap.release()
    if not points:
        raise RuntimeError("No frames could be decoded for speaker tracking")
    return {"points":points, "counts":counts}


def analyse(source, segment, info, settings, identity, check_cancel=None):
    """Cache exact source cuts, independent of captions and output dimensions."""
    duration = segment.end-segment.start
    if check_cancel and check_cancel():
        raise Cancelled("Speaker analysis cancelled")
    key = hashlib.sha256(json.dumps([VERSION, ASD_SHA, FACE_SHA, identity, segment.start, segment.end]).encode()).hexdigest()
    cache = settings.path/"cache"/"speaker-tracks"/f"{key}.json"
    warning = None
    reused = False
    if info["audio"] and ready(settings.path):
        try:
            # Hash checks apply even when a tracking cache already exists.
            network(settings.path)
            if cache.is_file():
                result = json.loads(cache.read_text(encoding="utf-8"))
                if result.get("key") != key or not valid_points(result.get("points"), duration):
                    raise ValueError("Invalid speaker tracking cache")
                reused = True
            else:
                result = _analyse(source, segment.start, segment.end, info, settings, check_cancel)
                result["key"] = key
                atomic_json(cache, result)
        except (RuntimeError, OSError, ImportError, ValueError, TimeoutError) as exc:
            warning = f"Local speaker analysis failed ({type(exc).__name__}); full-frame fallback used."
            result = {"points":[{"time":0,"speaker":None,"center":.5,"fallback":True}],"counts":{}}
    else:
        warning = "No audio track; full-frame fallback used." if not info["audio"] else "Local speaker dependencies or model assets are missing; run the speaker setup script. Full-frame fallback used."
        result = {"points":[{"time":0,"speaker":None,"center":.5,"fallback":True}],"counts":{}}
    coverage = sum((result["points"][i+1]["time"] if i+1<len(result["points"]) else duration)-p["time"]
                   for i,p in enumerate(result["points"]) if not p["fallback"])/duration
    switches = sum(a["speaker"] is not None and b["speaker"] is not None and a["speaker"] != b["speaker"]
                   for a,b in zip([p for p in result["points"] if p["speaker"] is not None], [p for p in result["points"] if p["speaker"] is not None][1:]))
    return {**result, "engine":VERSION,"device":"cpu", "source_start":segment.start,"source_end":segment.end,
            "coverage":round(coverage,4),"track_changes":switches,"cache_reused":reused,"warning":warning,
            "calibrated":False,"review_required":True,
            "limitations":["Speaker scores are uncalibrated; inspect the output before publication.",
                "No speaker names, voice identity, or diarization are inferred.",
                "Faces outside the portrait crop limits cannot always be placed exactly at its center."]}


def valid_points(points, duration):
    if not isinstance(points,list) or not points or len(points)>int(duration*FPS)+2:
        return False
    last = -1
    for p in points:
        if not isinstance(p,dict) or type(p.get("fallback")) is not bool:
            return False
        t, x = p.get("time"), p.get("center")
        if not isinstance(t,(int,float)) or not isinstance(x,(int,float)) or not math.isfinite(t) or not math.isfinite(x) or not last<t<duration or not 0<=x<=1:
            return False
        last = t
    return points[0]["time"] == 0


def filter_graph(profile, info, tracking, command_file: Path):
    """Runtime crop/overlay commands avoid Windows command-line size limits.

    Full-frame and speaker crops share the same continuous video and audio cut.
    Moving the overlay outside the canvas reveals the padded full frame.
    """
    w, h = profile.width, profile.height
    if not valid_points(tracking["points"], tracking["source_end"]-tracking["source_start"]):
        raise ValueError("Invalid speaker crop timeline")
    factor = max(w/info["width"], h/info["height"])
    sw, sh = math.ceil(info["width"]*factor/2)*2, math.ceil(info["height"]*factor/2)*2
    commands = []
    last = None
    for p in tracking["points"]:
        x = round(max(0,min(sw-w, sw*p["center"]-w/2))/2)*2
        state = x, 2*w if p["fallback"] else 0
        if state != last:
            commands.append(f"{p['time']:.3f} [enter] crop@focus x {x}, overlay@choice x {state[1]};\n")
            last = state
    atomic_text(command_file, "".join(commands))
    return (f"[0:v]setpts=PTS-STARTPTS,sendcmd=f={command_file.name},split=2[whole][face];"
            f"[whole]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[full];"
            f"[face]scale={sw}:{sh},crop@focus={w}:{h}:0:{(sh-h)//2},setsar=1[close];"
            f"[full][close]overlay@choice=x={2*w}:y=0:shortest=1,setsar=1[v]")
