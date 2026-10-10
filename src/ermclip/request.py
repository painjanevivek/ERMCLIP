"""Conservative standalone parsing. Hermes supplies JobSpec for complex requests."""
import re
from .models import Conditions, Duration, JobSpec, Profile, seconds
from .util import UnsupportedRequest


def source_context(spec: JobSpec, settings) -> JobSpec:
    """Use operator-supplied source types, never an inferred speaker identity."""
    from pathlib import Path
    known = any(Path(spec.source).resolve() == Path(p).resolve() for p in settings.podcast_sources)
    context = spec.instruction + ' ' + Path(spec.source).stem
    podcast = spec.podcast_mode == 'on' or (spec.podcast_mode == 'auto' and
        (known or bool(re.search(r'\b(podcasts?|interviews?|active speaker|person who is talking)\b', context, re.I))))
    if not podcast:
        return spec
    result = spec.model_copy(deep=True)
    result = JobSpec.model_validate(result.model_copy(update={'podcast_mode':'on'}).model_dump())
    preserve = bool(re.search(r'\b(keep|preserve|show)\b.{0,30}\b(full|whole|original)\s+(frame|video)\b', spec.instruction, re.I))
    for i, p in enumerate(result.profiles):
        if preserve or not p.inherit_podcast_style or p.layout.preset != 'plain' or p.ratio != '9:16' or p.framing == 'original' or p.captions.position != 'bottom':
            continue
        captions = p.captions.model_copy(deep=True)
        # Keep custom caption choices. The CLI applies its explicit override after this step.
        if captions.preset in {'highlight', *(d.captions.preset for d in settings.defaults)}:
            captions.preset = settings.podcast_caption_preset
            captions.max_chars = 24
        result.profiles[i] = Profile.model_validate(p.model_copy(update={
            'layout':settings.podcast_layout.model_copy(deep=True), 'captions':captions}).model_dump())
    return result


def interpret(source: str, instruction: str, defaults: list[Profile]) -> JobSpec:
    profiles = [p.model_copy(deep=True) for p in defaults]
    text = instruction.lower()
    selection_text = re.sub(r"\b(active speaker|center (?:the )?speaker|follow (?:the )?speaker|speaker (?:centered|centred|framing|tracking))\b", "", text)
    if re.search(r"\b(guest|speaker|robot|falls?|balance|scene where|only.*predictions)\b", selection_text):
        raise UnsupportedRequest("Speaker or visual instructions require a structured Hermes request and verified source annotations")
    ratio_match = re.search(r"\b(\d{1,4}):(\d{1,4})\b", text)
    dimensions = re.search(r"\b(\d{2,4})\s*[x×]\s*(\d{2,4})\b", text)
    resolution = re.search(r"\b(720p|1080p|1440p|4k)\b", text)
    count_match = re.search(r"\b(\d+)\s+(?:shorts|clips|videos)\b", text)
    word_count = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:shorts|clips|videos|\d+[- ]minute|\d+[- ]second)", text)
    if word_count:
        count_match_value = {word:i for i,word in enumerate("one two three four five six seven eight nine ten".split(),1)}[word_count[1]]
    elif "one " in text:
        count_match_value = 1
    else:
        count_match_value = int(count_match[1]) if count_match else None
    range_match = re.search(r"between\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)\s*(seconds?|minutes?)", text)
    duration_match = re.search(r"\b(\d+(?:\.\d+)?)\s*[- ]?(seconds?|minutes?)\b", text)
    clock = re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", text)
    for index, template in enumerate(profiles):
        # Build related dimensions together, then validate the complete profile.
        p = template.model_copy(deep=True)
        if range_match:
            factor = 60 if range_match[3].startswith("minute") else 1
            lo, hi = seconds(float(range_match[1])*factor), seconds(float(range_match[2])*factor)
            p.duration = Duration(target=(lo+hi)/2, minimum=lo, maximum=hi)
        elif duration_match or clock:
            target = seconds(clock[0]) if clock else seconds(float(duration_match[1]) * (60 if duration_match[2].startswith("minute") else 1))
            strict = bool(re.search(r"\b(exact|exactly|strict)\b", text))
            p.duration = Duration(target=target, minimum=target if strict else max(1, target*0.8), maximum=target, strict=strict)
        if count_match_value:
            p.count = count_match_value
        if "compilation" in text or "best-of" in text:
            p.strategy = "compilation"
        new_ratio = f"{int(ratio_match[1])}:{int(ratio_match[2])}" if ratio_match and not clock else p.ratio
        width,height=p.width,p.height
        if dimensions:
            width,height = int(dimensions[1]), int(dimensions[2])
            if not ratio_match:
                import math
                divisor = math.gcd(width,height)
                new_ratio = f"{width//divisor}:{height//divisor}"
        elif ratio_match or resolution:
            a, b = map(int, new_ratio.split(":"))
            short = {"720p":720, "1080p":1080, "1440p":1440, "4k":2160}.get(resolution[1] if resolution else "1080p", 1080)
            if a < b:
                width,height = short, round(short*b/a/2)*2
            else:
                width,height = round(short*a/b/2)*2, short
        if "without subtitles" in text or "subtitle-free" in text:
            p.captions.burn = False
        profiles[index] = Profile.model_validate(p.model_copy(update={"ratio":new_ratio,"width":width,"height":height}).model_dump())
    conditions = Conditions()
    exclusion = re.search(r"\b(?:excluding|exclude|without mentioning)\s+(.+?)(?:[.!]|$)", instruction, re.I)
    if exclusion:
        conditions.exclude = [x.strip() for x in re.split(r",|\bor\b|\band\b", exclusion[1]) if x.strip()]
    target = re.search(r"(?:discussing|discussions? about|related to|about)\s+(.+?)(?:\s+only|\s+excluding|[.!]|$)", instruction, re.I)
    if not target:
        target = re.search(r"find\s+(?:moments\s+(?:on|with)\s+)?(.+?)(?:\s+only|\s+excluding|[.!]|$)", instruction, re.I)
    if target:
        value = re.sub(r"[- ]related discussions.*$", "", target[1], flags=re.I).strip()
        if re.search(r"\b(semantic|topic)\b", text):
            conditions.topics = [value]
        else:
            conditions.keywords = [x.strip(' "') for x in re.split(r",|\bor\b|\band\b", value) if x.strip()]
            conditions.all_keywords = " and " in value.lower() and " or " not in value.lower()
    elif re.search(r"\b[A-Z][A-Z0-9]+-related", instruction):
        conditions.keywords = [re.search(r"\b([A-Z][A-Z0-9]+)-related", instruction)[1]]
    if not target and not conditions.keywords and not re.search(r"\b(best|interesting|clips?|videos?|shorts|compilation|highlight|funniest)\b", text):
        raise UnsupportedRequest("Use a structured job for this instruction. The local parser cannot safely interpret it.")
    return JobSpec(source=source, instruction=instruction, mode="TARGETED" if conditions.keywords or conditions.topics else "AUTO", conditions=conditions, profiles=profiles)
