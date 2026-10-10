from pathlib import Path
from unittest.mock import patch
import cv2
import pytest
from pydantic import ValidationError

from ermclip.config import Settings
from ermclip.layouts import viewport
from ermclip.media import probe, render
from ermclip.models import Candidate, Layout, Profile, Segment, Transcript
from ermclip.subtitles import write
from ermclip.util import run


def test_portrait_layout_contract_and_caption_safe_area():
    p = Profile(layout=Layout(preset='reference_window'))
    v = viewport(p)
    assert v.top == 520 and v.height == 880
    assert v.top < v.caption_y < v.top+v.height
    with pytest.raises(ValidationError):
        Profile(ratio='16:9',width=1920,height=1080,layout=Layout(preset='podcast_hero'))
    with pytest.raises(ValidationError):
        Profile(layout=Layout(preset='podcast_hero',headline='Choose a game',highlight='not present'))


def test_reference_headline_balances_lines_and_uses_actual_font_metrics():
    from ermclip.layouts import _fit_lines
    lines,size=_fit_lines('Every Entrepreneur Will Relate','Arial',100,940,2)
    assert lines==['Every Entrepreneur','Will Relate']
    assert size==100


@pytest.mark.parametrize('preset', ['reference_window','podcast_hero'])
def test_encoded_layout_reserves_header_and_keeps_speaker_switches(tmp_path,preset):
    source = tmp_path/'source.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
        'color=red:s=640x360:r=30:d=2,drawbox=x=320:y=0:w=320:h=360:color=blue:t=fill',
        '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-threads','2','-c:a','aac',str(source)],timeout=30)
    p = Profile(width=540,height=960,framing='speaker',normalize_audio=False,
        layout=Layout(preset=preset,headline='A safe headline',credit='Example episode'))
    p.captions.burn=False  # Title remains visible when speech captions are off.
    candidate = Candidate(id='clip_001',profile=p.name,title='Title',reason='test',segments=[Segment(start=0,end=2,reason='test')])
    ass,cues = write(Transcript(engine='test',passages=[]),candidate,p,tmp_path/'clip')
    tracking={'source_start':0,'source_end':2,'points':[
        {'time':0,'center':.25,'fallback':False},
        {'time':1,'center':.75,'fallback':False}]}
    with patch('ermclip.speaker.analyse',return_value=tracking):
        result=render(source,probe(source),candidate,p,ass,tmp_path/'result.mp4',Settings(root=str(tmp_path),encoder='cpu'),{})
    assert abs(float(result['probe']['audio_stream']['duration'])-2)<.1
    assert (result['probe']['width'],result['probe']['height'])==(540,960)
    cap=cv2.VideoCapture(str(tmp_path/'result.mp4')); v=viewport(p)
    for t,index in ((.5,2),(1.5,0)):
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000); ok,frame=cap.read(); assert ok
        body=frame[v.top:v.top+v.height,100:440]
        assert body[:,:,index].mean()>body[:,:,(0 if index==2 else 2)].mean()+60
        assert frame[:v.top].max()>180  # Header is actually rendered.
        header=frame[:v.top]
        mask=(header[:,:,0]>180)&(header[:,:,1]>180)&(header[:,:,2]>180)
        ys,xs=__import__('numpy').where(mask)
        if preset=='podcast_hero':
            assert abs((xs.min()+xs.max())/2-270)<12
        assert frame[-30:].mean()<5  # The reserved footer stays black.
    cap.release()


def test_header_escapes_source_text_and_fits_long_title(tmp_path):
    p=Profile(layout=Layout(preset='podcast_hero',headline='A very long title '+('complete words '*5),credit=r'{\p1} credit'))
    p.captions.burn=False
    c=Candidate(id='clip_001',profile=p.name,title='x',reason='x',segments=[Segment(start=0,end=3,reason='x')])
    ass,_=write(Transcript(engine='test',passages=[]),c,p,tmp_path/'clip')
    text=ass.read_text()
    assert 'complete words' in text
    assert r'{\p1} credit' not in text
    assert 'Title,,' in text


def test_word_aligned_edit_requires_context_review_without_expanding_cut():
    from ermclip.models import JobSpec, Passage, Word
    from ermclip.quality import pre_render
    p=Profile(); spec=JobSpec(source='source.mp4',profiles=[p])
    c=Candidate(id='clip_001',profile=p.name,title='x',reason='x',segments=[Segment(start=1,end=2,reason='complete words')])
    transcript=Transcript(engine='test',passages=[Passage(start=0,end=3,text='Before. Complete sentence. After.',words=[
        Word(start=0,end=.8,text='Before.'),Word(start=1,end=1.4,text='Complete'),Word(start=1.4,end=2,text='sentence.'),Word(start=2.2,end=3,text='After.')])])
    class Matcher:
        def validates_candidate(self,*args): return True
    findings=pre_render(spec,c,p,transcript,{'duration':3},Matcher())
    assert any(f.code=='word_aligned_boundary' and f.severity=='review' for f in findings)
    assert not any(f.severity=='revision' for f in findings)
    c.segments[0].end=1.7
    assert any(f.code=='incomplete_statement' and f.severity=='revision' for f in pre_render(spec,c,p,transcript,{'duration':3},Matcher()))
    from ermclip.director import text_for
    c.segments[0].end=2
    assert text_for(transcript,c)=='Complete sentence.'


def test_reference_captions_join_asr_passages_without_losing_words(tmp_path):
    from ermclip.models import Passage, Word
    t=Transcript(engine='test',passages=[
        Passage(start=0,end=.6,text='Words will',words=[Word(start=0,end=.5,text='Words'),Word(start=.5,end=.6,text='will')]),
        Passage(start=.6,end=1.5,text='stay aligned.',words=[Word(start=.6,end=1,text='stay'),Word(start=1,end=1.5,text='aligned.')])])
    p=Profile(); p.captions.preset='short_yellow'
    c=Candidate(id='clip_001',profile=p.name,title='x',reason='x',segments=[Segment(start=0,end=1.5,reason='x')])
    ass,cues=write(t,c,p,tmp_path/'joined')
    assert ' '.join(c.text for c in cues)=='Words will stay aligned.'
    assert all(len(c.words)<=3 for c in cues)
    assert not any(c.text=='will' for c in cues)
