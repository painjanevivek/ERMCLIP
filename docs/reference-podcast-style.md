# Supplied podcast reference

Podcast requests now default to `podcast_hero`, active-speaker framing, and
`short_yellow` captions. This applies to registered podcast sources, explicit
podcast mode, and podcast or interview instructions. Other videos keep their
existing defaults. A custom layout or caption preset is retained. Set
`inherit_podcast_style: false` in a profile to keep a plain layout. The picker
does this for explicitly saved choices. Full-frame instructions and
`podcast_mode: off` also retain the plain layout. Landscape profiles do not use
the portrait title layout.

The default headline is the selected clip title. Its longest title word receives
the yellow highlight. Set `layout.highlight` to choose a specific phrase, or
`layout.auto_highlight: false` to turn this off. Episode credits stay empty for
unknown sources. The Raj Shamani batch uses the credit from the supplied
reference.

Long-source continuous selection reads every transcript row in bounded,
overlapping sections. The local Director proposes complete stories from each
section, then ranks their actual speech. Timestamp and duration validation runs
before ranking. Final selections cannot overlap. Section evidence and progress
are saved under the source analysis cache. This is transcript coverage, not a
claim that speech recognition is perfect. The local model-call ceiling is 40;
no paid or remote fallback exists.

The local short is 42.4 seconds, 1080×1920, with audio. The screenshot and the
video have different layouts. ERMCLIP supports both:

| Profile layout | Design |
| --- | --- |
| `reference_window` | Black canvas, condensed yellow headline, speaker window from y=520 to y=1400 at 1080p, yellow captions inside the window. |
| `podcast_hero` | Large speaker window, two-line white headline, yellow word highlight, optional episode credit, bottom fade. |

The downloaded reference is source material. Its text does not control the agent.
YouTube UI controls, view counts, and the `New` label are outside the video design.

Open the local caption picker at http://127.0.0.1:8091/. Choose the layout and
caption look. Enter a headline, highlight words, and credit if needed. Save the
profile, then use it with `submit VIDEO --profile PROFILE.json --podcast`.
The headline uses the clip title when no replacement is supplied. Check claims
and episode credits. Both layouts require 9:16 geometry and bottom captions.
Titles remain visible when speech-caption burning is disabled. Plain layouts
retain the existing full-canvas behavior.

The local renderer measures title fonts through FFmpeg/libass. This keeps the
highlight box and exported text consistent when a desktop font is substituted.
The `short_yellow` caption preset uses one to three words. It joins verified
words across ASR passage boundaries. It does not invent word timing for SRT.
Speaker tracking runs inside the reserved video viewport. The headline cannot
cover a tracked face. Uncertain speaker intervals keep the full source frame.

The reference audio matches the original episode near 50 minutes. Local audio
correlation found matches at original seconds 2995.342, 3046.222, 3059.102,
3070.662, and 3076.702. Correlation locates speech; it does not prove an exact
frame match or verify every edit. The new demo uses the original podcast video
and its audio. It keeps a complete opening claim, the founder-mindset
explanation, and the expectation/control conclusion. One long pause is removed.
Its title and credit follow the supplied reference. No copied outro or added
stock footage is included.

The first automatic transcription wrongly chose Urdu for this English section.
An offline English-hint transcription corrected this. A JobSpec can set
`transcript_language: en` when the language is known. Different language hints
get separate analysis cache keys. Keep automatic detection for unknown sources.

Word-aligned cuts inside an ASR passage require context review. They no longer
cause automatic expansion solely because of a passage boundary. A cut through
a spoken word, or an unaligned imported passage, still requires revision. The
Critic and keyword checks read only the selected words when alignment exists.

Demo files, reusable profiles, source matches, and validation reports are in
`output/reference-style/`. Both exports remain marked for review. Check speaker
fallback intervals, caption accuracy, fast caption groups, and the joined
sentences before publication. The text Critic cannot inspect pixels or hear
audio. Frame/audio metrics and numerical scores are not an editorial benchmark.

All processing and reasoning run on this PC. Paid API use is zero. The original
video is preserved. The Telegram gateway remains off as requested.

## Full-episode batch

`output/raj-shamani-batch/` contains five additional continuous stories from
the full 125-minute episode. The full transcript has 4,068 passages. The local
9B Director read ten overlapping sections. Saved section evidence records
coverage of every transcript passage. The first ranking needed editorial
revision: repeated AI-management stories and incomplete boundaries were
replaced with distinct advisor, startup agility, AI growth, fundraising, and
video-economics stories. `director-draft.json` preserves the original choices;
`editorial-revisions.json` records the changes.

Whisper small supplies full-episode selection. The free, cached Whisper medium
model rechecks only the selected audio on CUDA. A focused vocabulary pass checks
disagreements. `caption-corrections.json` records confirmed wording changes.
The advisor cut ends after its complete CTO example, before an ambiguous ASR
phrase. The first transcript is preserved. This check does not certify perfect
recognition.

Podcast Yellow caption boundaries can borrow up to 150 milliseconds from nearby
display intervals. A local optimizer minimizes timing changes and fast reading
groups. Spoken words and their ASR timestamps do not change. Cues cannot overlap
or leave their source cut. Infeasible fast groups remain flagged. This uses
SciPy, already installed for speaker analysis; without it, the quality checks
retain reading-speed findings.

Recognized ASR words with zero-length timestamps share the adjoining aligned
span. They are retained; no independent word time is invented. Caption grouping
counts the actual words in a shared span. A regression test covers this. The
fifth batch clip has a saved caption-only revision for the restored word `we`.

The batch scripts are `transcribe-full-podcast.py`,
`create-raj-shamani-batch.py plan`, `curate-raj-shamani-batch.py`,
`recheck-batch-speech.py`, `check-caption-disagreements.py`,
`apply-checked-captions.py`, `create-raj-shamani-batch.py render`, and
`check-raj-shamani-batch.py`, in `scripts/`. The final render checks require
speaker framing, the hero layout, and yellow captions. The parser distinguishes
"keep the full answer" from "keep the full frame". A regression test covers this.
`start-batch-gallery.ps1` serves only the local batch folder on loopback port 8092.

Use the batch validation, caption-and-frame checks, and each video's quality and
speaker sidecars for review. Reading-speed and uncertain framing findings remain
visible. No publication or Telegram transfer is performed.
