"""Persist podcast defaults and update the existing local picker."""
from ermclip.config import load
from ermclip.util import atomic_json

s=load(); s.max_model_calls=40
atomic_json(s.path/'config/local.json',s.model_dump())
old="document.querySelector('#podcast').addEventListener('change',()=>select(current()));"
new="document.querySelector('#podcast').addEventListener('change',()=>{if(document.querySelector('#podcast').checked){document.querySelector('#layout').value='podcast_hero';select(cards.find(c=>c.dataset.id==='short_yellow'))}else select(current())});"
for p in [s.path/'src/ermclip/caption_gallery.py',s.path/'output/caption-gallery/index.html']:
    text=p.read_text(encoding='utf-8')
    text=text.replace(old,new)
    text=text.replace("layout:{preset:layout}}", "inherit_podcast_style:false,layout:{preset:layout,auto_highlight:layout==='podcast_hero'}}")
    p.write_text(text,encoding='utf-8')
print('Podcast defaults saved. Explicit picker profiles retain their selected layout.')
