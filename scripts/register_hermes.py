"""Register one external skill path without changing model or gateway settings."""
import json
from pathlib import Path
import sys
import time

import yaml

project,home,mode=Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve(),sys.argv[3]
config=home/"config.yaml"
original=config.read_text(encoding="utf-8-sig")
data=yaml.safe_load(original) or {}
skills=data.setdefault("skills",{})
path=str(project/"skills")
entries=skills.get("external_dirs",[])
if not isinstance(entries,list): raise ValueError("skills.external_dirs must be a list")
entries=[e for e in entries if str(Path(e).expanduser().resolve())!=path]
if mode=="install": entries.append(path)
skills["external_dirs"]=entries
backup=project/"state"/("hermes-skill-config-"+str(time.time_ns())+".yaml.backup")
# The backup contains private config; do not check it in or print it.
backup.parent.mkdir(parents=True,exist_ok=True)
backup.write_text(original,encoding="utf-8")
temporary=config.with_suffix(".yaml.ermclip.tmp")
temporary.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True),encoding="utf-8")
temporary.replace(config)
print(json.dumps({"skill_directory":path,"action":mode,"backup":str(backup),"restart_note":"Start a new Hermes chat or reload skills if this build requires it."}))
