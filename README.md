# FrameCleave

Local hard-cut detection and **decode-verified, frame-exact** splitting. A real Python
CLI, with JSON/CSV scene indexes, a script-free visual dry run, optional thumbnails,
bounded batch processing, resume validation, and independent export verification.

**Status: 0.1.0rc1, an engineering release candidate—not an unattended accuracy guarantee.**
The detector still has documented misses and false positives on private phone/webcam
footage. Two held-out edits were flagged for review rather than automatically cut.
Use `inspect` before important exports. macOS 27 / Apple-Silicon execution has not
been measured in the development environment; an arm64 validation workflow is provided.
See [engineering report](docs/ENGINEERING_REPORT.md) and [evaluation](docs/detector-evaluation.md).

## Install on Apple Silicon

Use a native arm64 Terminal/Python environment, not Rosetta. Install system FFmpeg
with H.264/HEVC lossless encoders and an isolated Python tool installer:

```sh
brew install ffmpeg@7 uv
export PATH="$(brew --prefix ffmpeg@7)/bin:$PATH"
uv tool install --python 3.13 ./framecleave-0.1.0rc1-py3-none-any.whl
framecleave doctor
```

Alternatively, from this source directory: `uv tool install --python 3.13 .`. Python 3.11 or later
and FFmpeg 7 or later are required. The explicit `ffmpeg@7` PATH above selects the
7.1.x family exercised here; the current Homebrew default (9.0.1 at research time)
has not been executed in this environment. The package depends only on NumPy and OpenCV.
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

# A full, independent decode check of the resulting media.
framecleave verify "recording.mkv" "clips/scene-index.json"

# Directory or multiple-file batch. A broken file does not abort other files.
framecleave batch "incoming" -o "batch-output" --recursive --jobs 2 --dry-run
framecleave batch "incoming" -o "batch-output" --recursive --jobs 2 --resume
```

To promote a single-file inspection in place, repeat the same input/configuration/
boundary options with `split --resume -o review`, without adding `--index`. Changing
configuration, explicit cuts, imported-index content, tool version or export mode
requires a new output directory. JSON results use `--json`; progress goes to stderr.
`--quiet`, `--verbose`, subcommand `--help`, and `doctor --json` are available.

## Exactness and preservation

Scene intervals are zero-based decoded frame ordinals **[start, end)**. A cut at 123
means frame 122 ends the old shot and frame 123 begins the new one. Actual integer
PTS and rational time bases are stored; cuts are never silently snapped to keyframes.

The default export policy:

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
  scenes/0001.mov
  certificates/0001.json
  thumbnails/frame-000000123.jpg
```

New job directories are owner-only (0700); existing directory permissions are respected.
Existing outputs are not overwritten. Verified completed files are reused on resume
only after content-digest validation. `verify` performs the full decode comparison.
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

Public evidence is synthetic only. Keep private labels, source hashes, timings,
results and aggregates local as well as media/reports. See the
[privacy boundary and history cleanup](docs/privacy-cleanup.md).

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check --fix .
ruff format .
python -m build
```

Tests generate their own non-private fixtures. Private evaluation data stays local. Reproduction scripts live in
`scripts/`; see [benchmark instructions](benchmarks/README.md). Release workflows build
artifacts only; they do not publish packages or create public repositories.
