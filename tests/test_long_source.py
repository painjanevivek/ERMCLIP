import pytest
from ermclip.long_source import chunks, proposal_candidate, Proposal, overlap, valid_windows
from ermclip.models import Candidate, Duration, Passage, Profile, Segment, Transcript, Word


def test_section_coverage_and_progress_with_long_rows():
    passages=[Passage(start=i*10,end=i*10+9,text='x'*150) for i in range(30)]
    windows=list(chunks(passages,limit=700,overlap_seconds=15))
    assert {i for a,b in windows for i in range(a,b)}==set(range(30))
    assert all(a<b for a,b in windows)
    assert all(a<c for (a,b),(c,d) in zip(windows,windows[1:]))


def test_proposal_cannot_invent_times_or_repeat_existing_clip():
    t=Transcript(engine='fixture',passages=[Passage(start=0,end=10,text='Hello.',words=[Word(start=.2,end=9.8,text='Hello.')]),Passage(start=10,end=20,text='End.')])
    profile=Profile(duration=Duration(target=20,minimum=15,maximum=25))
    p=Proposal(first=0,last=1,title='Example',reason='test')
    c=proposal_candidate(p,t,profile,(0,2))
    assert c.segments[0].start==.2 and c.segments[0].end==20
    with pytest.raises(ValueError): proposal_candidate(p,t,profile,(1,2))
    with pytest.raises(ValueError): proposal_candidate(p,t,profile,(0,2),[(5,6)])
    with pytest.raises(ValueError): proposal_candidate(p.model_copy(update={'last':0}),t,profile,(0,2))
    assert overlap(c,c)
    other=Candidate(id='clip_001',profile=profile.name,title='Other',segments=[Segment(start=20,end=40,reason='test')],reason='test')
    assert not overlap(c,other)


def test_model_window_choices_all_meet_duration_and_exclusion_limits():
    t=Transcript(engine='fixture',passages=[Passage(start=i*10,end=i*10+9,text=f'Statement {i}.') for i in range(12)])
    profile=Profile(duration=Duration(target=30,minimum=20,maximum=40))
    windows=valid_windows(t,profile,(0,12),[(40,50)])
    assert windows
    for key,(a,b,duration) in windows.items():
        c=proposal_candidate(Proposal(first=a,last=b,title='Test',reason='Test'),t,profile,(0,12),[(40,50)])
        assert key==f'{a}:{b}' and 20<=c.duration<=40
        assert round(c.duration,2)==duration
