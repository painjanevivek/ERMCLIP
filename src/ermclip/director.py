from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .models import Candidate, EditingPlan, JobSpec, Segment, Transcript
from .util import UnsupportedRequest, atomic_json


def words(text):
    return re.findall(r"[\w]+", text.lower())


def phrase(term, text):
    return bool(re.search(r"(?<!\w)" + re.escape(term.lower().strip()) + r"(?!\w)", text.lower()))


def passages_for(transcript: Transcript, candidate: Candidate):
    selected=[]
    for s in candidate.segments:
        for p in transcript.passages:
            if p.start>=s.end or p.end<=s.start:
                continue
            if p.words:
                aligned=[w for w in p.words if w.start>=s.start-.001 and w.end<=s.end+.001]
                if not aligned:
                    continue
                selected.append(p.model_copy(update={"text":" ".join(w.text.strip() for w in aligned),"words":aligned}))
            else:
                selected.append(p)
    return selected


def text_for(transcript: Transcript, candidate: Candidate):
    return " ".join(p.text for p in passages_for(transcript, candidate))


class Matcher:
    def __init__(self, spec: JobSpec, transcript: Transcript, settings, cache: Path):
        self.conditions = spec.conditions
        self.semantic = {}
        if self.conditions.visual_events:
            raise UnsupportedRequest("Visual event matching requires verified event annotations; this version cannot recognise actions")
        if self.conditions.speaker and not any(p.speaker for p in transcript.passages):
            raise UnsupportedRequest("No verified speaker labels exist in this transcript")
        if self.conditions.topics:
            if not settings.semantic_model:
                raise UnsupportedRequest("Semantic topic requests require a configured local embedding model; no keyword match will be substituted")
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise UnsupportedRequest("Install the semantic optional dependency first") from exc
            model = SentenceTransformer(settings.semantic_model, device="cpu", local_files_only=not settings.allow_model_download, cache_folder=str(settings.path / "cache" / "models"))
            key = hashlib.sha256(json.dumps({"model":settings.semantic_model,"text":[p.text for p in transcript.passages]}).encode()).hexdigest()[:24]
            target = cache / f"embeddings_{key}.json"
            if target.exists():
                vectors = json.loads(target.read_text(encoding="utf-8"))
            else:
                vectors = model.encode([p.text for p in transcript.passages], normalize_embeddings=True).tolist()
                atomic_json(target, vectors)
            queries = model.encode(self.conditions.topics, normalize_embeddings=True).tolist()
            for p,vector in zip(transcript.passages, vectors):
                self.semantic[p.start] = min(sum(a*b for a,b in zip(vector,q)) for q in queries)
            del model

    def matches_passage(self, p):
        c = self.conditions
        if any(phrase(term, p.text) for term in c.exclude):
            return False
        if c.speaker and p.speaker != c.speaker:
            return False
        tests = [phrase(term,p.text) for term in c.keywords]
        if tests and not (all(tests) if c.all_keywords else any(tests)):
            return False
        if c.topics and self.semantic.get(p.start, -1) < 0.4:
            return False
        return True

    def validates_candidate(self, transcript, candidate):
        c = self.conditions
        passages = passages_for(transcript, candidate)
        text = text_for(transcript, candidate)
        if any(phrase(term, text) for term in c.exclude):
            return False
        if c.speaker and any(p.speaker != c.speaker for p in passages):
            return False
        # Every compilation segment must qualify; context within each segment is allowed.
        for s in candidate.segments:
            local = passages_for(transcript,candidate.model_copy(update={"segments":[s]}))
            local_text = " ".join(p.text for p in local)
            tests = [phrase(term,local_text) for term in c.keywords]
            if tests and not (all(tests) if c.all_keywords else any(tests)):
                return False
            if c.topics and not any(self.semantic.get(p.start, -1) >= 0.4 for p in local):
                return False
        return True


def rank(text):
    tokens = words(text)
    informative = len(set(tokens))/max(1,len(tokens))
    markers = sum(phrase(x,text) for x in ("because", "why", "how", "imagine", "surprising", "predict", "example", "learn", "problem", "solution"))
    return min(100, 35 + informative*30 + markers*4 + min(len(tokens),100)*0.1)


def title(text):
    sentence = re.split(r"[.!?]", text.strip())[0]
    return (sentence[:90].strip() or "Selected source excerpt")


def full_transcript_plan(spec, transcript, source_info, identity, settings, model, preferences, warnings, verified_windows, matcher):
    """Let the larger model read the whole compact source when it fits.

    Passage indexes bind every edit to source evidence. The model cannot
    create timestamps. All conditions, counts and durations are validated.
    """
    if settings.director_model!='ermclip-qwen35-9b' or any(p.strategy!='continuous' or p.duration.strict for p in spec.profiles):
        return None
    payload={'instruction':spec.instruction,'conditions':spec.conditions.model_dump(),'profiles':[p.model_dump(include={'name','duration','count','total_duration','strategy'}) for p in spec.profiles],'source_duration':source_info['duration'],'columns':['passage_index','source_start','source_end','actual_speech'],'transcript':[[i,p.start,p.end,p.text] for i,p in enumerate(transcript.passages)],'feedback':preferences,'task':'Read the complete source transcript. Choose self-contained, useful excerpts that meet the instruction and all conditions. Each selection names a profile and inclusive start_passage/end_passage indexes. For that profile and start_passage, copy end_passage from valid_end_indexes. These pairs already meet duration and source conditions. Start at an actual setup or complete sentence, retain the full explanation, and end at its conclusion before the next topic. Do not pad with reactions or unrelated speech. Choose fewer excerpts if needed. Titles and reasons must describe the speech actually inside the chosen indexes.'}
    starts={p.start:i for i,p in enumerate(transcript.passages)}
    ends={p.end:i for i,p in enumerate(transcript.passages)}
    valid_ends={p.name:{} for p in spec.profiles}
    for window in verified_windows:
        start=starts[window['start']]; end=ends[window['end']]
        for name in window['profiles']:
            options=valid_ends[name].setdefault(str(start),[])
            if end not in options: options.append(end)
    for profile in spec.profiles:
        for start, options in valid_ends[profile.name].items():
            complete=[end for end in options if re.search(r'[.!][\"\u201d\u2019]*$',transcript.passages[end].text)] or options
            closest=min(complete,key=lambda end:abs(transcript.passages[end].end-transcript.passages[int(start)].start-profile.duration.target))
            valid_ends[profile.name][start]=list(dict.fromkeys([closest,min(complete),max(complete)]))
    payload['valid_end_indexes']=valid_ends
    # Keep the entire source context. Reduce alternative endings rather than
    # remove possible openings or omit speech from the model's evidence.
    for cap in (2,1):
        if len(json.dumps(payload))<=35000: break
        for entries in valid_ends.values():
            for start in entries: entries[start]=entries[start][:cap]
    if len(json.dumps(payload))>35000:
        return None
    if not verified_windows:
        return EditingPlan(instruction=spec.instruction,source=spec.source,fingerprint=identity,source_duration=source_info['duration'],mode=spec.mode,profiles=spec.profiles,candidates=[],director='verified-constraints',warnings=warnings+['No source windows meet the verified conditions and duration limits. No model call or filler was needed.'])
    from pydantic import Field
    from .models import Schema
    choices={f'{name}/{start}:{end}':(name,int(start),end) for name,entries in valid_ends.items() for start,options in entries.items() for end in options}
    payload.pop('valid_end_indexes')
    payload['task']='Read the complete source transcript. Select useful, self-contained excerpts that meet the instruction. Copy choice EXACTLY from the schema enum. Each choice is profile/start_passage:end_passage, with inclusive indexes into the complete transcript. All listed choices already meet source conditions and duration limits. Start with a clear setup, keep the explanation, and end at its actual conclusion before the next topic. Avoid padding with reactions or unrelated discussion. Return fewer selections if needed. Titles and reasons must describe only the selected speech.'
    class Selection(Schema):
        choice: str
        title: str = Field(max_length=100)
        reason: str
        score: float = Field(default=0,ge=0,le=100)
    class Output(Schema):
        selections: list[Selection] = Field(max_length=min(20,sum(p.count or 6 for p in spec.profiles)))
        warnings: list[str] = Field(default_factory=list)
    schema=Output.model_json_schema()
    schema['$defs']['Selection']['properties']['choice']={'type':'string','enum':list(choices)}
    for attempt in range(2):
        try:
            selected=Output.model_validate(model.json('director',payload,schema))
            candidates=[]
            counts=Counter()
            for choice in selected.selections:
                if choice.choice not in choices:
                    raise ValueError('Unknown source choice or excluded source conditions; copy a valid enum value')
                name,start,end=choices[choice.choice]
                actual=transcript.passages[start:end+1]
                counts[name]+=1
                candidate=Candidate(id=f'clip_{counts[name]:03}',profile=name,title=choice.title,reason=choice.reason,score=choice.score,segments=[Segment(start=actual[0].start,end=actual[-1].end,reason=choice.reason)],narrative=[actual[0].text,actual[len(actual)//2].text,actual[-1].text])
                if not matcher.validates_candidate(transcript,candidate):
                    raise ValueError('Chosen source passages violate the inclusion or exclusion conditions')
                candidates.append(candidate)
            result=EditingPlan(instruction=spec.instruction,source=spec.source,fingerprint=identity,source_duration=source_info['duration'],mode=spec.mode,profiles=spec.profiles,candidates=candidates,director='local-llm-full-transcript',warnings=warnings+selected.warnings,constraints={'paid_budget':0,'max_model_calls':settings.max_model_calls,'max_revisions':settings.revisions,'director_source_coverage':'complete compact transcript'})
            return result
        except ValueError as exc:
            if attempt: raise
            payload['validation_error']=str(exc)[:3000]
            payload['correction_task']='Return a fresh valid selection. Fix the stated constraint error. Do not change the source evidence.'


def plan(spec: JobSpec, transcript: Transcript, source_info: dict, identity: str, settings, cache: Path, model, preferences) -> EditingPlan:
    matcher = Matcher(spec, transcript, settings, cache)
    warnings = list(transcript.warnings)
    if any(p.trim_silence for p in spec.profiles):
        warnings.append("Silence trimming is not applied: removing speech pauses without alignment review can change pacing and meaning.")
    if spec.approved_plan:
        result = EditingPlan.model_validate_json(Path(spec.approved_plan).read_text(encoding="utf-8"))
        if result.fingerprint != identity or result.instruction != spec.instruction or result.mode != spec.mode or [p.model_dump() for p in result.profiles] != [p.model_dump() for p in spec.profiles]:
            raise ValueError("Approved plan does not match this source and request")
        result.source_duration = source_info["duration"]
        result = EditingPlan.model_validate(result.model_dump())
        if not all(matcher.validates_candidate(transcript,c) for c in result.candidates):
            raise ValueError("Approved plan violates verified selection conditions")
        return result
    if model.enabled:
        if len(json.dumps([[p.start,p.end,p.text] for p in transcript.passages])) > 35000 and len(spec.profiles)==1 and spec.profiles[0].strategy=='continuous' and not spec.profiles[0].duration.strict:
            from .long_source import plan_full_source
            return plan_full_source(spec,transcript,source_info,identity,settings,cache,model,matcher)
        # Word alignment is needed by captions, but wastes the director's context.
        passages = [p.model_dump(exclude={"words"}) for p in transcript.passages]
        payload = {"instruction":spec.instruction,"conditions":spec.conditions.model_dump(),"profiles":[p.model_dump() for p in spec.profiles],"source_duration":source_info["duration"],"transcript":passages,"feedback":preferences,"max_outputs":20,"task":"Select useful, complete moments. Use exact passage start and end timestamps. For each profile obey its name, count, duration minimum and maximum, strategy, and total duration. Candidate IDs use clip_001 format. Initial revision is 0. Each continuous candidate has exactly one segment. Return fewer outputs or no candidates when conditions cannot be met. Do not pad, invent matches, or include excluded words. Prefer a clear question followed by its complete explanation and conclusion."}
        windows=[]
        # Verify windows against the full transcript, even when it cannot fit
        # in a single model prompt. Send only shortlisted evidence below.
        window_passages=transcript.passages
        max_window=max(p.duration.maximum for p in spec.profiles)
        monotonic_ends=all(a.end<=b.end for a,b in zip(transcript.passages,transcript.passages[1:]))
        for i,p in enumerate(window_passages):
            for tail in transcript.passages[i:]:
                if tail.end<=p.start:
                    continue
                if monotonic_ends and tail.end-p.start>max_window:
                    break
                valid=[]
                for profile in spec.profiles:
                    if profile.strategy!="continuous":
                        continue
                    duration=tail.end-p.start
                    if not profile.duration.minimum<=duration<=profile.duration.maximum:
                        continue
                    if profile.duration.strict and abs(duration-profile.duration.target)>0.05:
                        continue
                    c=Candidate(id="clip_001",profile=profile.name,title="Verified window",segments=[Segment(start=p.start,end=tail.end,reason="Complete passage boundaries")],reason="Verified source window")
                    if matcher.validates_candidate(transcript,c):
                        valid.append(profile.name)
                if valid:
                    windows.append({"start":p.start,"end":tail.end,"seconds":round(tail.end-p.start,3),"profiles":valid})
            for profile in spec.profiles:
                ending=p.start+profile.duration.target
                if profile.strategy!="continuous" or not profile.duration.strict or ending>source_info["duration"]:
                    continue
                if any(abs(w["start"]-p.start)<0.001 and abs(w["end"]-ending)<0.001 and profile.name in w["profiles"] for w in windows):
                    continue
                c=Candidate(id="clip_001",profile=profile.name,title="Strict duration window",segments=[Segment(start=p.start,end=ending,reason="Exact requested duration; partial speech requires review")],reason="Strict requested duration")
                if matcher.validates_candidate(transcript,c):
                    windows.append({"start":p.start,"end":ending,"seconds":profile.duration.target,"profiles":[profile.name]})
        full_plan=full_transcript_plan(spec,transcript,source_info,identity,settings,model,preferences,warnings,windows,matcher)
        if full_plan is not None:
            return full_plan
        # Three duration options per opening keep the choice table small and readable.
        keep=set()
        for profile in spec.profiles:
            for start in {w["start"] for w in windows if profile.name in w["profiles"]}:
                local=[(i,w) for i,w in enumerate(windows) if w["start"]==start and profile.name in w["profiles"]]
                if local:
                    keep.update([min(local,key=lambda pair:abs(pair[1]["seconds"]-profile.duration.target))[0],min(local,key=lambda pair:pair[1]["seconds"])[0],max(local,key=lambda pair:pair[1]["seconds"])[0]])
        windows=[w for i,w in enumerate(windows) if i in keep]
        # A small text model chooses more reliably from a readable shortlist.
        # This stage filters options; the local model still makes the editorial choice.
        if all(p.strategy=="continuous" for p in spec.profiles):
            ignored=set("select create make one each clip clips video videos profile profiles complete explanation clear opening ending keep speech intact best section matters prefer find mentioning exclude cryptocurrency full for the with and from that this".split())
            requested=(set(words(spec.instruction))-ignored)|set(words(" ".join(spec.conditions.keywords)))
            def priority(w,profile):
                selected=[p for p in transcript.passages if p.start<w["end"] and p.end>w["start"]]
                text=" ".join(p.text for p in selected)
                opening=selected[0].text
                ending=selected[-1].text
                relevance=len(requested & set(words(text))) * 8
                hook=12 if opening.endswith("?") else 0
                hook+=8 if requested & set(words(opening)) else 0
                penalty=20 if ending.endswith("?") else 0
                penalty+=20 if not re.search(r'[.!?][\"\u201d\u2019]*$',ending) else 0
                penalty+=15 if opening and opening[0].islower() else 0
                penalty+=10 if re.match(r"^(and|but|so|he|she|it|they|that)\b",opening,re.I) else 0
                return relevance+hook-penalty-abs(w["seconds"]-profile.duration.target)/10
            keep=set()
            for profile in spec.profiles:
                local=[(i,w) for i,w in enumerate(windows) if profile.name in w["profiles"]]
                keep.update(i for i,w in sorted(local,key=lambda pair:priority(pair[1],profile),reverse=True)[:max(12,min(40,(profile.count or 3)*4))])
            windows=[w for i,w in enumerate(windows) if i in keep]
        window_lookup={f"window_{i:04}":w for i,w in enumerate(windows)}
        payload["window_columns"]=["window_id","start","end","seconds","allowed_profiles","actual_selected_text"]
        payload["valid_continuous_windows"]=[[key,w["start"],w["end"],w["seconds"],w["profiles"]," ".join(p.text for p in transcript.passages if p.start<w["end"] and p.end>w["start"])] for key,w in window_lookup.items()]
        if all(p.strategy=='continuous' for p in spec.profiles) and len(json.dumps(payload))>35_000:
            selected_passages=[p for p in transcript.passages if any(p.start<w['end'] and p.end>w['start'] for w in windows)]
            payload['transcript']=[p.model_dump(exclude={'words'}) for p in selected_passages]
            payload['coverage']={'full_source_passages':len(transcript.passages),'provided_passages':len(selected_passages),'method':'Full-source constraint verification and heuristic shortlist. Only shortlisted evidence is sent to the local Director.'}
            warnings.append('Long-source editorial choice uses a heuristic shortlist. The local Director reads all shortlisted speech; omitted moments require review.')
            # The window table already contains the exact speech, so a second
            # copy of those passages adds no evidence.
            if len(json.dumps(payload))>35_000:
                payload['transcript']=[]
            while len(json.dumps(payload))>35_000 and len(windows)>len(spec.profiles):
                counts=Counter(p for w in windows for p in w['profiles'])
                removable=[i for i,w in enumerate(windows) if all(counts[p]>1 for p in w['profiles'])]
                if not removable: break
                # Remove the lowest-priority option, not source text inside a window.
                index=min(removable,key=lambda i:max(priority(windows[i],p) for p in spec.profiles if p.name in windows[i]['profiles']))
                del windows[index]
                window_lookup={f'window_{i:04}':w for i,w in enumerate(windows)}
                payload['valid_continuous_windows']=[[key,w['start'],w['end'],w['seconds'],w['profiles'],' '.join(p.text for p in transcript.passages if p.start<w['end'] and p.end>w['start'])] for key,w in window_lookup.items()]
        payload["boundary_rule"]="For continuous outputs copy an exact start/end pair from valid_continuous_windows for that profile. Do not calculate a new pair. If no such window exists, return no candidates for it."
        if len(json.dumps(payload)) > 35_000:
            warnings.append("Transcript exceeds the local director input budget. Used deterministic selection; configure a larger-context director for deeper analysis.")
        else:
            from pydantic import Field
            from .models import Schema
            class DirectorOutput(Schema):
                candidates: list[Candidate] = Field(max_length=100)
                warnings: list[str] = Field(default_factory=list)
            continuous=all(p.strategy=="continuous" for p in spec.profiles)
            if continuous:
                if not window_lookup:
                    return EditingPlan(instruction=spec.instruction,source=spec.source,fingerprint=identity,source_duration=source_info["duration"],mode=spec.mode,profiles=spec.profiles,candidates=[],director="verified-constraints",warnings=warnings+["No source windows meet the verified conditions and duration limits. No model call or filler was needed."],constraints={"paid_budget":0,"max_model_calls":settings.max_model_calls,"max_revisions":settings.revisions})
                class Selection(Schema):
                    choice: str
                    title: str = Field(max_length=100)
                    reason: str
                    narrative: list[str] = Field(default_factory=list)
                    score: float = Field(default=0,ge=0,le=100)
                class SelectionOutput(Schema):
                    selections: list[Selection] = Field(max_length=20)
                    warnings: list[str] = Field(default_factory=list)
                choices={}
                for key,w in window_lookup.items():
                    actual=[p.text for p in transcript.passages if p.start<w["end"] and p.end>w["start"]]
                    for profile in w["profiles"]:
                        # Meaningful labels stop a small model from confusing opaque IDs.
                        label=f"{profile}/{key}: {actual[0]} -> {actual[-1]}"
                        choices[label]=(profile,w)
                schema=SelectionOutput.model_json_schema()
                schema["$defs"]["Selection"]["properties"]["choice"]={"type":"string","enum":list(choices) or ["NO_VALID_WINDOW"]}
                schema["properties"]["selections"]["maxItems"]=min(20,sum(p.count or 6 for p in spec.profiles))
                payload["task"]="Select the most useful complete explanation for each output profile. Return selections, each with a choice copied EXACTLY from the schema's enum, title, reason, narrative and score. Choice labels show their actual opening and ending. The worker uses verified timestamps for that choice. Do not calculate timestamps or create candidate IDs. Respect count and total duration. Return fewer selections or none if no useful qualifying material exists. Prefer a clear question with its complete explanation and conclusion."
                payload["title_and_reason_rule"]="Each choice has its exact speech in valid_continuous_windows. Write its title and reason ONLY from that row's actual_selected_text. Do not describe ideas outside that window. An idea introduced just before the ending is not a complete explanation. Prefer a window containing both the question and the full answer."
                payload.pop("boundary_rule",None)
            else:
                schema=DirectorOutput.model_json_schema()
                candidate_schema=schema["$defs"]["Candidate"]["properties"]
                candidate_schema["profile"]={"type":"string", "enum":[p.name for p in spec.profiles]}
                candidate_schema["framing"]={"anyOf":[{"type":"string", "enum":["smart","center","pad","blur","original","speaker"]},{"type":"null"}]}
                candidate_schema["revision"]={"type":"integer", "const":0}
            for attempt in range(2):
                try:
                    raw=model.json("director", payload, schema)
                    if continuous:
                        selected=SelectionOutput.model_validate(raw)
                        converted=[]
                        counts=Counter()
                        for selection in selected.selections:
                            if selection.choice not in choices:
                                raise ValueError("Unknown source window choice; select a value from the supplied enum")
                            profile,w=choices[selection.choice]
                            counts[profile]+=1
                            actual=[p.text for p in transcript.passages if p.start<w["end"] and p.end>w["start"]]
                            narrative=[actual[0],actual[len(actual)//2],actual[-1]] if actual else []
                            converted.append(Candidate(id=f"clip_{counts[profile]:03}",profile=profile,title=selection.title,segments=[Segment(start=w["start"],end=w["end"],reason=selection.reason)],reason=selection.reason,narrative=narrative,score=selection.score))
                        response=DirectorOutput(candidates=converted,warnings=selected.warnings)
                    else:
                        response=DirectorOutput.model_validate(raw)
                    for c in response.candidates:
                        profile=next((p for p in spec.profiles if p.name==c.profile),None)
                        if profile and not profile.duration.minimum<=c.duration<=profile.duration.maximum:
                            raise ValueError(f"{c.id}/{c.profile}: duration {c.duration:.3f} seconds is outside {profile.duration.minimum}..{profile.duration.maximum}. Chosen segments: {[s.model_dump() for s in c.segments]}. Copy a valid window pair for this profile.")
                    result = EditingPlan(instruction=spec.instruction, source=spec.source, fingerprint=identity, source_duration=source_info["duration"], mode=spec.mode, profiles=spec.profiles, candidates=response.candidates, director="local-llm", warnings=warnings+response.warnings, constraints={"paid_budget":0,"max_model_calls":settings.max_model_calls,"max_revisions":settings.revisions})
                    if not all(matcher.validates_candidate(transcript,c) for c in result.candidates):
                        raise ValueError("Director response violates verified source selection conditions")
                    return result
                except ValueError as exc:
                    if attempt:
                        raise
                    payload["validation_error"] = str(exc)[:3000]
                    payload["correction_task"] = "Generate a fresh valid plan. Fix this validation error. All original source conditions still apply."
    candidates = []
    source_passages = transcript.passages
    for profile in spec.profiles:
        proposed = []
        if profile.strategy == "continuous":
            for i,p in enumerate(source_passages):
                if not matcher.matches_passage(p):
                    continue
                start = p.start
                # One preceding passage can supply context if it fits the duration budget.
                if i and p.end-source_passages[i-1].start <= profile.duration.maximum and not any(phrase(x,source_passages[i-1].text) for x in spec.conditions.exclude):
                    start = source_passages[i-1].start
                ending = p.end
                for tail in source_passages[i+1:]:
                    if tail.end-start > profile.duration.maximum or tail.start-ending > 10:
                        break
                    ending = tail.end
                    if ending-start >= profile.duration.target:
                        break
                if profile.duration.strict:
                    ending = start + profile.duration.target
                    if ending > source_info["duration"]:
                        continue
                if not profile.duration.minimum <= ending-start <= profile.duration.maximum:
                    continue
                c = Candidate(id="clip_001", profile=profile.name, title=title(p.text), segments=[Segment(start=start,end=ending,reason="Selected passage with adjacent context")],reason="Contains verified requested terms" if spec.mode == "TARGETED" else "Ranks well for explanation markers and transcript variety",narrative=["opening context","source discussion","source conclusion"],score=rank(" ".join(q.text for q in source_passages if start <= q.start < ending)))
                if matcher.validates_candidate(transcript,c):
                    proposed.append(c)
        else:
            groups = []
            for p in source_passages:
                if not matcher.matches_passage(p):
                    continue
                if groups and p.start-groups[-1].end <= 2 and p.end-groups[-1].start <= profile.duration.maximum:
                    groups[-1].end = p.end
                else:
                    groups.append(Segment(start=p.start,end=p.end,reason="Qualifying passage in chronological source order"))
            segments = []
            total = 0
            for s in groups:
                remaining = profile.duration.maximum-total
                if remaining <= 0:
                    break
                if s.end-s.start > remaining:
                    # Prefer a real passage boundary to a cut through speech.
                    ends = [p.end for p in source_passages if s.start < p.end <= s.start+remaining]
                    if not ends:
                        continue
                    s = s.model_copy(update={"end":max(ends)})
                segments.append(s)
                total += s.end-s.start
                if total >= profile.duration.target:
                    break
            if profile.duration.strict and abs(total-profile.duration.target)>0.05:
                warnings.append(f"{profile.name}: source passage boundaries cannot meet the strict compilation duration.")
            elif total >= profile.duration.minimum:
                c = Candidate(id="clip_001",profile=profile.name,title=title(" ".join(p.text for p in source_passages if matcher.matches_passage(p))),segments=segments,reason="Chronological compilation of verified qualifying passages",narrative=["source order; human coherence review required"],score=rank(" ".join(p.text for p in source_passages if matcher.matches_passage(p))))
                if matcher.validates_candidate(transcript,c):
                    proposed.append(c)
        chosen = []
        total = 0
        for c in sorted(proposed,key=lambda x:x.score,reverse=True):
            if any(sum(max(0,min(a.end,b.end)-max(a.start,b.start)) for a in c.segments for b in existing.segments) > 0.01 for existing in chosen):
                continue
            if profile.total_duration and total+c.duration > profile.total_duration+0.01:
                continue
            if c.score < 50:
                continue
            c.id = f"clip_{len(chosen)+1:03}"
            chosen.append(c)
            total += c.duration
            if len(chosen) >= (profile.count or 6):
                break
        if profile.count and len(chosen) < profile.count:
            warnings.append(f"{profile.name}: found {len(chosen)} qualifying outputs of {profile.count} requested. No filler added.")
        candidates.extend(chosen)
    warnings.append("Deterministic director used. Ranking is a heuristic. AI editorial reasoning and human-calibrated quality are not available without a configured local model or Hermes plan.")
    return EditingPlan(instruction=spec.instruction,source=spec.source,fingerprint=identity,source_duration=source_info["duration"],mode=spec.mode,profiles=spec.profiles,candidates=candidates,director="deterministic",warnings=warnings,constraints={"paid_budget":0,"max_revisions":settings.revisions,"max_output_seconds":900})
