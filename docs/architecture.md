# Architecture

## Boundaries

Hermes interprets requests and can provide an approved editing plan. ERMCLIP accepts only validated JobSpec and EditingPlan data. It never executes instructions in a transcript or model response.

The CLI writes jobs to SQLite. The worker owns one exclusive file lock. It runs independently of a chat, recovers interrupted jobs, and processes one GPU-heavy task at a time. Separate foreground analysis commands use the same lock.

The media engine uses FFprobe, FFmpeg, local faster-whisper, and OpenCV. The optional sentence-transformers adapter implements semantic comparison on CPU. The LocalModel adapter supports an operator-configured loopback OpenAI-compatible endpoint. No cloud fallback exists.

## Flow

Request → input allowlist and stability checks → full file fingerprint → persistent queue → source probe → cached transcript and visuals → Director → validated timeline → pre-render checks → ASS/SRT → segment renders → final render → actual audiovisual metrics → isolated text Critic → bounded revision → publishing Markdown → manifest.

Cached analysis is keyed by source SHA-256, transcript identity, transcription model, and scene setting. It is shared across profiles and compatible jobs. Changing a transcript creates a new cache entry.

## Persistence

`state/jobs.sqlite3` stores jobs, events, controls, feedback, and watched-file fingerprints. The schema is defined in `src/ermclip/store.py` and exported to `config/sqlite-schema.sql`. WAL supports CLI commands during worker execution. Claims use `BEGIN IMMEDIATE`. Fingerprint plus normalized spec identifies duplicate submissions.

A job stores its source fingerprint, analysis cache, and final output records. Recovery changes interrupted running jobs to queued. Existing packaged outputs are reused only when the video, Markdown, and quality report exist. A render interrupted before packaging is rendered again. This is output-level recovery, not frame-level encoding resume.

The heartbeat runs in a separate thread. Stop/cancel flags are checked while FFmpeg and transcription subprocesses run. Calls to local reasoning servers have a 300-second timeout; they do not stop immediately on cancellation. Model-call counts persist across retries and restarts. Retries are separately bounded.

The managed Qwen3.5 9B service uses pinned project-local GGUF weights and official CUDA llama.cpp binaries. It binds to 127.0.0.1, requires a local key, and runs offline with a 64K context shared with Hermes. Continuous, non-strict requests use the complete compact transcript when it fits the input budget. The model can choose only schema-constrained, verified source windows, with up to three valid ending options per qualifying opening. Code supplies exact timestamps and candidate IDs. Larger transcripts use an explicit heuristic shortlist. Strict and compilation requests retain their validated planning path. Invalid choices get at most one corrective request. The independent Critic sees actual selected speech with output-relative times, proposed title, and measured evidence, without the Director's rationale, narrative, or score. Unsupported or out-of-range findings cannot silently trigger a boundary repair. A verified no-match needs no model call.

The caption style catalog is shared by the job schema, CLI, ASS writer and local picker. Its 24 previews are rendered by FFmpeg/libass. Styles define installed font families, colors, outlines, boxes, shadows, glow layers and grouping. Single-word presets use verified word timing; imported SRT retains passage timing. Source text is escaped before ASS overrides are added. The managed model can be stopped before GPU ASR when memory is low; the next local Director call restarts it.

## Editorial safeguards

Pre-render checks verify source boundaries, conditions, context warnings, repetition, and transcript evidence. Hard findings reject before rendering. The actual render is decoded and inspected for dimensions, duration, stream start/duration differences, black/frozen intervals, and silence. Critical edit frames and audio are saved for review.

The optional isolated text critic receives the selected transcript, timeline, and numerical audiovisual findings. It does not receive pixels or audio. Score weights are relevance 25, coherence 25, hook/pacing 15, value 15, visual 10, and audio/subtitles 10. Scores below 70 reject; 70–84 require revision. Hard findings override scores. Unreviewed material cannot get a fabricated score.

The supported automatic repairs move boundaries to complete transcript passages, add preceding context if it fits, and change cropping to padding when a critic identifies a cropping issue. Each proposed repair is schema-validated and condition-checked. There are at most two revision passes. Unsupported corrections remain visible for review.

## Limits

This release has no visual action recognition, speaker diarization, OCR subtitle validation, or self-calibrating benchmark. Sparse Haar face samples support static smart framing. Podcast framing adds CPU-only YuNet face tracks and the Light-ASD audiovisual activity model, with timed crops and full-frame fallback. It does not infer speaker names or voice identities. Outputs retain tracking evidence and require review. Imported transcripts can provide verified speaker labels for content selection. Feedback is saved locally and passed to a configured Director; it does not train weights or prove improvement.

The output timeline is capped at 900 seconds. AAC container padding can make the container duration slightly larger than the video stream duration; the video stream itself is capped at 900. Profile dimensions are even H.264-compatible values. The source is never opened for writing.
