# Caption styles and real-video validation

Date: 10 October 2026.

## Result

24 reference-based caption presets are available in the local picker. Four real-video demos are saved in output/real-demo. All final demos are marked review_required. No paid inference API was used.

The Director and Critic use Qwen3.5 9B Q4_K_M on the RTX 4060. The model uses separate request contexts for each role. The runtime listens only on authenticated 127.0.0.1:8088 and runs with offline mode. The 4B weights remain cached as a fallback.

## Final demo files

| Style | Frame | Seconds | Status | Uncalibrated score |
|---|---|---:|---|---:|
| highlighter_16x9 | 16:9 | 39.57 | review_required | 79.25 |
| bold_lime_16x9 | 16:9 | 26.30 | review_required | 86.50 |
| momentum_9x16 | 9:16 | 26.30 | review_required | 88.00 |
| digital_highlights_9x16 | 9:16 | 26.30 | review_required | 93.25 |

The Highlighter demo starts at source 18:49.75 and explains the extended CV axle and welding jig. The other three demos start at 03:28.16 and end at 03:54.48. They retain the complete width-choice and special-permit explanation. Portrait outputs preserve the whole car over a blurred background. SRT, ASS, source mappings, metadata and quality reports accompany each MP4.

## Verification

- 88 unit checks passed. Six FFmpeg integration checks passed. XML results are saved with this report.
- All 24 style previews were rendered with FFmpeg/libass. The picker selection and JSON profile download worked in the local browser.
- GPU Whisper small transcribed the full source: 371 passages and 3,062 aligned words. Model downloads are disabled for normal inference.
- AUTO, TARGETED, style variants, deliberate cut repair and no-match behavior ran locally on the real video.
- The cut-repair test rendered revision 1. It cleared the verified incomplete-statement findings. Its uncalibrated score changed from 76.5 to 92.5.
- The absent-term request returned no clips and used no model calls.
- Source SHA-256 is 8f6f93dec6621a4aa8b13ddbad9da29c1f601b4450751670593bfafe3f57ff8d. The source file is unchanged.
- Paid API usage and paid API cost: 0.

## Model and planning changes

These demos used the 9B model with a 32,768-token context. Measured idle GPU use was about 6,007 MiB, with about 1,950 MiB free. The later Hermes integration increased the shared server to 65,536 tokens; GPU use measured about 6,776 MiB with 1,181 MiB free. The worker releases its own language-model server before GPU transcription when available memory is below the configured threshold, then restarts it for planning. It does not stop unrelated GPU processes.

Early AUTO selections used a shortlist and were rejected for sponsor content or missing context. A first full-transcript attempt exceeded the old context limit. Free passage-index choices also failed duration validation. These failed and rejected jobs remain in the queue audit history. No weak output was marked passed.

The corrected 9B path reads the full compact transcript when it fits the input budget. It chooses only from schema-constrained, pre-verified source windows. All possible qualifying openings remain visible; up to three valid ending options are provided per opening. This prevents invented times and unchecked duration choices. Larger transcripts still use a heuristic shortlist with an explicit warning. Strict-duration and compilation profiles use their existing validated planning path.

## Local style picker

Open output/caption-gallery/index.html in a browser, or the current loopback preview at http://127.0.0.1:8091. The preview server serves only the gallery folder. The page uses no CDN, external fonts, analytics or external model calls. A chosen card saves a profile JSON. Use scripts/ermclip.ps1 submit VIDEO --caption-style highlighter for a direct style choice.

The two unnamed reference styles are called Forest Notes and Retro Serif. Styles approximate the references with installed font families. Single-word styles use verified word timing. An imported SRT keeps passage timing. The old highlight, plain and pop presets remain available.

## Review limits

The isolated Critic reads selected speech and measured AV evidence. It does not see pixels or hear sound. Its scores are not calibrated. Fast captions, transcript accuracy, visual legibility and pacing still need human review before publication. The Highlighter excerpt scored 79.25, below the automatic pass threshold, and remains marked for review. All outputs stay local and nothing is published.

## Evidence and sources

- final-demo.json: final jobs, media paths, source mappings, local model usage and cost.
- real-demo-validation.json: full workflow and revision history.
- caption-unit-tests.xml and caption-integration-tests.xml: regression checks.
- 9b-local-runtime-check.json: endpoint, authentication, network and runtime checks.
- [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-9B).
- [Pinned GGUF weights](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/tree/3885219b6810b007914f3a7950a8d1b469d598a5).
