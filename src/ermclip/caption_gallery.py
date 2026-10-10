"""Build a local preset picker from frames rendered by the export engine."""
import html
import json
from pathlib import Path

from .caption_styles import STYLES, catalog
from .models import Candidate, Duration, Passage, Profile, Segment, Transcript, Word
from .subtitles import write
from .util import atomic_json, atomic_text, run


def build(folder: Path):
    import cv2
    import numpy as np
    folder.mkdir(parents=True, exist_ok=True)
    cards=[]
    images=[]
    for key, look in STYLES.items():
        text='Elevate' if look.max_words==1 else 'Elevate every video with captions that pop'
        profile=Profile(name='preview',ratio='1:1',width=1080,height=1080,duration=Duration(target=3,minimum=1,maximum=3))
        profile.captions.preset=key
        profile.captions.position='middle'
        profile.captions.size=140 if look.max_words==1 else 92
        profile.captions.max_chars=24
        words=text.split()
        # This is labelled preview text, not a transcript of real footage.
        passage=Passage(start=0,end=3,text=text,words=[Word(start=i*0.1,end=i*0.1+0.09,text=w) for i,w in enumerate(words[:look.max_words])])
        transcript=Transcript(engine='style-preview',passages=[passage])
        candidate=Candidate(id='clip_001',profile=profile.name,title='Style preview',reason='Preview typography',segments=[Segment(start=0,end=3,reason='Sample text')])
        ass,_=write(transcript,candidate,profile,folder/key)
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=c=0xf4f5f6:s=1080x1080:r=1:d=2','-vf',f'ass={ass.name},scale=480:480','-frames:v','1','-update','1',f'{key}.png'],cwd=folder,timeout=60)
        preview=cv2.imread(str(folder/(key+'.png')))
        tile=np.full((370,320,3),255,np.uint8)
        tile[:320]=cv2.resize(preview,(320,320))
        label=look.name
        (width,_),_=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,0.62,1)
        cv2.putText(tile,label,(max(5,(320-width)//2),350),cv2.FONT_HERSHEY_SIMPLEX,0.62,(70,70,70),1,cv2.LINE_AA)
        images.append(tile)
        cards.append(f'<button class="card" data-id="{key}" aria-pressed="false"><img src="{key}.png" alt="{html.escape(look.description)}"><strong>{html.escape(look.name)}</strong><span>{html.escape(look.description)}</span></button>')
    sheet_images=images+[np.full_like(images[0],255) for _ in range((-len(images))%4)]
    sheet=np.vstack([np.hstack(sheet_images[i:i+4]) for i in range(0,len(sheet_images),4)])
    cv2.imwrite(str(folder/'caption-styles.jpg'),sheet,[cv2.IMWRITE_JPEG_QUALITY,94])
    atomic_json(folder/'styles.json',catalog())
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ERMCLIP | Caption styles</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f7f7f5;color:#202420;font-family:Segoe UI,Arial,sans-serif}main{max-width:1200px;margin:auto;padding:48px 28px}header{max-width:800px;margin-bottom:30px}small{letter-spacing:.15em;font-weight:700}h1{font-size:40px;line-height:1.1;margin:14px 0}p{color:#5e655e;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}.card{font:inherit;text-align:left;padding:0 0 16px;background:white;border:2px solid transparent;border-radius:16px;overflow:hidden;cursor:pointer}.card:hover{border-color:#afbaad}.card[aria-pressed=true]{border-color:#244f38;box-shadow:0 0 0 2px #244f38}.card img{display:block;width:100%;aspect-ratio:1;object-fit:contain}.card strong,.card span{display:block;margin:12px 16px 0}.card span{font-size:13px;line-height:1.4;color:#5e655e}.selection{position:sticky;bottom:12px;background:#202a23;color:white;padding:18px 22px;border-radius:12px;margin-top:24px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}.selection code{background:#344039;padding:8px;user-select:all}a.action{background:#d8f7ab;color:#172315;padding:12px 18px;border-radius:7px;text-decoration:none;font-weight:600}.note{font-size:13px}button:focus-visible,a:focus-visible{outline:3px solid #4e8044;outline-offset:3px}@media(max-width:850px){.grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.grid{grid-template-columns:repeat(2,1fr)}main{padding:24px 14px}h1{font-size:30px}}</style>
<main><header><small>ERMCLIP / LOCAL EDITOR</small><h1>Give every word a style.</h1><p>Choose from 25 looks based on your references. These previews use the same caption renderer as the final video. Select a card, then save its output profile.</p><p class="note">The two unnamed references are called Forest Notes and Retro Serif. Preview wording is sample text. Fonts use the families installed on this computer.</p></header><fieldset><legend>Video layout</legend><label>Layout <select id="layout"><option value="plain">Full canvas</option><option value="reference_window">Reference speaker window</option><option value="podcast_hero">Thumbnail hero</option></select></label> <label>Headline <input id="headline" maxlength="100" placeholder="Use the selected clip title"></label> <label>Highlight words <input id="highlight" maxlength="40" placeholder="Hero layout only"></label> <label>Episode credit <input id="credit" maxlength="100" placeholder="Optional"></label><p class="note">Reference layouts use a black 9:16 canvas. They reserve a title area and place captions inside the speaker window. Headline and credit are user text. Check them before export.</p></fieldset><div class="grid">'''+''.join(cards)+'''</div><div class="selection"><label><input id="podcast" type="checkbox"> Podcast: follow the speaker</label><strong id="selected">Highlighter selected</strong><code id="command">--caption-style highlighter</code><a class="action" id="download" download="caption-profile.json">Save profile</a></div><p class="note">Use the saved profile with scripts/ermclip.ps1 submit VIDEO --profile caption-profile.json. To restyle an existing job, submit the same source with --caption-style STYLE --force. Analysis stays cached. Podcast requests also enable speaker framing automatically. All files and processing stay local.</p></main>
<script>let previous;const cards=[...document.querySelectorAll('.card')];function current(){return cards.find(c=>c.getAttribute('aria-pressed')==='true')}function select(card){cards.forEach(c=>c.setAttribute('aria-pressed',String(c===card)));const id=card.dataset.id;document.querySelector('#selected').textContent=card.querySelector('strong').textContent+' selected';const podcast=document.querySelector('#podcast').checked;const layout=document.querySelector('#layout').value;document.querySelector('#command').textContent=layout==='plain'?'--caption-style '+id+(podcast?' --podcast':''):'--profile caption-profile.json'+(podcast?' --podcast':'');const profile={name:'shorts_9x16',ratio:'9:16',width:1080,height:1920,framing:podcast?'speaker':'pad',duration:{target:45,minimum:20,maximum:60},count:1,captions:{preset:id,size:52},inherit_podcast_style:false,layout:{preset:layout,auto_highlight:layout==='podcast_hero'}};if(layout!=='plain'){profile.captions.max_chars=24;for(const key of ['headline','highlight','credit']){const value=document.querySelector('#'+key).value.trim();if(value)profile.layout[key]=value}}if(previous)URL.revokeObjectURL(previous);previous=URL.createObjectURL(new Blob([JSON.stringify(profile,null,2)],{type:'application/json'}));document.querySelector('#download').href=previous}cards.forEach(c=>c.addEventListener('click',()=>select(c)));document.querySelector('#podcast').addEventListener('change',()=>{if(document.querySelector('#podcast').checked){document.querySelector('#layout').value='podcast_hero';select(cards.find(c=>c.dataset.id==='short_yellow'))}else select(current())});document.querySelector('#layout').addEventListener('change',()=>{if(document.querySelector('#layout').value!=='plain'){document.querySelector('#podcast').checked=true;select(cards.find(c=>c.dataset.id==='short_yellow'))}else select(current())});for(const key of ['headline','highlight','credit'])document.querySelector('#'+key).addEventListener('input',()=>select(current()));select(cards.find(c=>c.dataset.id==='highlighter'));</script></html>'''
    atomic_text(folder/'index.html',page)
    return {'gallery':str(folder/'index.html'),'contact_sheet':str(folder/'caption-styles.jpg'),'styles':len(STYLES)}
