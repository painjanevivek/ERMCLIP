"""Run real local ASR on the generated demo. Keep evidence separate from job caches."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from ermclip.config import load
from ermclip.transcribe import transcribe
from ermclip.util import atomic_json

settings=load()
settings.whisper_device="cuda" if "--cuda" in sys.argv else "cpu"
cache=settings.path/"cache"/("asr-validation-"+settings.whisper_device)
cache.mkdir(parents=True,exist_ok=True)
result=transcribe(settings.path/"input"/"ermclip_demo.mp4",cache,settings)
assert result.passages and sum(len(p.words) for p in result.passages)>100
assert "context" in " ".join(p.text.lower() for p in result.passages)
summary={"engine":result.engine,"language":result.language,"passages":len(result.passages),"aligned_words":sum(len(p.words) for p in result.passages),"warnings":result.warnings,"source":"generated narration; synthetic visual pattern"}
atomic_json(settings.path/"docs"/("asr-"+settings.whisper_device+"-validation.json"),summary)
print(summary)
