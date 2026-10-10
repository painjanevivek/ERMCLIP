from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .models import Candidate, Passage, Profile, Transcript
from .caption_styles import STYLES
from .util import atomic_text


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[tuple[float,float,str]]


def smooth_readability(cues, start, end, skew=.15):
    """Borrow bounded display time, retaining every word and its ASR timing."""
    if not cues: return
    try:
        import numpy as np
        from scipy.optimize import linprog
    except ImportError:
        return  # Optional speaker dependencies; quality still flags fast cues.
    n=len(cues); count=5*n
    costs=np.zeros(count); costs[2*n:3*n]=100; costs[3*n:]=1
    bounds=[]
    for cue in cues: bounds.append((max(start,cue.start-skew),min(end,cue.start+skew)))
    for cue in cues: bounds.append((max(start,cue.end-skew),min(end,cue.end+skew)))
    bounds.extend([(0,None)]*(3*n))
    rows=[]; limits=[]
    def row(values,limit):
        r=np.zeros(count)
        for index,value in values: r[index]=value
        rows.append(r); limits.append(limit)
    for i,cue in enumerate(cues):
        row([(i,1),(n+i,-1),(2*n+i,-1)],-len(cue.text)/27.5-.001)
        row([(i,1),(n+i,-1)],-min(.25,cue.end-cue.start))
        if i+1<n: row([(n+i,1),(i+1,-1)],0)
        row([(i,1),(3*n+i,-1)],cue.start)
        row([(i,-1),(3*n+i,-1)],-cue.start)
        row([(n+i,1),(4*n+i,-1)],cue.end)
        row([(n+i,-1),(4*n+i,-1)],-cue.end)
    result=linprog(costs,A_ub=np.asarray(rows),b_ub=np.asarray(limits),bounds=bounds,method='highs')
    if result.success:
        for i,cue in enumerate(cues): cue.start=float(result.x[i]); cue.end=float(result.x[n+i])


def timeline(transcript: Transcript, candidate: Candidate, max_chars=36, max_words=None, join_passages=False):
    cues = []
    offset = 0.0
    for s in candidate.segments:
        cut_cue_start = len(cues)
        passages=transcript.passages
        if join_passages:
            local=[p for p in passages if p.start<s.end and p.end>s.start]
            if local and all(p.words for p in local):
                words=[w for p in local for w in p.words if w.start>=s.start-.001 and w.end<=s.end+.001]
                passages=[Passage(start=s.start,end=s.end,text=" ".join(w.text.strip() for w in words),words=words)]
        for p in passages:
            if p.end <= s.start or p.start >= s.end:
                continue
            aligned = [(max(w.start,s.start)-s.start+offset,min(w.end,s.end)-s.start+offset,w.text.strip()) for w in p.words if w.start >= s.start-0.001 and w.end <= s.end+0.001]
            if aligned:
                group = []
                groups = []
                for word in aligned:
                    if group and (len(" ".join(x[2] for x in group))+len(word[2])+1 > max_chars or word[1]-group[0][0]>4 or word[0]-group[-1][1]>.7 or (max_words and len(' '.join(x[2] for x in group+[word]).split())>max_words)):
                        groups.append(group)
                        group = []
                    group.append(word)
                if group:
                    groups.append(group)
                # Avoid an unreadable tail such as one word displayed for 0.16s.
                # Move already-aligned words, without changing their timestamps,
                # style word limits, text limits, or the selected speech.
                for i in range(len(groups)-1,0,-1):
                    tail, previous = groups[i], groups[i-1]
                    while len(previous)>1 and (tail[-1][1]-tail[0][0]<.5 or len(" ".join(w[2] for w in tail))/max(.01,tail[-1][1]-tail[0][0])>28):
                        proposed=[previous[-1]]+tail
                        if (max_words and len(' '.join(w[2] for w in proposed).split())>max_words) or len(" ".join(w[2] for w in proposed))>max_chars or previous[-2][1]-previous[0][0]<.5:
                            break
                        tail.insert(0,previous.pop())
                cues.extend(Cue(g[0][0],g[-1][1]," ".join(x[2] for x in g),g) for g in groups)
            elif not p.words:
                cues.append(Cue(max(p.start,s.start)-s.start+offset,min(p.end,s.end)-s.start+offset,p.text,[]))
        if max_words != 1:
            for i in range(cut_cue_start,len(cues)):
                cue=cues[i]
                if cue.words:
                    next_start=cues[i+1].start if i+1<len(cues) else offset+s.end-s.start
                    cue.end=min(next_start,offset+s.end-s.start,cue.end+.15)
        if join_passages and max_words != 1:
            smooth_readability(cues[cut_cue_start:],offset,offset+s.end-s.start)
        offset += s.end-s.start
    return cues


def stamp(t, ass=False):
    units = max(0,round(t*(100 if ass else 1000)))
    divisor = 100 if ass else 1000
    whole,fraction = divmod(units,divisor)
    h,remainder = divmod(whole,3600)
    m,s = divmod(remainder,60)
    return f"{h}:{m:02}:{s:02}.{fraction:02}" if ass else f"{h:02}:{m:02}:{s:02},{fraction:03}"


def escape(text):
    # Source content cannot inject ASS drawing or override instructions.
    return re.sub(r"[{}\\]", "", text).replace("\n", " ").replace("\r", " ")


def write(transcript: Transcript, candidate: Candidate, profile: Profile, base: Path):
    look = STYLES.get(profile.captions.preset)
    cues = timeline(transcript,candidate,profile.captions.max_chars,look.max_words if look else None,join_passages=profile.captions.preset=='short_yellow')
    if profile.captions.srt:
        atomic_text(base.with_suffix(".srt"), "\n".join(f"{i}\n{stamp(c.start)} --> {stamp(c.end)}\n{c.text}\n" for i,c in enumerate(cues,1)))
    size = max(12,round(profile.captions.size*profile.width/1080))
    alignment = {"bottom":2,"middle":5,"top":8}[profile.captions.position]
    margin = round(profile.height*(0.13 if profile.height>profile.width else 0.07))
    safe_lr = max(round(profile.width*0.07),20)
    from .layouts import viewport, title_events
    layout_position = ""
    if profile.layout.preset != "plain":
        box = viewport(profile)
        layout_position = f"{{\\an5\\pos({profile.width/2:.2f},{box.caption_y:.2f})}}"
    def ass_color(value):
        return "&H00"+value[4:6]+value[2:4]+value[0:2]
    if look:
        font=profile.captions.font if profile.captions.font != 'Arial' else look.font
        size=max(12,round(profile.captions.size*look.scale*profile.width/1080))
        unit=profile.width/1080
        color=profile.captions.color if profile.captions.color != 'FFFFFF' else look.color
        style=f"Style: Default,{font},{size},{ass_color(color)},{ass_color(color)},{ass_color(look.outline_color)},{ass_color(look.shadow_color)},{-1 if look.bold else 0},{-1 if look.italic else 0},0,0,100,100,{look.spacing*unit:.2f},0,{3 if look.box else 1},{look.outline*unit:.2f},{look.shadow*unit:.2f},{alignment},{safe_lr},{safe_lr},{margin},1"
    else:
        style=f"Style: Default,{profile.captions.font},{size},{ass_color(profile.captions.highlight if profile.captions.preset != 'plain' else profile.captions.color)},{ass_color(profile.captions.color)},&H00101010,&H88000000,-1,0,0,0,100,100,0,0,1,3,1,{alignment},{safe_lr},{safe_lr},{margin},1"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {profile.width}
PlayResY: {profile.height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}
Style: Title,Arial,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = title_events(profile,candidate,stamp,escape)
    for cue in cues:
        if look:
            if look.multicolor:
                colors=('FF5891','C39FFF','79D2A4')
                text=' '.join('{\\1c'+ass_color(colors[i%3])+'&}'+escape(word) for i,word in enumerate(cue.text.split()))
            else:
                text=escape(cue.text.upper() if look.uppercase else cue.text)
            if look.animation:
                text='{\\fscx94\\fscy94\\t(0,100,\\fscx100\\fscy100)}'+text
            if look.glow and profile.captions.burn:
                glow=layout_position+'{\\1c'+ass_color(look.color)+'&\\3c'+ass_color(look.color)+'&\\bord'+str(2*unit)+'\\blur'+str(look.glow*unit)+'\\alpha&H50&}'+text
                events.append(f"Dialogue: 0,{stamp(cue.start,True)},{stamp(cue.end,True)},Default,,0,0,0,,{glow}")
        elif cue.words and profile.captions.preset != "plain":
            # Karaoke timing includes gaps between words so highlights stay aligned.
            parts = []
            cursor = cue.start
            for start,end,text in cue.words:
                gap = max(0,round((start-cursor)*100))
                if gap:
                    parts.append("{\\k"+str(gap)+"}")
                parts.append("{\\kf"+str(max(1,round((end-start)*100)))+"}"+escape(text)+" ")
                cursor = end
            text = "".join(parts).strip()
        else:
            text = escape(cue.text)
        if profile.captions.preset == "pop":
            text = "{\\fscx92\\fscy92\\t(0,120,\\fscx100\\fscy100)}"+text
        if profile.captions.burn:
            events.append(f"Dialogue: 1,{stamp(cue.start,True)},{stamp(cue.end,True)},Default,,0,0,0,,{layout_position}{text}")
    ass = base.with_suffix(".ass")
    atomic_text(ass,header+"\n".join(events)+"\n")
    return ass,cues
