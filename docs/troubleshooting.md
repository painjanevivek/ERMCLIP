# Troubleshooting

## Worker does not start

Run `scripts/ermclip.ps1 health`, then inspect `logs/worker.jsonl`. A second worker cannot acquire `state/worker.lock`. Do not delete a live worker's lock file. Use `stop-worker.ps1`, wait for health to say stopped, then start again.

If Python is missing from PATH, use the project scripts. They select `.venv/Scripts/python.exe`. `setup.ps1 -PythonPath <path>` can create the environment from Python 3.11 or 3.12. Use `uv` for dependency installation.

## Source rejected

Add only the requested source folder to `allowed_inputs` in `config/local.json`. Check that the file exists and FFprobe can read it. Finish the download first. The source cannot be changed between submission and execution.

## Whisper cannot load weights

The default is `allow_model_download: false`. The development install downloaded the base weights to `cache/models`. If these files are absent, explicitly enable model downloads or provide an existing local model path. The download fetches weights; it does not upload media.

## GPU transcription fails

The RTX 4060 was detected. CTranslate2 requires a compatible CUDA/cuDNN runtime in addition to the NVIDIA driver. GPU transcription was verified after installing project-local NVIDIA packages. For a fresh environment, install the `cuda` extra with `uv pip install --python .venv/Scripts/python.exe -e '.[cuda]'`. The child process loads their DLL directories locally. Check the saved transcript warnings. In `auto`, the child ASR process retries on CPU if CUDA fails. Set `whisper_device: cpu` to use a stable CPU configuration. ERMCLIP does not change system CUDA installations.

## NVENC fails

Set `encoder: auto` for CPU fallback or `encoder: cpu` to select libx264. The FFmpeg binary must include libass and libx264. `doctor` reports binary paths. Drivers and encoder availability can change; a listed encoder does not prove that it can execute on the GPU.

## No clips found

No matching source content, insufficient duration, excluded context, unavailable semantic models, or missing speaker labels can prevent selection. Do not lower strict conditions merely to produce a file. Review the plan warnings and source transcript. The system does not claim visual-event matches.

## Output requires review

Read the matching `*_quality.json`. Open the MP4 and saved `*_review` frame/audio samples. Without a configured critic, the status remains review_required. A numerical pass is not human proof of editorial quality. Revisions are limited to supported corrections and duration constraints.

## Local Director or Critic is unavailable

Run `scripts/start-model.ps1`. Inspect `logs/local-model.log` and `state/local-model.json`. The managed server requires its files under `cache/local-llm`, CUDA device `CUDA0`, and free loopback port 8088. Do not change the endpoint to a cloud proxy. The private local key is in `state/local-model.key`; do not paste it into a chat. Run `scripts/stop-model.ps1` to release GPU memory. The next reasoning request starts the server again.

If GPU memory is low, close other GPU workloads. The selected 4-bit model uses about 4 GiB with a 16K context on this PC. ASR checks free VRAM and can fall back to CPU in normal auto mode. The live validation forces CUDA so a silent CPU fallback cannot count as a GPU pass.

Large transcript payloads use deterministic planning with an explicit warning when they exceed the Director input budget. The installed model does not provide diarization, visual action recognition, or perceptual AV review. Low scores and unsupported editorial repairs stay visible in the saved reports.

## Telegram does not notify

Run `doctor`. The inspected desktop installation had a stopped gateway and no Telegram token, home channel, or allowed users. Configure the existing bot locally through the installed Hermes gateway setup. Do not create a second polling bot. Set ERMCLIP `hermes_home` and `telegram_enabled`, then use `notify-test`. Token values are never printed by ERMCLIP.

Notifications are retried up to three times per event. Unsent events remain in SQLite. This release does not automatically retry them forever or send media files. The gateway skill is responsible for incoming natural-language controls and verified sender context.

## Overnight job stops

The PC must be awake. Sleep, power loss, sign-out, or shutdown can interrupt execution. Start the worker again to recover checkpoints. The startup task runs after this user signs in. It does not change sleep policy and does not run while the PC is off.

## Cache cleanup

Use `clean-cache` to preview unused analysis caches older than `cache_days`. Use `clean-cache --apply` to remove them. Referenced caches and model weights are retained. Original inputs are never removed. Delete old job outputs manually only after you decide they are no longer needed.
