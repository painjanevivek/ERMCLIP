"""Apply source-bound editorial revisions to the full-episode Director draft."""
import json
import shutil
from ermclip.config import load
from ermclip.models import Candidate, Duration, EditingPlan, JobSpec, Segment, Transcript
from ermclip.director import text_for
from ermclip.request import source_context
from ermclip.util import atomic_json

s=load(); folder=s.path/'output/raj-shamani-batch'
plan_path=folder/'editing-plan.json'; draft=folder/'director-draft.json'
if not draft.exists(): shutil.copyfile(plan_path,draft)
plan=EditingPlan.model_validate_json(draft.read_text(encoding='utf-8'))
spec=JobSpec.model_validate_json((folder/'request.json').read_text(encoding='utf-8'))
t=Transcript.model_validate_json((folder/'full-transcript.json').read_text(encoding='utf-8'))
selections=[
    ('Learn From Experienced Advisors',2051.89,2094.85,'Keep the timing question, the advisor-network explanation and its complete CTO-advisor example. Remove the later ambiguous ASR phrase and the next unfinished lesson.'),
    ('The Advantage AI Startups Can Use',3292.76,3363.32,'Keep the full incumbent-versus-startup comparison, the agility explanation, and the explicit uncertainty before its conclusion. Do not promise that startups always win.'),
    ('AI Helps Teams Meet More Demand',4476.62,4532.7,'Remove the opening reference to a previous model discussion. Keep the leadership explanation and the full supply/demand growth conclusion.'),
    ('Know What To Do Before Raising Capital',5713.38,5746.38,'Remove the preceding investment-banking prompt. End after the complete capital-use explanation; avoid repeating the earlier expectations/mindset short.'),
    ('Why Cheaper Video Changes The Economics',7383.13,7423.35,'Keep the concrete product-video ROI example and its complete lower-cost conclusion. Remove the subsequent PR and future-version discussion.'),
]
profile=source_context(spec,s).profiles[0].model_copy(deep=True); profile.duration=Duration(target=60,minimum=30,maximum=90)
profile.layout.credit='Sravanth Aluru | EP 572'
spec.profiles=[profile]
spec.revision_of='full-episode-batch-v3-caption-timing'
plan.profiles=[profile]; plan.candidates=[]
plan.constraints['caption_boundary_skew_seconds']=.15
for index,(title,start,end,reason) in enumerate(selections,1):
    c=Candidate(id=f'clip_{index:03}',profile=profile.name,title=title,
        segments=[Segment(start=start,end=end,reason=reason)],reason=reason)
    aligned=[w for p in t.passages for w in p.words if start-.01<=w.start and w.end<=end+.01]
    assert aligned
    c.segments=[Segment(start=aligned[0].start,end=aligned[-1].end,reason=reason)]
    c.narrative=[text_for(t,c)]
    plan.candidates.append(c)
plan.director+=' + source-bound editorial revision'
plan=EditingPlan.model_validate(plan.model_dump())
atomic_json(plan_path,plan.model_dump()); atomic_json(folder/'request.json',JobSpec.model_validate(spec.model_dump()).model_dump())
atomic_json(folder/'editorial-revisions.json',{'draft':str(draft),'final_plan':str(plan_path),
    'reason':'Replace repeated AI-management choices and incomplete boundaries with five distinct, complete stories. Preserve all transcript words inside each final continuous cut.',
    'candidates':[c.model_dump() for c in plan.candidates],'paid_api_cost':0})
print(json.dumps([{'id':c.id,'title':c.title,'duration':c.duration} for c in plan.candidates]),flush=True)
