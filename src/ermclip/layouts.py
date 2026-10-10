"""Portrait podcast layouts. Video and graphics use the same export timeline."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import tempfile


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int
    top: int
    caption_y: int


def viewport(profile):
    w, h = profile.width, profile.height
    if profile.layout.preset == "reference_window":
        # Measured reference: source picture runs from y=520 to y=1400 at 1080p.
        top = round(h * (520/1920) / 2) * 2
        height = round(h * (880/1920) / 2) * 2
        return Viewport(w, height, top, top + round(height*.87))
    if profile.layout.preset == "podcast_hero":
        top = round(h*.24/2)*2
        height = round((h-top-h*.08)/2)*2
        return Viewport(w, height, top, top + round(height*.88))
    return Viewport(w, h, 0, h-round(h*.13))


def body_profile(profile):
    box = viewport(profile)
    # Internal viewport geometry is separate from the validated output canvas.
    return profile.model_copy(update={"width":box.width,"height":box.height})


def frame_graph(graph, profile):
    if profile.layout.preset == "plain":
        return graph
    box = viewport(profile)
    graph = re.sub(r"\[v\]$", "[body]", graph)
    # Padding reserves a header. It never covers the speaker with title graphics.
    return graph + f";[body]pad={profile.width}:{profile.height}:0:{box.top}:color=black,setsar=1[v]"


@lru_cache(maxsize=256)
def _extent(text, font, bold):
    """Measure the export engine itself, including its actual font fallback."""
    import cv2
    import numpy as np
    from .util import run
    safe=re.sub(r"[{}\\\r\n]", "", text)
    with tempfile.TemporaryDirectory(prefix='ermclip-title-') as directory:
        folder=Path(directory)
        ass=f'''[Script Info]
ScriptType: v4.00+
PlayResX: 8192
PlayResY: 128
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Metric,{font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{-1 if bold else 0},0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Metric,,0,0,0,,{{\\an7\\pos(0,0)\\q2}}{safe}
'''
        (folder/'metric.ass').write_text(ass,encoding='utf-8')
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=8192x128:r=1:d=1',
            '-vf','ass=metric.ass','-frames:v','1','-threads','1','-update','1','metric.png'],cwd=folder,timeout=20)
        frame=cv2.imread(str(folder/'metric.png'),cv2.IMREAD_GRAYSCALE)
        if frame is None: raise RuntimeError('Cannot measure the title')
        ys,xs=np.where(frame>40)
        return (int(xs.max())+1,int(ys.min()),int(ys.max())+1) if len(xs) else (0,0,0)


def _width(text, font, size, bold=True):
    if not text: return 0
    # The sentinel preserves spaces, which have an advance but no visible pixels.
    return (_extent(text+'|',font,bold)[0]-_extent('|',font,bold)[0])*size/64


def _fit_lines(text, font, size, maximum, max_lines):
    words = text.split()
    # Fit without dropping text. Extremely long headlines shrink to the safe box.
    while True:
        if max_lines==2 and _width(text,font,size)>maximum:
            choices=[]
            for split in range(1,len(words)):
                left,right=" ".join(words[:split])," ".join(words[split:])
                lw,rw=_width(left,font,size),_width(right,font,size)
                if max(lw,rw)<=maximum:
                    choices.append((max(lw,rw)+abs(lw-rw)*.2,[left,right]))
            if choices:
                return min(choices,key=lambda c:c[0])[1],size
        lines = []; line = ""
        for word in words:
            trial = (line+" "+word).strip()
            if line and _width(trial,font,size)>maximum:
                lines.append(line); line=word
            else:
                line=trial
        if line: lines.append(line)
        if len(lines)<=max_lines and all(_width(line,font,size)<=maximum for line in lines):
            return lines,size
        size *= .94
        if size < 3:
            raise ValueError("Headline cannot fit the safe title area")


def title_events(profile, candidate, stamp, escape):
    """Create title events independently of the optional speech-caption burn."""
    if profile.layout.preset == "plain":
        return []
    w,h = profile.width,profile.height
    unit = w/1080
    box = viewport(profile)
    hero = profile.layout.preset == "podcast_hero"
    title = escape(profile.layout.headline or candidate.title)
    if not hero: title=title.upper()
    font = "Arial" if hero else "Impact"
    lines,size = _fit_lines(title,font,(100 if hero else 76)*unit,w*.87,2 if hero else 1)
    line_height = size*1.15
    credit = escape(profile.layout.credit or "")
    total = line_height*len(lines)+(58*unit if credit else 0)
    top = h*.055 if hero else box.top-total-24*unit
    end = stamp(candidate.duration,True)
    events=[]
    def emit(layer,body):
        events.append(f"Dialogue: {layer},0:00:00.00,{end},Title,,0,0,0,,{body}")
    highlight = escape(profile.layout.highlight or "")
    if hero and not highlight and profile.layout.auto_highlight:
        tokens = re.findall(r"[\w'-]+", title)
        # One actual title word; never add a claim or change the headline.
        highlight = max(tokens, key=len, default='')
    if hero:
        fade_height=200*unit
        for step in range(64):
            y0=round(fade_height*step/64); y1=round(fade_height*(step+1)/64)
            if y1==y0: continue
            y=box.top+box.height-round(fade_height)+y0
            alpha=round(255*(1-(step+1)/64))
            emit(0,f"{{\\an7\\pos(0,{y:.2f})\\p1\\bord0\\shad0\\1c&H00000000&\\alpha&H{alpha:02X}&}}m 0 0 l {w} 0 l {w} {y1-y0} l 0 {y1-y0}{{\\p0}}")
    for i,line in enumerate(lines):
        x=(w-_width(line,font,size))/2; y=top+i*line_height
        inline=line
        match=re.search(re.escape(highlight),line,re.I) if hero and highlight else None
        if match:
            before, marked, after=line[:match.start()],line[match.start():match.end()],line[match.end():]
            bx=x+_width(before,font,size); bw=_width(marked,font,size)
            pad=6*unit
            _,glyph_top,glyph_bottom=_extent(marked,font,True)
            by=y+glyph_top*size/64-pad; bh=(glyph_bottom-glyph_top)*size/64+2*pad
            emit(2,f"{{\\an7\\pos({bx-pad:.2f},{by:.2f})\\p1\\bord0\\shad0\\1c&H0035DFFF&\\alpha&H00&}}m 0 0 l {bw+2*pad:.2f} 0 l {bw+2*pad:.2f} {bh:.2f} l 0 {bh:.2f}{{\\p0}}")
            inline=before+"{\\1c&H00000000&}"+marked+"{\\1c&H00FFFFFF&}"+after
        color="FFFFFF" if hero else "35DFFF"
        emit(3,f"{{\\an8\\pos({w/2:.2f},{y:.2f})\\fn{font}\\fs{size:.2f}\\b1\\i0\\fscx100\\fscy100\\fsp0\\bord0\\shad0\\1c&H00{color}&\\alpha&H00&}}"+inline)
    if credit:
        credit_size=32*unit
        credit_size=min(credit_size,credit_size*(w*.84)/max(1,_width(credit,'Arial',credit_size,False)))
        credit=re.sub(r"(?<=EP )\d+",lambda m:"{\\1c&H0035DFFF&}"+m[0]+"{\\1c&H00FFFFFF&}",credit)
        emit(3,f"{{\\an8\\pos({w/2:.2f},{top+line_height*len(lines)+20*unit:.2f})\\fnArial\\fs{credit_size:.2f}\\b0\\i0\\fscx100\\fscy100\\fsp0\\bord0\\shad0\\1c&H00FFFFFF&\\alpha&H00&}}"+credit)
    return events
