# Consequential decisions

**Status:** implemented, with release gates recorded separately. **Date:** 2026-09-15/16.

1. **Use decoded ordinals and rational PTS, not seconds/FPS.** A zero-based half-open
   partition is the stable API. This avoids VFR, rounding and one-frame ambiguity.
2. **Separate candidate generation, verification and human review.** Duplicate-aware
   visual-update context addresses a measured adaptive-baseline failure. Flow/SIFT and
   photometric checks reduce motion/lighting errors but do not prove continuity. Review
   candidates remain distinct from accepted edits; no calibrated percentage is invented.
3. **Retain both sides of short interstitials.** Dropping minimum-length scenes would
   silently discard source frames or glue unrelated recordings together.
4. **Freeze detection before held-out review.** Local evaluation records stay outside the repository. Held-out labels must not tune the detector.
   The annotation process is provisional and candidate-assisted; it is not an exhaustive gold set.
5. **Prefer measured native-CPU primitives to an unavailable neural runtime.** This is
   not evidence that lightweight geometry outperforms learned models. Weight acquisition,
   license review and target execution remain outstanding comparative work.
6. **Verify every decoded output frame, not just the first one.** This caught MOV final
   packet discard behavior that a successful encoder exit would have missed.
7. **Use verified whole/video copy with whole-scene lossless fallback.** A hybrid GOP
   join was not established as correct. No keyframe snapping or unverified “lossless copy” claim.
8. **Use native-precision PCM for partial audio.** Keeps sample values and clocks exact
   without lossy codec generations; costs disk space and changes audio codec/container.
9. **Reject unsupported preservation cases.** Full per-frame audits catch late HDR and
   changing properties that a stream-header check misses. General HDR splitting is not shipped.
10. **Keep system FFmpeg external.** Native Homebrew installation and explicit capabilities
    avoid bundled-codec release obligations and an npm wrapper. Python dependencies are pinned.
11. **Use the actually tested OpenCV distribution.** The shared environment's headless
    metadata was misleading; byte hashes matched desktop OpenCV. The isolated install contains
    exactly one variant. Smaller headless packaging is not claimed as verified.
12. **Keep output ownership and privacy explicit.** Atomic, no-clobber finalization;
    source/config-bound resume; all reports/logs/media remain local. Private footage never
    enters Git or release artifacts. Content-derived annotations, hashes and measurements stay local too.
13. **Do not label missing evidence as success.** Native macOS 27, VideoToolbox and learned
    inference results cannot be inferred from Linux. The result is an engineering RC, not
    acceptance of all original release goals.
