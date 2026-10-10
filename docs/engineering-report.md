# Engineering report — 2026-10-10

## Delivery status

ERMCLIP has a working local processing pipeline, registered Hermes skill, persistent background worker, and installed Windows login task. The worker is running. This is a tested local MVP with production safeguards. It is **not yet a fully autonomous editorial system**.

The user selected local-only reasoning. The current model is Qwen3.5 9B Q4_K_M with a 64K local context shared with Hermes. It replaced the earlier Qwen3 4B model after weak editorial choices. There are now 24 caption presets and four real car-video demos, all marked for review. AUTO, TARGETED, caption variants, cut repair and no-match behavior passed execution checks on the user-specified video. See [the real-video report](real-demo-report.md) for evidence, rejected attempts and limits, and [the Hermes/Telegram setup](telegram-hermes-setup.md) for connection requirements. The [earlier 4B report](local-model-report.md) remains as historical evidence. No calibrated quality, virality, or broad editorial improvement is claimed.

## Implemented

- AUTO and TARGETED job schemas; conservative natural-language parsing; strict word-boundary keyword conditions, combined inclusion and exclusion, optional verified speaker labels.
- Continuous excerpts and chronological compilations, counts, duration ranges, strict targets, custom durations, per-profile total output budgets, and a 900-second video-stream limit.
- Multiple profiles, even custom dimensions, ratio validation, static face-aware cropping, centre crop, padding, blurred fill, and original-ratio preservation.
- Local faster-whisper transcription, language detection, word timestamps, imported JSON/SRT, GPU VRAM checks, isolated GPU transcription, CPU fallback, and shared analysis caches.
- ASS burned captions, karaoke highlighting, a pop preset, plain captions, SRT, configurable font/colour/position, safe margins, and caption-free exports.
- FFmpeg rendering, NVENC and CPU paths, loudness processing, short audio fades, stream synchronization checks, temporary render files, and cleanup.
- Schema-validated editing plans and source mappings. Loopback model-provider adapter, separate Director/Critic contexts, persisted model-call budget, score thresholds, hard quality gates, and bounded corrections.
- Pre-render findings, actual decoded frame samples, cut-audio samples, black/freeze/silence metrics, timing checks, and actionable review reports. Up to two supported boundary/framing revisions.
- SQLite jobs, atomic claims, duplicate prevention, persistent checkpoints, retries, restart recovery, graceful cancellation, pause/resume, worker lock, heartbeat, folder watching, batch inputs, and processing history.
- Per-output publishing Markdown with all 20 requested fields, separate Tags and hashtags, YouTube tag character counting, source timestamps, transcript, and factual-verification notes.
- Local ratings and feedback deletion, preference input for a configured Director, benchmark schema and score comparison tool.
- Hermes skill registered through `skills.external_dirs`, without Hermes core changes. CLI commands cover job control, tags, defaults, feedback, and regeneration.
- Existing-bot outbound Telegram adapter, sender allowlist checks, durable events, limited delivery retries, and redacted notification errors. No second inbound bot listener.
- PowerShell setup, start/stop, task registration/removal, skill registration/removal, JSON schemas, dependency lock file, and operation documents.

## Partial or unavailable

- **Autonomous content understanding and AI Critic:** the local Qwen3.5 9B model selects only verified source windows and reviews output evidence in isolated contexts. It reads the full compact source when it fits; larger sources use an explicit shortlist. A forced boundary repair and second live Critic call passed on the real video. Low scores and unresolved findings remain rejected or review_required. Human-calibrated autonomous editorial approval is unavailable. Live Hermes cloud planning was not invoked.
- **Semantic topic matching:** optional local embedding adapter is implemented. Its dependency and weights are not installed, so execution is untested. The system rejects semantic requests when that evidence is unavailable.
- **Speaker identification:** imported verified labels are supported. Automatic diarization is not implemented.
- **Visual action matching and dynamic tracking:** not implemented. Sparse face sampling supports fixed crops only. Object/action-specific requests fail clearly.
- **Silence trimming:** requested settings produce an explicit plan warning. Speech pauses are not removed automatically.
- **Perceptual audiovisual evaluation:** real frames/audio and numerical metrics are saved, but there is no audiovisual reasoning model or subtitle OCR. Stream checks cannot prove lip sync or readability. The text critic cannot see or hear the video.
- **Broad editorial repairs:** boundary expansion and padding are supported. Automatic semantic reordering, weak-material replacement, repetition editing, and pacing reconstruction need further work.
- **Telegram:** the inspected active Hermes home had no bot token, home channel, sender allowlist, or running gateway. Mock delivery and authorisation passed. Live notifications and media delivery remain untested. Automatic outbound media transfer is not implemented.
- **Preference learning:** feedback storage and Director input exist. No trained preference model or human-rated benchmark exists.
- **Free cloud providers:** none enabled. The additional paid-API budget remains zero. No private video or transcript was sent to a cloud inference provider.

## Environment verified

| Item | Observed |
|---|---|
| OS | Windows |
| Python | Project venv, Python 3.11.15 |
| CPU | 32 logical threads |
| RAM | 23.63 GiB |
| GPU | NVIDIA RTX 4060 Laptop GPU, 8188 MiB VRAM |
| FFmpeg | 8.0 full build, libass, libx264, and NVENC available |
| Local ASR | faster-whisper 1.2.1, base weights downloaded |
| GPU ASR runtime | Project-local cuBLAS 12, cuDNN 9, and NVRTC libraries |
| Hermes | Running desktop build at the supplied path; CLI 0.21.6+509 build stamp |
| Hermes skill | `ermclip` listed as external, local, enabled |
| Startup task | `ERMCLIP Local Worker`, registered and running |

See `environment.json` and `asr-cuda-validation.json`. The initial CUDA attempt failed because cuBLAS was absent; CPU fallback worked. After isolated runtime installation, GPU ASR passed with 34 passages and 293 aligned words. NVENC rendered the sample outputs successfully.

## Tests and real outputs

The bullets below record the initial MVP checks. The later local-model validation added six tests: 57 current unit checks and 6 current integration checks passed, plus the three long-render checks already passed in this session. See [local-model-report.md](local-model-report.md) for the four real local-model outputs and revision evidence.

- Main regression suite: **56 passed**, 3 long-duration tests deselected; 117.19 seconds. Saved JUnit evidence: `test-results.xml`.
- Long-duration suite: **3 passed**; 208.20 seconds. Actual 300-, 600-, and 900-second video streams rendered and probed successfully.
- Additional reliability/Critic run: 9 passed. These are included in the final 56-test main suite and are not an additional count.
- A subsequent revision-loop test checks that three drafts stop after two revisions despite persistent critic findings. Evidence: `revision-test-results.xml`.
- Initial MVP unique automated tests executed: **60 passed** after the separate revision-loop check.
- PowerShell syntax validation and Hermes frontmatter validation passed.
- Hermes external skill discovery passed. Worker manual start, graceful stop, and Scheduled Task restart passed. A reboot/sign-in cycle and a full overnight run were not performed.
- Initial local narrated demo, before model installation: portrait and landscape outputs, each about 31.73 seconds, with burned captions, SRT, Markdown, thumbnails, source maps, and audiovisual findings. Both were `review_required` because the AI critic was not yet configured.
- A real TARGETED request for context explanations produced a captioned portrait video using the same cached analysis. A cryptocurrency-only request produced `no_matches` and no video.
- Exact source SHA-256 and metadata timestamps are saved. Automated integration tests prove source files remain unchanged.
- The speech sample uses our generated narration and a moving test pattern. Synthetic long-video tests use transcript fixtures; they do not prove long-form editorial coherence or long-audio recognition quality.
- The base ASR misheard some technical names in the generated voice. Exact NVIDIA/CUDA matching therefore returned no match. This is a transcription accuracy limit, not proof that those spoken concepts are absent. Review the transcript and correct an imported transcript when names matter.

## Requested acceptance tests

| # | Acceptance item | Evidence/status |
|---:|---|---|
| 1 | Hermes accepts local path | Skill discovered; underlying CLI accepts and queues local files. Live agent interaction untested. |
| 2 | Natural-language interpretation | Parser tests pass. Complex live Hermes interpretation untested. |
| 3 | Valid editing plan | Schema tests and real demo plans pass. |
| 4 | AUTO selects moments | Deterministic tests and real local Qwen selection pass execution checks; editorial scores remain uncalibrated. |
| 5 | TARGETED conditions | Keyword, exclusion, speaker-label gates tested; optional semantic model untested. |
| 6 | Unsupported/unmatched requests | Fail-closed tests and real no-match demo. |
| 7 | 30-second output | Actual FFmpeg render passed. |
| 8 | 60-second output | Actual FFmpeg render passed. |
| 9 | 5-minute output | Actual FFmpeg render passed. |
| 10 | 10-minute output | Actual FFmpeg render passed. |
| 11 | 15-minute output | Actual FFmpeg render passed. |
| 12 | Longer than 15 minutes rejected | Duration and plan schema tests pass. |
| 13 | Arbitrary durations | Seconds, minute strings, fractions, HH:MM:SS parsing tests pass. Not every value was rendered. |
| 14 | Custom ratios | 7:5 actual compilation render passed. |
| 15 | Custom resolutions | Real custom landscape, square, portrait, and 7:5 renders pass; 4K performance untested. |
| 16 | Multi-profile analysis reuse | Integration test and real demo reuse one source analysis. |
| 17 | Continuous context | Passage-boundary/context tests pass; human content quality remains untested. |
| 18 | Compilation progression | Chronological timeline tests and compilation rendering pass; long-form narrative quality untested. |
| 19 | Subtitle timing | Source-to-output mapping tests and real burned captions inspected. No OCR validation. |
| 20 | A/V sync | Stream timing checks pass. Perceptual lip sync untested. |
| 21 | MP4 has Markdown | End-to-end package test and demo outputs pass. |
| 22 | Tags distinct from hashtags | Tests pass; 500-character counting includes multiword quotation marks. |
| 23 | Technical validation | Full decode tests, FFprobe checks, and real sampled-frame/audio evidence pass. |
| 24 | Actionable AI evaluation | Mock gates and real isolated local Critic calls tested. Findings are advisory; unsupported suggestions remain for review. |
| 25 | Supported revisions | Boundary and crop-to-padding tests pass. A real partial-boundary edit was repaired, rendered, and reviewed again by the local Critic. Broad editorial revisions remain partial. |
| 26 | Bounded revisions | A pipeline test with persistent critic findings verifies exactly three drafts: initial render plus two revisions. Remaining issues stay marked for review. |
| 27 | Telegram receives status | Mock API test passes. Live delivery untested; active credentials absent. |
| 28 | Restart recovery | SQLite recovery tests and actual worker restart pass. Mid-render forced-power-loss test untested. |
| 29 | Duplicate prevention | Submission, concurrent claim, and watcher tests pass. |
| 30 | Original unchanged | Full-file fingerprint integration test passes. |

## Start, stop, submit, and inspect

From the project root:

```powershell
.\scripts\start-worker.ps1
.\scripts\stop-worker.ps1
.\scripts\ermclip.ps1 submit .\input\video.mp4 --instruction 'Create three 60-second clips'
.\scripts\ermclip.ps1 status
.\scripts\ermclip.ps1 health
```

The worker is already running under the login task. Add only requested external input folders to `config/local.json` `allowed_inputs`. Put watched folders in `watch_folders`. Change future defaults with `defaults --profiles <profile.json>`, or use `submit --profile <profile.json>`. See `config/profiles.json` for durations, ratios, and dimensions.

Outputs are under `output/<source>/<job-id>/<profile>`. Open `manifest.json` and `summary.md`, then each MP4, its `.md`, and `*_quality.json`. Do not publish a rejected video. Review all review_required outputs.

The installed login task starts after this user signs in. The PC must remain powered and awake. The display can be off. No global sleep or security settings were changed. Use `install-startup.ps1 -Remove` to remove startup registration.

## Costs and next steps

Additional paid-API cost: **zero**. Models, packages, and CUDA libraries were downloaded for local processing. They use local disk and compute. No cloud inference was performed.

The local reasoning server is installed and tested. The main next step is to measure Director/Critic behavior on human-reviewed source videos, improve selection and repair quality, and calibrate scores. Telegram still needs the user's local gateway credentials before live delivery can be tested. These steps are required before claiming the complete autonomous-editor vision is delivered.

Automatic approval review rejected external codebase indexing of the Hermes source because it could disclose private code to an unverified service. Integration discovery used local file inspection instead. No indexing export was performed.
