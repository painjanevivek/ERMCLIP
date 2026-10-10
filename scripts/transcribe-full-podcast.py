"""Build a complete, offline word transcript; preserve the source."""
from pathlib import Path
from ermclip.config import load
from ermclip.models import JobSpec
from ermclip.pipeline import analyse
from ermclip.util import atomic_json, fingerprint
from ermclip.worker import worker_lock

s = load()
source = Path(s.podcast_sources[0])
folder = s.path / 'output/raj-shamani-batch'
folder.mkdir(parents=True, exist_ok=True)
identity = fingerprint(source)
spec = JobSpec(source=str(source), podcast_mode='on', transcript_language='en')
with worker_lock(s.path / 'state/worker.lock'):
    info, transcript, visuals, cache, reused = analyse(spec, s, identity)
    atomic_json(folder/'full-transcript.json', transcript.model_dump())
    atomic_json(folder/'analysis.json', {'source':str(source), 'fingerprint':identity,
        'duration':info['duration'], 'cache':str(cache), 'reused':reused,
        'language_hint':'en', 'paid_api_cost':0, 'passages':len(transcript.passages)})
    print(str(folder/'full-transcript.json'), flush=True)
