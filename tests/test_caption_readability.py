import pytest
from ermclip.subtitles import Cue, smooth_readability


def test_dense_captions_borrow_time_without_dropping_words_or_overlapping():
    pytest.importorskip('scipy')
    cues=[Cue(0,1,'Hello',[(0,1,'Hello')]),
          Cue(1,1.4,'going to make',[(1,1.1,'going'),(1.1,1.2,'to'),(1.2,1.4,'make')]),
          Cue(1.4,2.4,'more',[(1.4,2.4,'more')])]
    original=[(c.start,c.end,c.text,list(c.words)) for c in cues]
    smooth_readability(cues,0,2.4)
    assert len(cues[1].text)/(cues[1].end-cues[1].start)<28
    for c,(a,b,text,words) in zip(cues,original):
        assert abs(c.start-a)<=.150001 and abs(c.end-b)<=.150001
        assert c.text==text and c.words==words
        assert 0<=c.start<c.end<=2.4
    assert all(a.end<=b.start+.000001 for a,b in zip(cues,cues[1:]))


def test_impossible_reading_speed_stays_inside_cut_and_remains_visible():
    pytest.importorskip('scipy')
    c=Cue(0,.2,'An exceptionally long word',[(0,.2,'word')])
    smooth_readability([c],0,.2)
    assert c.start==0 and c.end==.2
    assert len(c.text)/(c.end-c.start)>28
