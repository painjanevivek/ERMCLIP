from types import SimpleNamespace
from ermclip.transcribe import aligned_words
from ermclip.models import Candidate, Passage, Segment, Transcript, Word
from ermclip.subtitles import timeline


def test_zero_duration_prefix_and_suffix_are_retained_without_fake_word_times():
    raw=[SimpleNamespace(start=1,end=1,word=' we'),SimpleNamespace(start=1,end=1.3,word=' are'),
         SimpleNamespace(start=1.3,end=1.3,word=' here')]
    words,merged=aligned_words(raw)
    assert merged and len(words)==1
    assert words[0].text==' we are here' and (words[0].start,words[0].end)==(1,1.3)


def test_shared_span_counts_real_words_in_short_caption_groups():
    t=Transcript(engine='fixture',passages=[Passage(start=0,end=2,text='Now we are ready.',words=[
        Word(start=0,end=.5,text='Now'),Word(start=.5,end=1,text=' we are'),Word(start=1,end=2,text=' ready.')])])
    c=Candidate(id='clip_001',profile='test',title='Test',reason='Test',segments=[Segment(start=0,end=2,reason='Test')])
    cues=timeline(t,c,24,3,join_passages=True)
    assert ' '.join(q.text for q in cues)=='Now we are ready.'
    assert all(len(q.text.split())<=3 for q in cues)
