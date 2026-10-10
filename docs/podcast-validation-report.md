# Podcast framing validation — 10 October 2026

The local speaker feature is installed. It uses the authors' TalkSet fine-tuned
Light-ASD weights and YuNet face detection. It runs on the CPU. The Director and
Critic use Qwen3.5 9B on the RTX 4060. All inference stays local. Paid API cost is
zero. The original podcast has the same SHA-256 hash after the tests.

The supplied Raj Shamani episode is registered as a podcast in local settings.
Its future submissions enable speaker framing automatically. Other files use
request context, filename context, `submit --podcast`, or a `speaker` profile.
The caption picker has a podcast switch. Its saved JSON profile was validated.

The demo uses a two-minute local excerpt from original source seconds 270–390.
The final clip uses original seconds 308.36–341.20. It is 32.83 seconds of video,
540 × 960, with continuous audio and Digital Highlights captions. An additional
Highlighter preview uses the same source cut and cached speaker tracks.

The full edit test ran transcription, local Director selection, encoding,
captions, independent local Critic checks, metadata, and source mapping. The
revision test changed boundaries, title, and captions. The first Director choice
needed correction. The final boundaries were verified against the local
transcript and submitted as a revised plan. The final render and Critic check
took 51.61 seconds and one local model call; cached transcription was reused.

On the same 32.84-second exchange, AVA weights focused the crop for 56.8% of the
timeline. TalkSet weights focused it for 73.3%. The rest used the full frame.
Coverage is not an accuracy score. Track changes also include camera cuts;
these IDs do not identify named speakers. Actual rendered frames show crops of
both speakers. There is no independently labelled speaker-identity benchmark.

The tests also found a Critic score-format error. The model copied importance
weights instead of quality scores. The request now excludes those weights, and
the validator rejects that response. Caption tails are balanced without losing
words or changing word timestamps. A possible context issue based only on an
opening conjunction now asks for review rather than forcing boundary changes.

Validation: 117 regression tests passed; three long render tests were excluded.
After registering source types, 83 focused checks passed, including its new
routing check. Actual encoded-pixel tests verify crop changes and full-frame
fallback. They also check audio/video duration. Tests cover speaker settling,
score changes, silence, competing faces, scene resets, cache isolation,
cancellation, cut bounds, and retained speaker framing during revisions.

The final export is `review_required`. Three short caption intervals remain
fast to read. The opening and uncertain speaker intervals also need review.
The Critic has transcript text and numerical evidence; it cannot inspect pixels
or listen to speech. This export is a review demo, not a publication approval.

Artifacts are in `output/podcast-demo/`:

- `podcast-speaker-demo.mp4`: final Digital Highlights demo.
- `podcast-speaker-highlighter.mp4`: caption-only preview; no separate Critic call.
- `speaker-checks.jpg`: sampled rendered crops and fallback frames.
- `podcast-speaker-demo_speaker_tracking.json`: exact cut-relative track evidence.
- `podcast-speaker-demo_quality.json`: findings and local Critic report.
- `podcast-speaker-demo_source_map.json`: mapping to the original episode.
- `source-preservation-check.json`: original file hash comparison.
- `caption-revision-check.json`: verified reuse of real speaker tracks.

The existing editor service is restored. Telegram remains off at the owner's
request. External code indexing was blocked by automatic approval review. All
code inspection used local source files instead.
