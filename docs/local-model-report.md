# Local Director and Critic — tested setup

Qwen3-4B-Instruct-2507 Q4_K_M is installed and running on the RTX 4060 Laptop GPU. The Director and Critic use separate, stateless requests to the same local model. No paid API or cloud inference was used.

The complete workflow test passed its execution checks. **Editorial approval did not pass:** one output was rejected and three require review. Successful rendering does not certify content quality.

## Runtime

- Model: Qwen3-4B-Instruct-2507-Q4_K_M.gguf; 2,497,281,120 bytes.
- Model revision: a06e946bb6b655725eafa393f4a9745d460374c9.
- Model SHA256: 3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597.
- Runtime: official llama.cpp b11429, Windows CUDA 12.4 build.
- GPU: CUDA0; 16,384 context tokens, one request slot, Flash Attention, Q8 KV cache.
- Endpoint: http://127.0.0.1:8088/v1; offline mode, local access key, no proxy or redirect fallback.
- Initial measured total GPU usage: 4,131 MiB, including desktop GPU use.
- Minimum free GPU memory during the final edit/revision run: 3,874 MiB (3.78 GiB).
- Login task, worker heartbeat, model authentication, and loopback-only listener passed a stop/start check. The worker and model are running.

## Live workflow results

The source is a 117-second generated pattern with original narration. CUDA faster-whisper/base produced 34 passages and 309 aligned words, without fallback. ASR ran fresh in the first live attempt; subsequent edits reused that verified cache. Some technical names were misheard. This is a pipeline test, not a transcription accuracy benchmark.

| Case | Output | Duration | Final status | Local model calls per job |
|---|---|---:|---|---:|
| auto | local_portrait | 20.83s | rejected | 3 |
| auto | local_landscape | 21.57s | review_required | 3 |
| targeted | local_portrait | 21.57s | review_required | 2 |
| revision | local_revision | 21.57s | review_required | 2 |
| no-match | none | — | no_matches | 0 |

The revision test deliberately removed 0.7 seconds at each speech boundary. The first render had verified partial-passage findings. The worker moved both boundaries to complete source passages, rendered again, and made a second isolated Critic request. The partial-boundary findings cleared. The model score changed from 26.0 to 80.5/100. The final score did not meet the 85-point pass threshold, so the output remains review_required. Scores are uncalibrated and do not prove a general improvement in editorial quality.

Every rendered output has burned ASS captions, an SRT, publishing Markdown, thumbnail, source map, saved frame samples, and versioned quality reports. NVENC was used. Actual FFmpeg/FFprobe and frame checks ran locally. The final source SHA256 matches the submitted source. The absent cryptocurrency request returned no matches with zero model calls. No filler was created.

## Checks and limits

- Final unit/contract checks: 57 passed.
- Final short-render integration checks: 6 passed.
- Three 300/600/900-second render checks passed in the earlier full regression run in this session. Render code was not changed afterward.
- PowerShell parsing, generated schemas, local endpoint authentication, service restart, and GPU device checks passed.
- Continuous selection uses verified source windows and server-enforced output schemas. Incorrect IDs, counts, choices, or durations cannot silently become a plan. There is at most one corrective Director request, eight model calls per job, and two supported render revisions.
- The Critic receives selected speech at output-relative times and measured AV evidence, without the Director rationale or score. Out-of-range findings and unsupported semantic “incomplete” claims cannot silently drive boundary repair.
- The small model still made inaccurate rationales and unsupported editorial suggestions in these tests. Treat titles, findings, and scores as advisory. The repair engine does not synthesize new narration from those suggestions.
- Text reasoning cannot see image pixels or hear audio. Metrics cannot certify lip sync, speaker framing, or caption legibility. Human review remains required before publication.
- Large transcripts exceeding the Director input budget use deterministic planning with a visible warning. Semantic topic matching still needs separate local embedding weights; diarization and visual action recognition remain unavailable.
- No human-rated benchmark, real talking-head trial, or autonomous publishing claim is made.

## Use

    .\scripts\ermclip.ps1 health
    .\scripts\ermclip.ps1 submit .\input\your_video.mp4 --instruction "Create one complete 30-second clip"
    .\scripts\ermclip.ps1 status

The login task starts both services. To free model VRAM, run scripts/stop-model.ps1; the next reasoning request starts it again. Stop the idle worker before rerunning scripts/validate_local_workflow.py, then start it with scripts/start-worker.ps1 afterward. The pinned public-file installer is scripts/install_local_model.py.

## Evidence and sources

- [Machine-readable live validation](local-model-validation.json)
- [CUDA ASR result](local-model-asr.json)
- [Service/startup check](local-model-service-check.json)
- [Final unit tests](local-model-unit-tests.xml)
- [Final integration tests](local-model-integration-tests.xml)
- [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- [Quantized weights](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF)
- [Official runtime release](https://github.com/ggml-org/llama.cpp/releases/tag/b11429)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
