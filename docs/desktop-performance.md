# Desktop resource evidence

Measured on this PC with an NVIDIA GeForce RTX 4060 Laptop GPU (8,188 MiB reported by the driver) and 32 logical CPU processors. No editing job was running during these samples. The model remained unloaded in both new-app samples.

| Measured state | Interval | Private memory, MiB | Working set sum, MiB | CPU, % of whole machine | GPU memory, whole device, MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous idle services, including worker and loaded 9B model | 11.08 s | 7,273.44 | 125.61 | 0.256 | 6,639 |
| New background UI service only | 10.95 s | 32.05 | 54.43 | 0.018 | 225 |
| Native desktop window and UI service, after startup | 21.12 s | 300.49 | 547.98 | 0.351 | 224 |

Private memory is committed private process memory. It is not the same as resident RAM. The previous idle model had a small resident working set but a large private allocation and GPU allocation. Summing working sets can count shared runtime pages more than once. The baseline does not include existing Chrome windows. These samples do not prove that the native window has a smaller resident working set than Chrome.

CPU is the sum of process user and kernel time changes, divided by the measured interval and 32 logical processors. The open-window sample is equivalent to 11.243% of one logical processor. Samples include the loopback service, the native window and its WebView2 children. Existing clients can also generate requests to that service. The sampling script is excluded. Only processes present with the same creation time in both snapshots contribute to the CPU delta.

GPU figures come from `nvidia-smi` and include unrelated apps and the Windows desktop. The drop occurred after the project-owned idle model was stopped. These are not per-window GPU measurements. Video playback, rendering, transcription and 9B reasoning use more resources than an idle window. Editing performance was not measured in this change.

## What changed

- With an empty queue, sign-in starts one small loopback service and no reference gallery, worker or model. Saved pending work resumes after restart unless paused.
- The shortcut opens one native window using the installed WebView2 runtime. It does not open Chrome or bundle another Chromium distribution.
- A second launch reuses the existing window.
- A submitted job starts the engine. One worker lock serializes heavy editing work.
- The on-demand worker releases the managed model and exits after five minutes with no pending jobs. Delayed retries and paused pending jobs are retained.
- Idle interface polling runs every 20 seconds. Active editing polls every four seconds. Hidden pages skip polling and pause the source preview.
- Caption preview images load lazily. There are no animation loops, external fonts, remote scripts or analytics in the interface.

## Checks and raw reports

The combined API, launcher, reliability, queue and podcast checks passed: **32 tests**. These include an empty import library despite allowed reference files, exact-file registration, source preservation, request access checks, idle model release, retention of a delayed retry and conditional restart of saved pending work.

The native check passed using the actual `edgechromium` renderer. It recorded five steps, no source selected, 25 caption styles, a visible import button, only loopback page resources and no new Chrome process. The native capture shows the rendered app content; its title was also read from the native window object. A second regular launch reused window PID 100360 during this test session.

The five-step UI check passed with no JavaScript errors or external page requests. It covered local path import, invalid duration prevention, caption selection, saved defaults, job submission, job-specific export review, revision, pause/resume, engine settings and source reset after reopen. It used a separate SQLite queue and a synthetic export fixture. It did not submit a production job or claim a new AI render. The Windows picker script passed syntax checks; its interactive file-selection action was not automated.

Raw reports and screenshots stay local and are excluded from Git:

- `output/workspace-checks/before-desktop.json`
- `output/workspace-checks/background-only.json`
- `output/workspace-checks/native-window-steady.json`
- `output/workspace-checks/native-checks.json`
- `output/workspace-checks/browser-checks.json`
- `output/workspace-checks/native-window.png`
- `output/workspace-checks/wizard-look.png`
- `output/workspace-checks/wizard-confirm.png`

To repeat a sample with the app open:

```powershell
.venv\Scripts\python.exe scripts/measure-desktop.py --label repeated-window --seconds 20
```

Close the native window before running `scripts/check-native-desktop.py`. Keep the local service running for `scripts/check-workspace-ui.py`. Neither checker enables a paid API. The native check opens and closes a temporary test window; normal shortcut launches keep the window open.
