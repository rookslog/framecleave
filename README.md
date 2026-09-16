# FrameCleave

Local hard-cut detection and **fast compressed review slices**, with one optional final encode. A real Python
CLI, with JSON/CSV scene indexes, a script-free visual dry run, optional thumbnails,
bounded batch processing, resume validation, and independent export verification.

**Status: 0.2.0rc1, an engineering release candidate—not an unattended accuracy guarantee.**
The detector still has documented misses and false positives on private phone/webcam
footage. Two held-out edits were flagged for review rather than automatically cut.
Use `inspect` before important exports. Current generated-media tests run locally on
Apple Silicon with FFmpeg 9.0.1; complete macOS-27/player qualification is still open.
See [engineering report](docs/ENGINEERING_REPORT.md) and [evaluation](docs/detector-evaluation.md).

## Install on Apple Silicon

Use a native arm64 Terminal/Python environment, not Rosetta. Install system FFmpeg
with H.264/HEVC decoders and libx264/libx265 for optional assembly:

```sh
brew install ffmpeg uv
uv tool install --python 3.13 ./framecleave-0.2.0rc1-py3-none-any.whl
framecleave doctor
```

Alternatively, from this source directory: `uv tool install --python 3.13 .`. Python 3.11 or later
and FFmpeg 7 or later are required. The 7.1.x family used in the original delivery
is historical; this feature's local tests
exercise FFmpeg 9.0.1 on arm64. The package depends only on NumPy and OpenCV.
No neural weights are downloaded; no npm wrapper, telemetry, cloud processing or bundled
system FFmpeg is included. The package name is provisional and has **not** been
registered or published to a package registry.

The runtime versions are pinned to the versions evaluated here, not claimed to be
the latest available releases. Native macOS arm64 wheels exist for both dependencies.
OpenCV's wheel contains its own third-party components; see the license audit.

## Everyday usage

```sh
# Detect, index and review. Creates report.html and exact-ordinal thumbnails, no clips.
framecleave inspect "recording.mkv" -o "review"
open "review/report.html"

# Export the proposed index to a new directory; do not rerun detection.
framecleave split "recording.mkv" --index "review/scene-index.json" -o "clips" --thumbnails

# Direct automatic detection and splitting (review-first is safer).
framecleave split "recording.mkv" -o "clips-direct"

# Identical dry-run behavior from the split command.
framecleave split "recording.mkv" -o "another-review" --dry-run

# Explicit corrections: cuts are the first decoded frames of the new shots.
framecleave split "recording.mkv" --cuts 123,456,900 -o "corrected"

# Check review-file integrity and stream inventory (not exact decoded boundaries).
framecleave verify "recording.mkv" "clips/scene-index.json"

# Keep selected scenes, trim preview edges, and encode the result once.
framecleave assemble "clips/scene-index.json" --scenes 1,3,5 -o "selected.mp4" --crf 18

# Select across compatible jobs; indexes determine job numbers, selection sets playback order.
framecleave assemble "job-a/scene-index.json" "job-b/scene-index.json" --scenes 1:3,2:5 -o "joined.mp4"

# Directory or multiple-file batch. A broken file does not abort other files.
framecleave batch "incoming" -o "batch-output" --recursive --jobs 2 --dry-run
framecleave batch "incoming" -o "batch-output" --recursive --jobs 2 --resume
```

To promote a single-file inspection in place, repeat the same input/configuration/
boundary options with `split --resume -o review`, without adding `--index`. Changing
configuration, explicit cuts, imported-index content, tool version or export mode
requires a new output directory. JSON results use `--json`; progress goes to stderr.
`--quiet`, `--verbose`, `--debug`, subcommand `--help`, and `doctor --json` are available.

## Default review copying and final assembly

`split` and `batch` default to `--mode review-copy`. Partial H.264/HEVC scenes use
input-seek MP4 **video and audio packet copying**. AAC stays AAC; no lossless audio,
full-source PCM cache, reference encode or per-scene encoder is used. Unsplit sources
are copied byte-for-byte in their original container. Failed copying fails that job;
it never silently switches to encoding. Other source codecs or MP4-incompatible audio
can be refused. Earlier DTS warnings in `auto` meant a rejected copy attempt followed
by lossless encoding; that recovery caused the large outputs, not duplicated originals.

The index retains intended frame/PTS ranges. Physically copied packets can include GOP
preroll or extra trailing frames. These are review/selection clips, **not frame-exact
or sample-exact exports**. Certificates and `verify` distinguish file integrity/stream
inventory from decoded equality. Starts decoded in the tested H.264/HEVC cases; universal
QuickTime/VLC playback, arbitrary damaged endings and open-GOP recovery are not promised.

`assemble` requires review-copy certificates and unchanged copied clips, not available
originals. It independently decodes each selection, trims the recorded visible duration,
concatenates in your order and encodes once with the same video codec family, medium
preset, CRF 18 (or 16 for higher quality) and AAC 128 kb/s per audio track. It writes no
joined intermediate movie or PCM cache. Compatible geometry, pixel/color properties and
audio layouts are required; unsupported HDR and normalization are refused. Joins are
not sample/pixel-exact. CRF controls quality, **not a fixed final byte size**.

Published review clips remain available for selection; assembly never deletes them.
It writes a new MP4 plus `.assembly.json` and private per-attempt `.diagnostics-RUN.log`
sidecars. Failed attempts keep their logs without blocking retry to an unpublished target.
See [research and measured size/timing results](docs/streamcopy-research.md).

### Temporary storage ceiling

Review processing limits owned **logical temporary bytes** to `floor(1.5 × input bytes)`:
unfinished media, filter scripts, metrics and atomic metadata writes. Writes reserve
space before growth; FFmpeg uses an OS file-size ceiling on macOS/Linux. Batch workers
cannot borrow from one another; a reserved parent-reporting allowance composes within
the total input ceiling. The allowance can cause an earlier refusal instead of overshoot.
Final assembly has the same ceiling against the unique selected copied-input bytes.

Published clips, indexes, reports, thumbnails and diagnostic/event logs are persistent
outputs, not disposable temporary data. Source files and existing outputs are excluded
and untouched. This is not a filesystem-block, RAM, free-space or total-output quota.
Disk exhaustion and budgets fail processing rather than lowering quality or deleting
completed media. Explicit exact/compact modes retain their old, unbounded PCM/reference
temporary storage behavior. Uncatchable kills can leave owned partials that require
operator inspection; automatic cleanup/adoption is deliberately not performed.

## Explicit exactness and preservation modes

Scene intervals are zero-based decoded frame ordinals **[start, end)**. A cut at 123
means frame 122 ends the old shot and frame 123 begins the new one. Actual integer
PTS and rational time bases are stored; cuts are never silently snapped to keyframes.

`--mode auto` retains the original exact export policy:

1. Copy an unsplit whole source byte-for-byte, then decode-verify the video.
2. Try video stream copying at eligible keyframe boundaries. Keep it only if decoding
   proves the exact frame count, every native decoded pixel, every PTS, and endpoint.
3. Otherwise losslessly re-encode the **whole scene**, using the source video codec
   (H.264/HEVC; restricted FFV1), resolution, pixel format/bit depth and known color
   attributes. Every decoded output frame is compared to the original. No hybrid GOP
   splice or unverified hardware shortcut is used.

For partial scenes, audio is decoded once into native-precision PCM and sliced at
original sample boundaries. The overlapping samples and stream offset are verified
again after export. AAC therefore normally becomes PCM, not another lossy AAC encode.
H.264/HEVC scenes use MOV; whole-file copies retain their original container. Lossless
encoding can be **much larger** and slower than the compressed source. H.264 lossless
profiles may not play in every consumer player; use an FFmpeg-compatible player.

An export certificate records method, hashes, source ordinals, PTS equality, native
pixel equality, audio sample equality, synchronization tolerance, attributes and any
failed copy attempt. Unsupported HDR/Dolby Vision, interlacing, dynamic properties,
subtitle/data/chapter retiming or incompatible container constraints are **rejected**,
not silently discarded. Whole-file byte copying preserves all original streams.

The review thumbnails are downscaled RGB images, not a promise of HDR color-managed
preview. See [media policy](docs/cutting-strategy.md) for the exact limitations.

### Experimental compact export

Explicit `--mode compact` is not the review default. Compact
tries independently verified exact stream copy, then same-codec H.264/HEVC software
re-encoding at CRF 18/medium. Video is intentionally lossy: certificates report
`pixel_equality: not_applicable` for re-encoding, never native-pixel equality.

Compact preserves native audio samples: supported 16-bit integer streams use verified
ALAC; float, wider-integer, or unsupported-layout streams retain native PCM. AAC-decoded
float audio therefore stays PCM, with its codec and selection reason in the certificate.
Audio size can still exceed the original compressed audio.

Compact content is checked against an independent exact-frame reference encode, with
rational timing/endpoints, preserved properties, and SSIM/PSNR evidence. This adds a
second encode and temporary disk usage. Reference replay requires the recorded FFmpeg
build and encoder-thread settings; `verify --threads` controls decoding resources only.

### Transition annotations

Inspection records evidence for scenes under 30 frames, examining every downscaled
frame plus neighboring context and per-channel interval audio RMS. Stable neutral
cards may be labeled `transition_candidate`; active/unknown audio, overlays, changing
uniform content, or missing two-sided context require review. Evidence is scoped to
the generic neutral-card classifier, not a qualified private-specific template family.
Classification never omits frames or changes the analysis partition. The default
editorial action is keep, and changed annotation content blocks resume.

## Outputs and safety

```text
job/
  scene-index.json        # versioned, exact rational timeline and proposed scenes
  scenes.csv             # convenient tabular index
  report.html            # local-only report, no scripts or external assets
  analysis-metrics.npz   # compact local diagnostic signals, not source frame dumps
  diagnostics.log        # decoder/export command diagnostics; contains local paths
  state.json             # resumable source/configuration/certificate manifest
  run-summary.json
  scenes/0001.mp4         # whole-file copies retain the source suffix
  certificates/0001.json
  thumbnails/frame-000000123.jpg
```

New job directories are owner-only (0700); existing directory permissions are respected.
Existing outputs are not overwritten. Verified completed files are reused on resume
only after content-digest validation. `verify` follows the recorded policy: review
integrity/inventory, or full decoded comparison for the explicit exact modes.
Interrupted temporary output is removed when Python can unwind; an uncatchable kill
can leave scratch/partial files. Uncertified orphan output is not silently adopted or
overwritten. Keep the source unchanged while processing. Reports, indexes, logs and
thumbnails can contain private content or paths—keep the **entire job directory** private.
No source video or private thumbnails are included in this repository or package.

## Configuration

Settings are explicit, not read implicitly from the current directory:

```toml
[framecleave]
threads = 2
analysis_width = 128
analysis_height = 96
detector = "temporal"
context_updates = 12
min_change = 4.0
```

Pass `--config path.toml`. Unknown keys and invalid ranges are errors. Changes can
alter detection; record/re-evaluate them. The other detector names (`pixel`,
`histogram`, `adaptive`) are transparent comparison baselines, not PySceneDetect aliases.

## Development and release

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
python -m build
```

Tests generate their own non-private fixtures. Private evaluation data stays local. Reproduction scripts live in
`scripts/`; see [benchmark instructions](benchmarks/README.md). Release workflows build
artifacts only; they do not publish packages or create public repositories.
