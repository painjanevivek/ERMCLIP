# Editorial benchmark v1

The benchmark starts as a schema and rating protocol. No representative human-rated video set was supplied, so there is no measured quality improvement or calibrated threshold.

Add only media you own or may use. Record its fingerprint, task, selected timeline, independent human ratings, and reviewer comments in `benchmarks/v1/ratings.json`. Include continuous explanation, targeted topic, compilation, humour, weak opening, incomplete ending, repetition, and difficult framing examples.

Use at least two independent reviewers when feasible. Rate instruction relevance, narrative coherence, hook/pacing, value, visuals, and audio/subtitles from 0 to 100. Mark hard violations separately. Do not show reviewers the automatic scores before they rate the video.

Compare AI scores to mean human scores and report mean absolute error, false-pass rate, and inter-reviewer disagreement. Keep a holdout set. Report changes only when the same benchmark and test conditions support them. User feedback can be deleted through the CLI.
