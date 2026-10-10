"""Compare saved automated scores with explicit human ratings. Never invent ratings."""
import argparse
import json
from pathlib import Path
import statistics

p=argparse.ArgumentParser()
p.add_argument("ratings",type=Path)
a=p.parse_args()
data=json.loads(a.ratings.read_text(encoding="utf-8"))
examples=data.get("examples",[])
if not examples:
    print(json.dumps({"status":"no-human-ratings","quality_improvement_claim":False}))
else:
    errors=[]
    false_passes=0
    for example in examples:
        humans=example["human_scores"]
        if not humans or any(not 0<=score<=100 for score in humans): raise ValueError("Invalid human scores")
        automatic=float(example["automatic_score"])
        if not 0<=automatic<=100: raise ValueError("Invalid automatic score")
        mean=statistics.mean(humans)
        errors.append(abs(automatic-mean))
        false_passes+=int(automatic>=85 and (mean<85 or example.get("hard_violation",False)))
    print(json.dumps({"examples":len(errors),"mean_absolute_error":statistics.mean(errors),"false_pass_rate":false_passes/len(errors),"quality_improvement_claim":False},indent=2))
