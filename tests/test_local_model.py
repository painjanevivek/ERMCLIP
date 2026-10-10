from pathlib import Path
import pytest
from pydantic import ValidationError

from ermclip.config import Settings
from ermclip.director import plan
from ermclip.models import Candidate, Conditions, Duration, JobSpec, Passage, Profile, Segment, Transcript


def test_managed_model_cannot_change_endpoint_or_alias():
    with pytest.raises(ValidationError):
        Settings(managed_local_model=True, local_llm_url="http://127.0.0.1:9999/v1", director_model="other")


def test_invalid_director_choice_gets_one_bounded_correction(settings):
    profile=Profile(duration=Duration(target=20,minimum=15,maximum=30),count=1)
    transcript=Transcript(engine="fixture",passages=[Passage(start=0,end=20,text="A complete context explanation.")])
    spec=JobSpec(source="fixture",profiles=[profile])
    class Model:
        enabled=True
        calls=0
        def json(self,role,payload,schema):
            self.calls+=1
            assert "words" not in payload["transcript"][0]
            if self.calls==1:
                return {"selections":[{"choice":"invented/window_9999","title":"bad","reason":"bad"}]}
            assert "source window" in payload["validation_error"]
            choice=schema["$defs"]["Selection"]["properties"]["choice"]["enum"][0]
            return {"selections":[{"choice":choice,"title":"valid","reason":"complete"}]}
    model=Model()
    result=plan(spec,transcript,{"duration":20},"hash",settings,settings.path/"cache",model,[])
    assert model.calls==2 and result.candidates[0].duration==20


def test_repeated_invalid_director_answer_fails_closed(settings):
    spec=JobSpec(source="fixture",mode="TARGETED",conditions=Conditions(keywords=["context"]))
    transcript=Transcript(engine="fixture",passages=[Passage(start=0,end=30,text="A valid context explanation.")])
    class Model:
        enabled=True
        calls=0
        def json(self,*args):
            self.calls+=1
            return {"selections":[{"choice":"NO_VALID_WINDOW","title":"bad match","reason":"test"}]}
    model=Model()
    with pytest.raises(ValueError,match="source window"):
        plan(spec,transcript,{"duration":30},"hash",settings,settings.path/"cache",model,[])
    assert model.calls==2


def test_verified_no_match_needs_no_model_call(settings):
    spec=JobSpec(source="fixture",mode="TARGETED",conditions=Conditions(keywords=["absent"]))
    transcript=Transcript(engine="fixture",passages=[Passage(start=0,end=30,text="A context explanation.")])
    class Model:
        enabled=True
        def json(self,*args):
            pytest.fail("Absent source material must not be invented by the model")
    result=plan(spec,transcript,{"duration":30},"hash",settings,settings.path/"cache",Model(),[])
    assert not result.candidates and result.director=="verified-constraints"


def test_long_transcript_still_uses_local_director_for_verified_tail(settings):
    passages=[Passage(start=i*10,end=i*10+9,text=('Ordinary unrelated workshop discussion. '*5)) for i in range(500)]
    passages[-2].text='The wheel widening solution keeps the car stable.'
    passages[-1].text='This complete wheel explanation ends with the test result.'
    transcript=Transcript(engine='long-fixture',passages=passages)
    profile=Profile(duration=Duration(target=19,minimum=15,maximum=30),count=1)
    spec=JobSpec(source='fixture',mode='TARGETED',conditions=Conditions(keywords=['wheel']),profiles=[profile])
    class Model:
        enabled=True
        calls=0
        def json(self,role,payload,schema):
            self.calls+=1
            assert len(__import__('json').dumps(payload))<=35000
            assert payload['coverage']['full_source_passages']==500
            choices=schema['$defs']['Selection']['properties']['choice']['enum']
            choice=next(c for c in choices if ': The wheel widening solution' in c)
            return {'selections':[{'choice':choice,'title':'Wheel solution','reason':'Verified complete explanation'}]}
    model=Model()
    result=plan(spec,transcript,{'duration':5000},'hash',settings,settings.path/'cache',model,[])
    assert model.calls==1 and result.director=='local-llm'
    assert result.candidates[0].segments[0].start==4980


def test_larger_director_reads_complete_source_and_corrects_excluded_indexes(settings):
    settings.director_model='ermclip-qwen35-9b'
    transcript=Transcript(engine='fixture',passages=[Passage(start=0,end=10,text='A sponsor pitch.'),Passage(start=10,end=20,text='An unrelated ending.'),Passage(start=20,end=30,text='The car width is the problem.'),Passage(start=30,end=40,text='Special permits provide the practical solution.')])
    profile=Profile(duration=Duration(target=20,minimum=15,maximum=30),count=1)
    spec=JobSpec(source='fixture',conditions=Conditions(exclude=['sponsor']),profiles=[profile])
    class Model:
        enabled=True
        calls=0
        def json(self,role,payload,schema):
            self.calls+=1
            assert len(payload['transcript'])==4
            assert payload['columns'][0]=='passage_index'
            if self.calls==1: start,end=0,1
            else:
                assert 'source conditions' in payload['validation_error']
                start,end=2,3
            return {'selections':[{'choice':f'{profile.name}/{start}:{end}','title':'Width solution','reason':'Actual source explanation'}]}
    model=Model()
    result=plan(spec,transcript,{'duration':40},'hash',settings,settings.path/'cache',model,[])
    assert result.director=='local-llm-full-transcript' and model.calls==2
    assert result.candidates[0].segments[0].start==20 and result.candidates[0].segments[0].end==40


def test_larger_director_rejects_invented_passage_indexes(settings):
    settings.director_model='ermclip-qwen35-9b'
    transcript=Transcript(engine='fixture',passages=[Passage(start=0,end=20,text='A complete source explanation.')])
    profile=Profile(duration=Duration(target=20,minimum=15,maximum=30),count=1)
    spec=JobSpec(source='fixture',profiles=[profile])
    class Model:
        enabled=True
        calls=0
        def json(self,role,payload,schema):
            self.calls+=1
            return {'selections':[{'choice':f'{profile.name}/0:9999','title':'bad','reason':'bad'}]}
    model=Model()
    with pytest.raises(ValueError): plan(spec,transcript,{'duration':20},'hash',settings,settings.path/'cache',model,[])
    assert model.calls==2
