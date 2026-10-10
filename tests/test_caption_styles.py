from pathlib import Path
import pytest
from pydantic import ValidationError

from ermclip.caption_styles import STYLES, catalog
from ermclip.models import Captions, Candidate, Passage, Profile, Segment, Transcript, Word
from ermclip.subtitles import write


def fixture():
    text=['Keep','the','whole','car','visible.']
    transcript=Transcript(engine='fixture',passages=[Passage(start=10,end=12.5,text=' '.join(text),words=[Word(start=10+i*.5,end=10.45+i*.5,text=t) for i,t in enumerate(text)])])
    candidate=Candidate(id='clip_001',profile='test',title='Car',reason='Test',segments=[Segment(start=10,end=12.5,reason='Test')])
    return transcript,candidate


@pytest.mark.parametrize('preset',list(STYLES))
def test_presets_use_bounded_source_timing_and_original_srt(preset,tmp_path):
    transcript,candidate=fixture()
    profile=Profile(name='test',captions=Captions(preset=preset))
    base=tmp_path/'clip'
    ass,cues=write(transcript,candidate,profile,base)
    assert cues and all(0<=c.start<c.end<=candidate.duration for c in cues)
    assert all(len(c.words)<=STYLES[preset].max_words for c in cues)
    assert 'Keep' in base.with_suffix('.srt').read_text()
    assert STYLES[preset].font in ass.read_text()
    assert 'PlayResX: 1080' in ass.read_text()
    if STYLES[preset].uppercase:
        assert 'KEEP' in ass.read_text() and 'Keep' in base.with_suffix('.srt').read_text()


def test_bad_preset_is_rejected():
    assert len(catalog())==25
    with pytest.raises(ValidationError): Captions(preset='invented')


def test_source_cannot_inject_ass_commands(tmp_path):
    transcript,candidate=fixture()
    transcript.passages[0].words[0].text=r'{\pos(0,0)}Keep'
    ass,_=write(transcript,candidate,Profile(name='test',captions=Captions(preset='eye_candy')),tmp_path/'safe')
    assert r'\pos(' not in ass.read_text()


def test_imported_srt_does_not_invent_word_timing(tmp_path):
    transcript,candidate=fixture()
    transcript.passages[0].words=[]
    ass,cues=write(transcript,candidate,Profile(name='test',captions=Captions(preset='bold_pop')),tmp_path/'srt')
    assert len(cues)==1 and not cues[0].words
    assert 'KEEP THE WHOLE CAR VISIBLE.' in ass.read_text()


def test_short_caption_tail_is_balanced_without_losing_aligned_words():
    from ermclip.subtitles import timeline
    words=[Word(start=0,end=.6,text='We'),Word(start=.6,end=1.2,text='can'),
           Word(start=1.2,end=1.8,text='start'),Word(start=1.8,end=1.95,text='now')]
    transcript=Transcript(engine='aligned',passages=[Passage(start=0,end=2,text='We can start now',words=words)])
    candidate=Candidate(id='clip_001',profile='test',title='test',reason='test',segments=[Segment(start=0,end=2,reason='test')])
    cues=timeline(transcript,candidate,max_chars=12,max_words=3)
    assert [w for c in cues for w in c.words]==[(w.start,w.end,w.text) for w in words]
    assert len(cues[-1].words)>1 and cues[-1].end-cues[-1].start>=.5
    assert all(c.end<=2 and len(c.text)<=12 and len(c.words)<=3 for c in cues)
    assert all(a.end<=b.start for a,b in zip(cues,cues[1:]))
