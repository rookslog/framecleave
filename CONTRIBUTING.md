# Contributing

Use Python 3.11+, system FFmpeg 7+ with libx264/libx265, and a fresh virtual environment.
Install `.[dev]`, run `pytest`, `ruff check .` and `ruff format .`, then build a wheel and
sdist with `python -m build`. Pin runtime dependency changes and rerun detector evaluation.

Keep source videos, images, media caches, logs with private paths and model weights out
of commits. Tests generate original fixtures. Existing annotations are provisional;
submit independently reviewed annotations with a clear content hash, provenance, frame
semantics and permission, rather than private media. An index/report may itself be private.

A detector change needs separate FP/FN counts, exact offsets, held-out evidence and error
inspection. Do not quietly change thresholds to erase a held-out failure. A media change
needs decoded native-pixel/PTS and audio-sample verification, including one-frame and VFR
cases. Exit-code success and approximate thumbnail similarity are not export proof.

Report security-sensitive parser or path-handling bugs privately to the repository owner
once a remote exists. Do not post confidential footage, credentials or unredacted logs in
public issues. Treat malformed third-party media as untrusted and keep FFmpeg patched.

This release has no independent code review or native macOS sign-off. Local tests are
not a substitute for those gates. See `docs/release.md` before publishing anything.
