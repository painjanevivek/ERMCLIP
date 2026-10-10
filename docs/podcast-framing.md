# Local podcast speaker framing

The supplied Raj Shamani episode is registered in `config/local.json` under
`podcast_sources`. Future submissions of that exact file enable speaker framing
even when its filename and request do not contain the word podcast. Add other
known podcast file paths there, or select podcast mode when submitting them.

Podcasts use a moving portrait crop that follows the visible person who speaks.
The local Light-ASD model compares face motion with speech audio. YuNet detects
faces. Box association keeps separate tracks; a shot change resets them. The
largest face is not assumed to be the speaker.

Run `scripts/setup-speaker.ps1` once on a new installation. It downloads pinned
public models and CPU-only Torch. Model files are about 4.4 MB; the Torch wheel
is about 591 MiB. No inference API is used. Assets have SHA-256 checks. The
worker never downloads them during a job. Both models use MIT licences, kept
with the installed files. The adapted architecture and licence are in
`src/ermclip/_light_asd/`.

Use `submit VIDEO --podcast --caption-style highlighter`, or set
`profiles[].framing` to `speaker` in a job spec. In automatic mode, the words
podcast, interview, or active speaker in the request or source filename enable
speaker framing. This uses the user's context, not a video-type classifier.
Set the job's `podcast_mode` to `off` to disable automatic routing; `on` forces
it. A request to keep the full frame, or an `original` profile, preserves that
framing. Named-speaker content selection still needs verified transcript labels.

The speaker must have a high audiovisual activity score and a clear margin over
other faces for at least 0.4 seconds. An established speaker uses a lower exit
threshold to prevent small score changes from switching the camera. Median
face-box smoothing and two temporal contexts reduce detector and model jitter.
A short local energy window keeps pauses between words from resetting the crop.
The crop follows small movements smoothly.
It cuts to a new speaker rather than panning across listeners. Scores are not
calibrated probabilities. Silence, uncertain choices, short face tracks,
missing audio/models, overlapping speech scores, and off-screen speech use the
padded full frame. Crop limits can prevent exact centering near a frame edge.

Audio stays continuous within each selected cut. The crop uses timed FFmpeg
commands; it does not create extra audio cuts. Each cut has independent tracks
and output offsets. Exact cut analysis stays cached across caption changes. A
different cut or source gets a different cache key.

Each export has a `_speaker_tracking.json` sidecar. It gives model version,
source identity, source times, output offsets, tracks, crop centers, fallback
intervals, coverage, and warnings. Quality reports require review for this
feature. Check actual speaker turns, frame edges, and fallback intervals before
publication. It does not identify people, name voices, or provide diarization.
Captions still use the transcript.

Sources: [Light-ASD](https://github.com/Junhua-Liao/Light-ASD),
[CVPR paper](https://openaccess.thecvf.com/content/CVPR2023/papers/Liao_A_Light_Weight_Model_for_Active_Speaker_Detection_CVPR_2023_paper.pdf),
[YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).

Private video, audio, faces, and transcripts stay on this computer. Speaker
analysis uses the CPU beside the RTX 4060's local 9B reasoning model. Paid API
cost is zero. The Telegram gateway stays off until the owner resumes it.

The selected weights are the authors' TalkSet fine-tuned model. On one supplied
podcast exchange, focused-crop coverage was 73.3%, versus 56.8% with AVA weights
under the same rules. Coverage measures time spent in the crop; it is not an
accuracy score or proof of speaker identity. See the local validation report.
