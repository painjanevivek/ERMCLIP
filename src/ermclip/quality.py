from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Literal

from pydantic import Field
from .director import Matcher, passages_for, text_for
from .media import probe, thumbnail
from .models import Candidate, Schema
from .util import run


class Finding(Schema):
    code: str
    severity: Literal["hard", "revision", "review"]
    start: float = Field(default=0, ge=0)
    end: float = Field(default=0, ge=0)
    issue: str
    correction: str


class CriticResponse(Schema):
    scores: dict[str,float]
    findings: list[Finding] = Field(default_factory=list, max_length=40)
    hard_violation: bool = False


def pre_render(spec, candidate, profile, transcript, info, matcher):
    findings = []
    if not matcher.validates_candidate(transcript,candidate):
        findings.append(Finding(code="selection",severity="hard",issue="Timeline violates requested conditions",correction="Replace the selected material"))
    for segment in candidate.segments:
        if segment.end>info["duration"] or segment.start<0:
            findings.append(Finding(code="timestamp",severity="hard",issue="Source timestamps are invalid",correction="Choose valid source timestamps"))
        crossed = [p for p in transcript.passages if p.start < segment.start < p.end-0.1 or p.start+0.1 < segment.end < p.end]
        if crossed:
            partial_word = any(w.start+.04 < t < w.end-.04 for p in crossed for w in p.words for t in (segment.start,segment.end))
            if partial_word or any(not p.words for p in crossed):
                findings.append(Finding(code="incomplete_statement",severity="revision",start=0,end=candidate.duration,issue="An edit boundary cuts a word or an unaligned transcript passage",correction="Move the boundary to complete speech; retain duration constraints"))
            else:
                findings.append(Finding(code="word_aligned_boundary",severity="review",start=0,end=candidate.duration,issue="An edit uses a complete-word boundary inside an ASR passage. Passage boundaries do not prove sentence boundaries.",correction="Check the joined speech and sentence context before publication"))
    selected = passages_for(transcript,candidate)
    if selected and re.match(r"^(and|but|so|he|she|it|they|that)\b", selected[0].text.strip(), re.I):
        findings.append(Finding(code="missing_context",severity="review",end=min(8,candidate.duration),issue="Opening may depend on preceding context",correction="Check whether the opening actually needs a preceding statement before changing its boundary"))
    texts = [p.text.strip().lower() for p in selected if p.text.strip()]
    if len(texts)!=len(set(texts)):
        findings.append(Finding(code="repetition",severity="review",issue="Repeated source wording found",correction="Review repeated material and remove only if meaning is preserved"))
    if not selected:
        findings.append(Finding(code="no_content",severity="hard",issue="No transcript evidence covers the selected timeline",correction="Choose evidence-backed footage"))
    return findings


def audiovisual(video, candidate, profile, transcript, cues, settings, check_cancel=None):
    import cv2
    import numpy as np
    findings = []
    info = probe(video)
    video_duration = float(info["video"].get("duration", info["duration"]))
    if video_duration > 900.001 or abs(video_duration-candidate.duration)>0.12:
        findings.append(Finding(code="duration",severity="hard",issue="Video duration is outside timeline limits",correction="Render the validated timeline again"))
    if (info["width"],info["height"]) != (profile.width,profile.height):
        findings.append(Finding(code="resolution",severity="hard",issue="Output dimensions differ from the profile",correction="Render with the correct scale and framing"))
    av_delta = None
    if info["audio_stream"]:
        audio = info["audio_stream"]
        av_delta = abs(float(audio.get("start_time",0))-float(info["video"].get("start_time",0)))
        if av_delta > 0.1 or abs(float(audio.get("duration",video_duration))-video_duration)>0.2:
            findings.append(Finding(code="av_sync",severity="hard",issue="Audio and video stream timing differs",correction="Reset segment timestamps and render again"))
    else:
        findings.append(Finding(code="missing_audio",severity="hard",issue="Rendered output has no audio stream",correction="Render audio with video"))
    offsets = []
    total = 0
    for s in candidate.segments[:-1]:
        total += s.end-s.start
        offsets.extend([max(0,total-0.12),min(video_duration-0.05,total+0.12)])
    times = sorted(set([0.05,video_duration/2,max(0.05,video_duration-0.15),*offsets]))
    capture = cv2.VideoCapture(str(video))
    frame_evidence = []
    frame_dir = video.parent / (video.stem+"_review")
    frame_dir.mkdir(exist_ok=True)
    try:
        for i,t in enumerate(times):
            if check_cancel and check_cancel():
                from .util import Cancelled
                raise Cancelled()
            capture.set(cv2.CAP_PROP_POS_MSEC,t*1000)
            ok,frame = capture.read()
            if not ok:
                findings.append(Finding(code="decode",severity="hard",start=t,end=t,issue="Rendered frame cannot be decoded",correction="Render again and verify the source"))
                continue
            grey = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            file = frame_dir / f"frame_{i:03}.jpg"
            cv2.imwrite(str(file),frame)
            frame_evidence.append({"time":t,"path":str(file),"mean_luma":float(grey.mean()),"black_fraction":float(np.mean(grey<12)),"sharpness":float(cv2.Laplacian(grey,cv2.CV_64F).var())})
    finally:
        capture.release()
    result = run(["ffmpeg","-hide_banner","-i",str(video),"-vf","scale=320:-2,blackdetect=d=0.3:pix_th=0.08,freezedetect=n=-50dB:d=2","-af","silencedetect=n=-45dB:d=2,astats=metadata=0:reset=0","-f","null","-"],timeout=settings.process_timeout,check_cancel=check_cancel)
    black = [{"start":float(a),"end":float(b)} for a,b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)",result.stderr)]
    frozen = [float(t) for t in re.findall(r"freeze_start: ([0-9.]+)",result.stderr)]
    silence = [float(t) for t in re.findall(r"silence_start: ([0-9.]+)",result.stderr)]
    peak = re.findall(r"Peak level dB: ([\-0-9.inf]+)",result.stderr)
    if black:
        findings.append(Finding(code="black_frames",severity="review",start=black[0]["start"],end=black[0]["end"],issue="Black footage detected in the actual render; source intent is unknown",correction="Inspect the sampled footage; replace unintended black sections"))
    if frozen:
        findings.append(Finding(code="frozen_frames",severity="review",start=frozen[0],end=min(video_duration,frozen[0]+2),issue="Static footage detected; it may be intentional",correction="Inspect the source and output for unintended freezes"))
    if silence and len(silence)>2:
        findings.append(Finding(code="silence",severity="review",start=silence[0],end=min(video_duration,silence[0]+2),issue="Several long silent intervals detected",correction="Review pacing and check that source audio is present"))
    if profile.captions.burn and any(p.words for p in passages_for(transcript,candidate)) and not cues:
        findings.append(Finding(code="missing_captions",severity="hard",issue="Verified speech has no subtitle cues",correction="Regenerate subtitles from aligned words"))
    for cue in cues:
        if cue.start < -0.01 or cue.end > video_duration+0.1 or cue.end<=cue.start:
            findings.append(Finding(code="subtitle_timing",severity="hard",start=max(0,cue.start),end=cue.end,issue="Subtitle timing is outside the output",correction="Map source words to the output timeline again"))
        if len(cue.text)/max(0.1,cue.end-cue.start)>28:
            findings.append(Finding(code="subtitle_readability",severity="review",start=cue.start,end=cue.end,issue="Caption reading speed is high",correction="Review shorter caption groups or a longer excerpt"))
    # Save actual cut audio for human review. This is evidence, not a perceptual sync claim.
    cut_audio = []
    for i,t in enumerate(offsets[::2]):
        file = frame_dir / f"cut_{i:03}.wav"
        run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",str(max(0,t-0.5)),"-i",str(video),"-t","1.25","-vn","-ac","1","-ar","16000",str(file)],timeout=60,check_cancel=check_cancel)
        cut_audio.append(str(file))
    evidence = {"probe":info,"sampled_frames":frame_evidence,"cut_audio":cut_audio,"black_intervals":black,"freeze_starts":frozen,"silence_starts":silence,"peak_db":peak[-1] if peak else None,"stream_start_delta":av_delta,"limits":["Metric checks do not prove perceptual AV sync, speaker visibility, semantic accuracy, or caption legibility.","The text critic sees numerical frame and audio findings, not image pixels or sound."]}
    return findings,evidence


def evaluate(spec,candidate,profile,transcript,info,matcher,video,cues,settings,model,check_cancel=None,speaker_tracking=None):
    before = pre_render(spec,candidate,profile,transcript,info,matcher)
    rendered,evidence = audiovisual(video,candidate,profile,transcript,cues,settings,check_cancel)
    findings = before+rendered
    if speaker_tracking is not None:
        evidence["speaker_tracking"] = [{k:v for k,v in s.items() if k not in ("points","key")}
                                        for s in speaker_tracking["segments"]]
        findings.append(Finding(code="speaker_framing_review",severity="review",
            issue="Local audiovisual speaker framing is uncalibrated. Check speaker changes and full-frame fallback intervals.",
            correction="Inspect the saved video and speaker tracking sidecar before publication.",start=0,end=candidate.duration))
    elif profile.framing == "speaker":
        findings.append(Finding(code="speaker_full_frame_review",severity="review",
            issue="This podcast uses a full-frame override instead of active-speaker crops.",
            correction="Inspect framing or restore speaker mode.",start=0,end=candidate.duration))
    weights = {"relevance":25,"coherence":25,"hook_pacing":15,"value":15,"visual":10,"audio_subtitles":10}
    scores = None
    critic_used = False
    if model.enabled:
        selected=[]
        offset=0
        for segment in candidate.segments:
            for p in transcript.passages:
                if p.start>=segment.end or p.end<=segment.start:
                    continue
                text="".join(w.text for w in p.words if w.start>=segment.start and w.end<=segment.end).strip() if p.words else p.text
                selected.append({"start":round(offset+max(p.start,segment.start)-segment.start,3),"end":round(offset+min(p.end,segment.end)-segment.start,3),"text":text,"partial_start":p.start<segment.start<p.end-0.1,"partial_end":p.start+0.1<segment.end<p.end})
            offset+=segment.end-segment.start
        # Director assertions and scores are excluded from the isolated Critic context.
        payload = {"instruction":spec.instruction,"output_duration":candidate.duration,"selected_transcript":selected,"technical_findings":[f.model_dump() for f in findings],"audiovisual_metrics":{k:v for k,v in evidence.items() if k != "probe"},"criteria":list(weights),"score_scale":"Each criterion has its own quality score from 0 to 100. 100 is excellent, 85 is strong, 70 needs improvement, 40 is poor, and 0 is unusable. Return quality scores, not criterion weights or percentage shares. The worker computes importance weights separately.","task":"Evaluate only the actual selected transcript and measured evidence. Scores 0-100 for exactly the six criteria. Transcript times are OUTPUT-relative. Findings must use times between zero and output_duration. Treat partial_start or partial_end as incomplete speech. Use incomplete_statement only for a verified partial boundary, not an ordinary weak narrative. Use editorial_narrative for weak progression or an unresolved idea. All technical findings remain binding. State only evidence-backed problems with a specific correction. Do not invent repeated statements, missing speech, or visual defects. missing_context means the opening depends on a missing referent. hard_violation is true only for a verified hard constraint violation. You have metrics, not pixels or audio. Visual and audio scores are provisional metric-based scores."}
        payload["proposed_title"]=candidate.title
        payload['render_layout']=profile.layout.model_dump()
        payload['metric_interpretation']=(
            'Frame luma and black fraction measure the whole canvas, including margins and the studio background. '
            'A black podcast canvas is intentional. These numbers alone do not prove that a face is dark, obscured or off-center. '
            'You cannot see pixels; do not prescribe exposure or crop changes from whole-frame darkness alone. '
            'Speaker audit segments are edit segments, not person counts. Track changes are activity/face-track changes, not verified identities. '
            'Speaker cropping changes only video framing; it cannot remove speech from the continuous source audio. '
            'Read every selected transcript row, including any conclusion after a wait-and-watch or uncertainty statement.')
        payload["title_check"]="Check that the proposed title is supported by the actual selected text. Report title_mismatch with review severity if it is misleading."
        try:
            schema = CriticResponse.model_json_schema()
            schema["properties"]["scores"] = {"type":"object", "properties":{key:{"type":"number", "minimum":0, "maximum":100} for key in weights}, "required":list(weights), "additionalProperties":False}
            critic = CriticResponse.model_validate(model.json("critic",payload,schema))
            if set(critic.scores) != set(weights) or any(not __import__("math").isfinite(v) or not 0<=v<=100 for v in critic.scores.values()):
                raise ValueError("Invalid critic scorecard")
            scores = critic.scores
            if scores == weights:
                scores = None
                raise ValueError("Critic returned importance weights instead of quality scores")
            critic_used = True
            for finding in critic.findings:
                if finding.end<finding.start or finding.start>candidate.duration+0.1 or finding.end>candidate.duration+0.1:
                    findings.append(Finding(code="critic_evidence_invalid",severity="review",issue="A critic finding used a timestamp outside the output and was excluded from automatic repair",correction="Review the saved media and verify the claimed issue"))
                    continue
                if finding.code=="incomplete_statement" and not any(f.code=="incomplete_statement" for f in before):
                    finding.code="editorial_narrative"
                    finding.severity="review"
                findings.append(finding)
            if critic.hard_violation:
                findings.append(Finding(code="critic_hard",severity="hard",issue="Critic identified a hard editorial violation",correction="Replace material or request human review"))
        except (RuntimeError,ValueError,OSError,KeyError) as exc:
            findings.append(Finding(code="critic_unavailable",severity="review",issue=f"Local critic failed: {type(exc).__name__}",correction="Review manually or restore the local model"))
    else:
        findings.append(Finding(code="editorial_review",severity="review",issue="Independent AI critic is not configured. Technical checks cannot certify editorial quality.",correction="Have Hermes or a human review the saved media and timeline"))
    weighted = sum(scores[k]*v/100 for k,v in weights.items()) if scores else None
    hard = any(f.severity=="hard" for f in findings)
    if hard or (weighted is not None and weighted<70):
        status = "rejected"
    elif any(f.severity=="revision" for f in findings) or (weighted is not None and weighted<85):
        status = "revision_required"
    elif any(f.severity=="review" for f in findings) or not critic_used:
        status = "review_required"
    else:
        status = "passed"
    return {"status":status,"scores":scores,"weighted_score":weighted,"heuristic":True,"calibrated":False,"critic":"local-isolated-text" if critic_used else "unavailable","revision":candidate.revision,"findings":[f.model_dump() for f in findings],"evidence":evidence}


def revise(candidate: Candidate, findings: list[dict], transcript, profile, source_duration):
    updated = candidate.model_copy(deep=True)
    changed = False
    codes = {f["code"] for f in findings if f.get("severity","revision")=="revision"}
    if "incomplete_statement" in codes or "missing_context" in codes:
        for i,segment in enumerate(updated.segments):
            for p in transcript.passages:
                if p.start<segment.start<p.end:
                    segment.start=p.start
                    changed=True
                if p.start<segment.end<p.end:
                    segment.end=p.end
                    changed=True
            if i==0 and "missing_context" in codes:
                previous = [p for p in transcript.passages if p.end<=segment.start]
                if previous:
                    segment.start=previous[-1].start
                    changed=True
    if any(f["code"]=="cropping" for f in findings) and (updated.framing or profile.framing) not in ("pad", "speaker"):
        updated.framing="pad"
        changed=True
    if not changed or updated.duration>profile.duration.maximum or updated.duration<profile.duration.minimum or updated.duration>900 or any(s.end>source_duration for s in updated.segments):
        return None
    if profile.duration.strict and abs(updated.duration-profile.duration.target)>0.05:
        return None
    updated.revision+=1
    return updated
