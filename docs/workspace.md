# ERMCLIP desktop app

Double-click **ERMCLIP** on the desktop. A native Windows window opens. It uses WebView2 and does not launch Chrome. Each new session starts at step 1 with no selected source. Reference videos stay on disk and are not built into the interface.

## Five steps

1. **Import video.** Select **Upload / import video** for the Windows file picker. You can also paste a full file path. The app opens the original file without copying it or uploading it to the internet. It permits only that exact file. Check the source preview and audio. Previously imported files remain in the library for explicit selection.
2. **Choose shorts.** Set count, target length, minimum and maximum length, format, and resolution. Write the editing brief. Select Podcast / interview for active speaker tracking. Open topic controls for keywords, exclusions and speech language.
3. **Set the look.** Choose the frame layout. The portrait podcast default is the thumbnail hero layout with a black canvas and headline. Select one of 25 caption styles. You can change font, size, color, caption group length, burned captions and subtitle export. Add episode credit if needed.
4. **Check & start.** Read the source, duration, canvas, framing, captions, language and brief summary. Select **Create shorts**. The app checks file stability, fingerprints the source, saves the job and starts the local engine. Save these settings as default here if needed.
5. **Review exports.** Follow the status and stage. Exports shown in this step belong to this job. Watch each short, listen to the audio and check its captions. Download the MP4, SRT and checks. Use **Details / request revision** to describe a change. The app saves a new job and keeps earlier exports. Select **Make another set** to return to an empty source.

The count is a ceiling. The engine can produce fewer clips when the source cannot meet the conditions. Choose duration bounds that preserve complete speech. Exact duration can require review. Topic conditions use transcript text; named speakers and visual actions need verified annotations.

## Settings and queue

Open **Settings** to change encoding, speech processing, a cached speech model, or the AI call ceiling. These settings apply before the next job. Active jobs keep their existing settings. The UI cannot change credentials, model routes or the zero paid API budget. It does not download model weights.

Open **Editing jobs** for all job stages and recent events. Pause stops new jobs from starting; the current job can finish. Resume permits queued work. Cancel stops the selected job and keeps existing output files. **Details / revise** creates a new job from the same source and profiles. The standard instruction parser applies; complex visual conditions need verified annotations.

Open **My shorts** for exports recorded in job manifests. There is no fixed reference batch or reference filter. A status of `review_required` means a person must check the result. The Critic sees text and measurements, not pixels or audio. Check titles, captions, speaker changes, fallback frames and story context before publication.

## PC load and restart

Only the small loopback UI service starts at Windows sign-in. The shortcut opens one native window. Neither action starts the editing model. A job submission starts the worker and local model on demand. The on-demand worker exits and releases the managed model after five minutes with no pending work. Delayed retries and paused pending jobs keep the worker alive. A continuous CLI worker without `--idle-exit` stays running.

Closing the app window leaves current editing jobs running. Reopen the app and select Editing jobs to find them. After a PC restart, saved pending work starts the engine again unless the queue is paused. An empty queue loads no model. Keep the PC awake during editing. Keep the project folder in its installed location. See the [sequence diagram](desktop-sequence.md) and [resource measurements](desktop-performance.md).

## Local access and recovery

The service binds to 127.0.0.1. Foreign Host/Origin requests are rejected. Changes require a request token. Only deliberately imported source videos, caption previews and permitted output artifacts are served. Video ranges support seeking without transferring the whole source to another computer.

The interface uses no external fonts, scripts or analytics. Model reasoning and video processing stay local. Optional Telegram setup stays in Hermes; this UI does not enable its gateway. The installed Windows WebView2 runtime can receive its normal Microsoft updates independently of ERMCLIP.

If the app stops responding, use the desktop shortcut again. If another application owns port 8090, the launcher reports the conflict and does not stop it. Check `logs/workspace.log` and `logs/desktop-launcher.log` for startup errors. The heartbeat and launcher status stay in `state/`. No global sleep settings are changed.
