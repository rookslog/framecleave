# Changelog

## 0.2.0rc1 — 2026-09-16

- Default CLI slicing copies compressed video/audio for review, retaining intended
  ranges without automatic encoding fallback or PCM/reference caches.
- Separate selected, compatible-job assembly trims copied visible durations and
  encodes once at CRF16/18 with AAC; no joined intermediate movie.
- Review certificates/resume/verification report integrity/inventory, never native
  decoded equality. Existing explicit exact/lossless/compact contracts remain.
- Owned logical temporary-byte reservations and OS media limits enforce the review
  1.5× input ceiling, including reserved batch-parent metadata; persistent outputs
  and explicit legacy-mode caches are outside this ceiling.
- Quiet/default/verbose/debug output, parent JSONL events, aggregate status, private
  diagnostics, transition evidence and controlled worker-exit handling.

Engineering candidate: consumer-player/subjective-quality and general damaged-media
qualification remain open. CRF is not a final-size guarantee. No registry publication.

## Publication safeguards

- Private-derived labels, fingerprints, timings and results are local-only, including
  aggregate measurements. Public benchmark evidence is synthetic only.
- Release audits reject private evaluation artifacts; synthetic evidence remains
  available for reproducible checks.

## 0.1.0rc1 — 2026-09-15/16

Initial installable engineering candidate: temporal/geometric detector, separate review
candidates, canonical rational scene index and CSV, visual dry run, optional thumbnails,
verified exact splitting, lossless fallback, bounded batches, conservative resume, deep
verification and diagnostics. Includes original synthetic fixtures, source/build packaging and artifact-only release workflows.

Not an unattended-accuracy or macOS-27-certified release. Known held-out misses, motion
false positives, unsupported partial HDR/ancillary retiming and unmeasured target-platform
performance are explicit in the engineering report. No public publication performed.
