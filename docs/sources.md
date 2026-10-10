# Technical references checked on 2026-10-10

- [Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/): skill frontmatter, external directories, and gateway use. Installed source and CLI help were inspected locally for this specific build.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): local word timestamps, CPU/GPU execution, and CUDA/cuDNN requirements.
- [YouTube video resource](https://developers.google.com/youtube/v3/docs/videos): tag character counting, including commas and quotation marks for tags with spaces.
- [OpenCV 4 to 5 migration](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration): Haar classifiers moved to the contrib module in OpenCV 5. ERMCLIP uses OpenCV 4 headless.

No free-tier claim or paid-provider adapter was enabled. The user selected local-only reasoning.
