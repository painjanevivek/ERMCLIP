from collections import Counter
from pathlib import Path
import re

from .director import text_for
from .subtitles import stamp
from .util import atomic_text


STOP = set("the a an and or of to in is it that this you your we for with on as are be was i they have can will from not but how what why its at by about into then when does do did has had must should could would also each both one two three their them our these those more most some any all only same here there instead keep keeps make makes useful good clear complete simple".split())


def tag_length(tags):
    # YouTube counts commas and two quotation marks for every tag containing a space.
    return sum(len(t)+(2 if " " in t else 0) for t in tags)+max(0,len(tags)-1)


def tags_for(text, conditions):
    tokens = re.findall(r"[\w][\w+-]*",text.lower())
    counts = Counter(t for t in tokens if len(t)>2 and t not in STOP)
    relevant = [t for t in conditions.keywords if re.search(re.escape(t),text,re.I)]
    bigrams = Counter(" ".join(pair) for pair in zip(tokens,tokens[1:]) if all(len(t)>2 and t not in STOP for t in pair))
    # Prefer descriptive source phrases to isolated common words.
    terms = relevant + [term for term,_ in bigrams.most_common(8)] + [word for word,_ in counts.most_common(8)]
    result=[]
    for term in terms:
        term=term.replace(","," ").replace("#","").strip()[:80]
        if term and term.lower() not in [x.lower() for x in result] and tag_length(result+[term])<=500:
            result.append(term)
    return result


def write(base: Path,candidate,profile,spec,transcript,actual_duration,quality):
    text=text_for(transcript,candidate)
    tags=tags_for(text,spec.conditions)
    subject=candidate.title.strip().replace("\n"," ")[:90]
    alternatives=[subject[:70]+" — Explained", "A closer look at "+subject[:65], subject[:70]+" | Source highlights"]
    hashtags=" ".join("#"+re.sub(r"\W+","",t.title()) for t in tags[:3] if re.sub(r"\W+","",t))
    ranges="\n".join(f"- {stamp(s.start)} → {stamp(s.end)} ({s.end-s.start:.3f} seconds): {s.reason}" for s in candidate.segments)
    thumbnail_time=min(actual_duration/2,5)
    text=f"""# {subject}

## Recommended YouTube title
{subject}

## Three alternative titles
"""+"\n".join(f"- {t}" for t in alternatives)+f"""

## YouTube description
{text[:1200]}

Source: {Path(spec.source).name}. This edit preserves the cited source passages. Review the complete source and verify factual claims before publication.

## YouTube Studio Tags
{', '.join(tags)}

Count under YouTube API rules: {tag_length(tags)} / 500 characters. These are Tags-field values.

## Description hashtags
{hashtags}

## Search-related topic keywords
{'; '.join(tags)}

## Opening-hook suggestion
Use the opening source statement: {text[:160]}

## Thumbnail text
{' '.join(subject.split()[:6])}

## Suggested thumbnail frame
Output timestamp: {stamp(thumbnail_time)}. Saved file: {base.name}_thumbnail.jpg. Confirm that the frame represents the content.

## Suggested pinned comment
Which point from this discussion would you like explored further?

## Call-to-action suggestion
Watch the full source for more context.

## Suggested content category
Education (review for this source).

## Target audience
Viewers interested in {', '.join(tags[:4]) or subject}.

## Source filename
{Path(spec.source).name}

## Exact original source timestamps
{ranges}

## Output duration
{actual_duration:.3f} seconds ({stamp(actual_duration)})

## Aspect ratio and resolution
{profile.ratio}; {profile.width} × {profile.height}.

## Transcript
{text}

## Reason the segment was selected
{candidate.reason}

## Publishing and factual-verification notes
- Quality status: {quality['status']}.
- Metadata uses source words and deterministic suggestions. It has no external factual verification.
- Verify rights, names, quotations, factual claims, title fit, and thumbnail fit before publishing.
- Do not publish a rejected output. Review outputs marked review_required.
- ERMCLIP does not publish to YouTube.
"""
    atomic_text(base.with_suffix(".md"),text)
    return tags
