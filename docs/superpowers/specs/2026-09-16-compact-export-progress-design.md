# Compact Export, Progress, and Editorial Planning Design

- **Status:** Stream-copy-first adjustment implemented and locally checked; [PR #1](https://github.com/rookslog/framecleave/pull/1), not merged.
- **Date:** 2026-09-16
- **Audience:** FrameCleave maintainers and contributors
- **Post-read action:** Read the clarification and research checkpoint before further implementation. Do not execute the old per-scene compact-default gate without amending its dependent contracts.
- **Implementation plan:** [Compact Export, Progress, and Editorial Planning Plan](../plans/2026-09-16-compact-export-progress-plan.md)

## Current owner clarification and research checkpoint

The owner restated the longstanding intended workflow: fast audiovisual packet-copy slices for review/selection, then one final encode of selected pieces, trialed at CRF16/18. Imperfect review edges are acceptable. The prior sample/pixel-exact fallback design overconstrained this intent; it remains an implemented optional contract, not the desired review acceptance gate. Observability work and explicit exact/lossless modes remain useful and their guarantees are not weakened.

Bounded FFmpeg research and the requested Astra consultation are complete; see [root findings](../../streamcopy-research.md) and [advisor response](../../astra-streamcopy-advice.md). Input-seek MP4 copies were independently decodable at their starts in the checked cases, and trimmed decoded assembly supported nonadjacent selection with one encode. These are bounded observations, not general player/quality guarantees or a demonstrated hard temporary-space quota.

The owner approved implementation. Ordinary CLI slicing now defaults to audiovisual
`review-copy`; library orchestration defaults remain `auto` for explicit compatibility.
Review certificates bind source/segmentation/intended ranges and output integrity,
never native decoded equality. Exact/compact modes retain their previous contracts.
`assemble INDEX... --scenes 1,3` (or `1:3,2:5` across compatible jobs) independently
decodes copies, trims recorded visible durations and encodes once at CRF16/18 plus AAC.
Originals are not required for assembly. No automatic encoding fallback or PCM/joined
reference cache is created by this default workflow.

Owned logical temporary bytes, including partial media/scripts/metrics/atomic metadata,
are bounded to floor(1.5× input bytes). Published outputs/logs and filesystem block
overhead are excluded. Batch-parent allowances are reserved inside per-input ceilings;
assembly uses unique selected copied-input bytes. Explicit legacy-mode caches remain
unbounded. A budget can refuse work, never delete published clips or lower quality.
Final output bytes are CRF-dependent, not a guaranteed ratio. Consumer-player, quality,
general delayed-audio/VFR/damaged-tail and mid-IPC hard-kill qualification remain open.

Transition evidence remains, with explicit selected-scene omission during assembly.
Automatic collapse, standalone export plans, constrained keyframe movement and hybrid
GOP work are intentionally deferred. The remaining sections preserve the original
approved design/history; this amendment and the owner's clarification govern current behavior.

## 1. Goals and approved decisions

FrameCleave will improve three related surfaces without collapsing their contracts:

1. Replace noisy console logging with structured progress events and presentation modes.
2. Add practical compact export and make it the default after its quality contract is accepted.
3. Add review-gated transition omission and optional constrained keyframe planning through a separate export plan.

The approved user-facing decisions are:

- An interactive default uses one refreshed status line.
- Recovered export attempts appear as a live counter and one concise completion note.
- `-q` and `--quiet` retain their current errors-only behavior.
- Verbose mode prints durable milestone lines. Debug mode adds development diagnostics.
- Batch runs persist compact structured events in `batch-events.jsonl`.
- Compact export becomes the practical default; exact lossless export remains explicit.
- Transition omission is represented as an editorial decision, not a detector rewrite.
- Keyframe movement is optional, bounded, auditable, and subordinate to semantic boundaries.

## 2. Evidence and problem statement

### 2.1 Console output

The current CLI maps ordinary library log records directly to stderr. Per-scene messages produce many permanent lines. A failed internal stream-copy attempt is logged as a warning even when a later lossless attempt succeeds and the scene is certified. The result looks terminal although processing continues correctly.

The current batch summary becomes useful only after a whole source file finishes. It does not provide a durable event history or a concise view of active work.

### 2.2 Storage expansion

Lossless whole-scene re-encoding can substantially increase storage relative to compressed originals. Source-specific sizes and timings stay local.

This result follows the current contract: arbitrary decoded-frame cuts are re-encoded losslessly when verified compressed-packet copying is unavailable. It is not duplicated media, but it is operationally impractical as an unnoticed default.

### 2.3 Transitional micro-scenes

Short transitional intervals can be worth omitting editorially, but visual uniformity alone does not establish that content or audio is disposable. Keep omission explicit and review-gated. A nearest-keyframe rule can move a boundary through meaningful adjacent content, so it must not silently replace semantic boundaries.

## 3. Compatibility and preservation contracts

FrameCleave must keep four claims separate:

1. **Frame-exact boundary:** the output represents the requested decoded source ordinals.
2. **Pixel-exact video:** every decoded output frame equals the source frame at native precision.
3. **Sample-exact audio:** decoded output samples and their source-clock placement equal the requested source interval.
4. **Compact encode:** the output is intentionally generation-lossy under a named quality policy.

Compact output may satisfy the first claim without satisfying the second. A certificate and success message must never imply native-pixel equality for compact output. Audio equality depends on the selected compact audio policy and must be independently stated.

Existing modes remain compatible:

- Explicit `--mode auto` retains its current copy-then-lossless behavior during the compatibility period.
- `--mode lossless` retains full-scene lossless encoding.
- `--mode copy-only` remains fail-closed and never snaps boundaries.
- A new `--mode compact` tries a verified exact stream copy when eligible, then uses compact re-encoding.
- After compact acceptance, omitting `--mode` selects compact. This default change requires release-note and version treatment.

Existing certificates remain readable under their original contract. Resume never reinterprets an old certificate or changes a completed job's policy.

## 4. Structured progress-event module

### 4.1 Seam and interface

Media, export, workflow, and batch code emit domain events through one small interface:

```python
class ProgressSink(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...
    def close(self, result: dict | None = None) -> None: ...
```

Callers report facts rather than formatted terminal strings. The progress module owns aggregation, throttling, rendering, JSONL serialization, and multiprocessing transport.

Each event contains:

- schema version;
- run, job, scene, and attempt identifiers when applicable;
- producer sequence number;
- event type and processing phase;
- completed, total, and unit when known;
- elapsed time;
- outcome and stable reason code;
- recovery state;
- a relative diagnostics reference when details exist.

Useful phases include discovery, probing, analysis, boundary detection, reference preparation, encoding, verification, finalization, report generation, and completion.

Unknown totals remain unknown. The renderer must not invent an overall percentage or time remaining from insufficient evidence.

### 4.2 Event semantics

An unsuccessful attempt is not a failed scene. Emit `attempt_rejected` immediately. Increment the recovered-fallback count only after another attempt succeeds. Emit `scene_failed` only after all allowed attempts are exhausted.

Lifecycle events are durable decisions, not per-frame chatter. High-frequency frame progress may be coalesced or rate-limited. Start, terminal outcome, fallback, interruption, and certification events may not be dropped.

### 4.3 Multiprocessing

The parent process owns console rendering and the batch JSONL writer. Spawned workers send bounded structured events over an explicit queue. Each worker retains its per-job diagnostics file.

The parent reconciles worker exit with durable state. A worker that exits without a terminal event produces an explicit `worker_lost` event and is not presented as success. Queue shutdown drains terminal events before closing when Python can unwind normally.

The event stream supplements job state and certificates; it is never the sole evidence that output was certified.

## 5. Terminal modes and diagnostic retention

| Mode | Interactive terminal | Non-interactive stderr | Persistent diagnostics |
|---|---|---|---|
| Quiet | Errors only | Errors only | Normal private job diagnostics and state |
| Default | One refreshed status line plus terminal failures and final summary | Rate-limited milestone lines | Batch events and per-job diagnostics |
| Verbose | Permanent phase, scene, fallback, and completion lines | Same | Same |
| Debug | Verbose output plus commands, bounded FFmpeg tails, and tracebacks | Same | Same, with explicit truncation records |

The default batch line should fit ordinary terminals and degrade by dropping optional fields from right to left. Its information order is:

```text
[files completed/total] active file · phase · scene progress · elapsed · recovered fallbacks
```

The renderer clears or terminates the active line before printing a permanent error or final summary.

`--json` continues to produce exactly one machine-readable result on stdout. Presentation remains on stderr. Quiet plus JSON still emits the requested result object.

Debug output can expose private paths and media metadata. Help text and the initial debug message must say so.

Current FFmpeg error capture retains bounded tails rather than unlimited stderr. The redesigned diagnostics contract must state its bounds, write a truncation marker when applied, and avoid accumulating unbounded subprocess output in memory. Full per-frame decode chatter is not retained by default.

## 6. Batch event log and status surfaces

`batch-events.jsonl` is private job metadata. The parent appends one compact JSON object per durable event. It contains no image data and no copied FFmpeg stderr. Source identity uses a stable local job identifier plus a relative diagnostic reference; unnecessary absolute paths are excluded.

`batch-summary.json` remains the current-state digest and gains:

- pending, active, succeeded, failed, and interrupted counts;
- last update time;
- active phase summaries;
- recovered fallback count;
- current and peak observed output bytes;
- relative event-log location.

The event writer flushes terminal events. A partial final JSONL line after an uncatchable kill is ignored by readers and reported as truncated rather than preventing resume.

## 7. Compact export policy

### 7.1 Initial strategy

The first compact implementation performs a full-scene software re-encode for arbitrary boundaries. It preserves:

- exact requested source ordinals;
- rational relative presentation timing and final endpoint;
- resolution, sample aspect ratio, orientation, and supported color properties;
- source bit depth and chroma layout when the selected encoder supports them;
- stream ordering and explicitly supported audio behavior;
- decodability and container integrity.

The initial implementation does not splice newly encoded edge GOPs onto copied interior GOPs.

### 7.2 Verification and certificates

Verification becomes policy-aware. Every certificate records:

- certificate schema version and export policy digest;
- method and encoder profile;
- requested source range;
- decoded output frame count;
- relative PTS and endpoint checks;
- preserved media properties;
- decode success;
- pixel-equality status: `true`, `false`, or `not_applicable`;
- audio-equality status and audio policy;
- output digest and byte size;
- rejected attempts and recovery result;
- source, scene-index, and export-plan digests.

Compact output never reports `all_native_pixels_equal: true`. Runtime checks establish structural correspondence and policy conformance, not mathematical perceptual equivalence.

The initial implementation independently re-encodes the full-decoded requested frame-ordinal interval under the same compact policy and compares its decoded hashes with the output. This catches content substitution, reordering, and duplication without using SSIM/PSNR as a correctness threshold. It adds a second encode and requires the recorded encoder build and thread configuration for replay; calibration includes that cost. SSIM/PSNR remain measured quality evidence.

Generated adversarial fixtures must catch substitution, reordering, duplication, omission, wrong endpoints, property loss, and timing drift. Private-corpus evaluation measures quality and size but is not committed.

### 7.3 Quality calibration gate

Compact cannot become the no-flag default until a checked-in benchmark procedure compares candidate profiles across generated fixtures and locally held private reports. The selected policy must record:

- codec and software encoder;
- rate-control setting and preset;
- output pixel format and bit depth;
- container;
- audio codec and synchronization policy;
- measured size ratio, encode time, compatibility observations, and quality metrics;
- known failure/refusal cases.

The calibration result is a release decision, not a hidden constant. Source-code defaults, help, documentation, certificates, and resume fingerprints change together.

The initial candidate matrix uses the source codec's software encoder at CRF 16, 18, and 20, with one fixed preset per codec so the first comparison isolates quality level. Every candidate must pass structural verification. The evidence bundle includes private visual review plus measured size and runtime. The winning candidate is selected from that evidence before the default changes.

### 7.4 Audio decision

Compact audio policy is independent from compact video. The candidates are:

- native-precision PCM, preserving the current sample contract but often large;
- a verified lossless audio codec, preserving decoded samples while reducing some storage;
- a compact lossy codec, requiring explicit delay, padding, timing, quality, and non-equality semantics.

Compact partial-scene audio uses the approved `alac-or-pcm` policy. The initial verified ALAC path covers native 16-bit integer samples in supported ALAC channel layouts. Other native formats, including AAC-decoded floating-point samples and full-width integer PCM, retain their native PCM encoding. Each stream records the selected codec and reason; decoded sample equality and timing are required in both paths. Lossy compact audio is deferred.

Owner amendment (2026-09-16): native PCM fallback was approved after a generated local AAC-to-ALAC round trip changed decoded float samples. This preserves the native sample-equality guarantee while compact video addresses the measured video-storage expansion. Quantized ALAC and deferral were not selected. Calibration must show the remaining PCM contribution to size.

## 8. Immutable analysis index and export plan

`scene-index.json` remains the immutable, complete, contiguous analysis partition. Detection evidence, accepted cuts, and review candidates keep their existing meaning.

Editorial changes live in a new `export-plan.json`. Its versioned schema records:

- source and scene-index digests;
- tool and planner versions;
- encoding and audio policy digests;
- protected semantic boundaries;
- transition annotations;
- exact owner-approved omission ranges;
- requested and effective boundaries;
- signed frame and rational-time displacement;
- rejected keyframe candidates and reason codes;
- retained-range coverage;
- approval provenance and time;
- a plan digest used by execution and resume.

The plan is created before export and validated independently. Changing classifier versions, quality profiles, omission masks, or snap limits produces a different plan digest and cannot silently reuse completed output.

## 9. Transition classification and review

The first release uses three classifications:

- `transition_candidate`;
- `ordinary`;
- `ambiguous`.

Short duration triggers examination, not deletion. Candidate evidence can include all-frame temporal stability, luminance and chroma distribution, spatial texture, edge density, template similarity scoped to a demonstrated transition family, and neighboring context. Endpoint similarity alone is insufficient.

The report presents candidate evidence and exact frame ranges. The initial release requires explicit keep/collapse/omit approval before generating an export plan. Batch selection is available with a per-candidate override. Automatic omission of a known template is a later policy that requires an evaluated false-positive bound and explicit owner enablement.

Operations have distinct meanings:

- **Classify:** attach evidence without changing media or cuts.
- **Recommend omission:** propose an exact source interval.
- **Approve omission:** add that exact interval to an export plan.
- **Merge:** remove a segmentation boundary while retaining all frames.
- **Omit:** exclude approved frames from newly generated outputs.
- **Concatenate across an omission:** produce a discontinuous source mapping; deferred initially.

The source file and prior outputs are never deleted. First and last micro-scenes lack two-sided context and therefore receive reduced confidence. A visually uniform interval with meaningful audio remains ambiguous unless the owner explicitly approves omission.

## 10. Constrained keyframe planning

Exact boundaries remain the semantic default. Keyframe planning is an optional export optimization applied only after transition decisions are resolved.

The planner evaluates boundaries jointly and enforces:

1. Every output interval is nonempty, ordered, and within the source.
2. No effective boundary crosses a protected semantic boundary.
3. Frames outside approved omission ranges appear exactly once.
4. No real-content frame moves between scenes solely for codec convenience.
5. Every movement satisfies configured absolute frame and rational-time limits.
6. Equal effective boundaries cannot silently collapse a scene.
7. No eligible keyframe means exact compact encoding or explicit refusal.

Distance percentage is not the primary limit because it allows large shifts in long scenes and almost none in micro-scenes. Keyframe movement is allowed only inside an approved transition mask and is capped at the smaller of 30 frames or one second. The first release accepts lower limits but refuses values above either cap.

Candidate keyframes are intersected with each boundary's allowed region, omission mask, protected neighbors, and distance bounds. A deterministic optimization selects an ordered noncollapsing solution. Its objective and tie-breaker are recorded in the planner version.

Keyframe flags establish eligibility only. Every stream-copy result still undergoes independent frame, timing, endpoint, property, and audio verification.

## 11. Privacy, resume integrity, and resource safety

All reports, annotations, event logs, diagnostics, and plans remain private job artifacts because they can contain paths and content-derived information. New job directories remain owner-only. Existing-directory permissions continue to be respected and reported.

JSONL and console events never contain thumbnail data or raw media. Debug mode is explicitly private. Diagnostic symlink refusal and contained-path checks remain mandatory.

Disk pressure includes final media, partial files, reference hashes, temporary audio, and concurrent worker scratch. Compact size alone is not a peak-space estimate. The implementation adds:

- pre-run free-space reporting;
- current and peak observed job bytes;
- low-space terminal events;
- catchable cancellation that preserves certified outputs and resume state;
- disk-full tests for diagnostics, partial media, certificates, and summaries.

An uncatchable kill can still leave an uncertified partial or orphan. Resume refuses it rather than adopting or overwriting it.

## 12. Staged rollout and version control

Implementation proceeds as independently reviewable commits on one feature branch:

1. Structured event model, adapters, and output-mode tests with no media-policy change.
2. Parent-owned batch JSONL and multiprocessing transport.
3. Explicit compact mode, policy-aware certificates, and verification.
4. Quality/audio calibration evidence and owner decision.
5. No-flag compact default plus documentation and the `0.2.0rc1` version transition.
6. Transition annotations and report controls.
7. Versioned export-plan schema and review-gated omission.
8. Constrained keyframe planner and refusal fixtures.

The pull request remains draft until each shipped slice passes focused and full checks. If later slices prove too large, the branch may produce stacked pull requests without changing the artifact contracts.

## 13. Test strategy

### Progress and presentation

- fake-clock event aggregation;
- pseudo-TTY width and redraw behavior;
- non-TTY newline behavior;
- quiet, JSON, verbose, and debug channel separation;
- recovered versus exhausted attempts;
- queue ordering, throttling, worker loss, cancellation, and drain;
- truncated JSONL recovery;
- diagnostic-write failure without fabricated success.

### Compact export

- one-frame and very short scenes;
- arbitrary non-keyframe cuts;
- VFR and nonzero timestamps;
- ten-bit video, color properties, and rotation;
- multiple and delayed audio streams;
- deliberate frame substitution, omission, duplication, and reordering;
- corrupted and truncated output;
- certificate vocabulary that cannot claim lossless equality for compact media;
- measured size and quality reports on generated fixtures.

### Export planning

- property tests for ordered nonempty ranges;
- no unauthorized gaps or duplicates;
- exact coverage outside approved omissions;
- protected-boundary preservation;
- maximum displacement and deterministic tie-breaking;
- rejection when a nearby keyframe lies across real content;
- transition negatives including legitimate dark scenes, fades, flashes, overlays, and meaningful audio;
- first and last transition candidates;
- stale source, index, policy, and plan digest refusal.

Private reports remain a local holdout. Only aggregate results and privacy-safe conclusions may enter the repository.

## 14. Explicitly deferred work

- Hybrid edge-GOP encoding and copied-interior splicing.
- Automatic deletion of every short or uniform scene.
- Silent keyframe snapping.
- Concatenating noncontiguous retained ranges into one output.
- A generalized semantic transition detector beyond evaluated families.
- Unlimited raw subprocess logging.
- Hardware encoding as a default or preservation claim.

## 15. Calibration decision gate

The architecture and initial defaults are approved. Implementation may build the candidate matrix and evidence pipeline, but the no-flag default does not change until the measured CRF 16/18/20 comparison is reviewed and one candidate is selected. That selection is recorded in the benchmark evidence, changelog, help, certificates, and resume fingerprint in the same change.
