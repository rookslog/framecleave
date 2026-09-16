# Research and dependency/license audit

Research date: 2026-09-15/16 UTC. External research below is distinct from locally
executed benchmarks. This is an engineering audit of the distribution, not legal advice
about codec patents, jurisdiction-specific use or a future bundled binary distribution.

## Detector candidates

| Candidate | Primary source | What was established | Actual inference here |
|---|---|---|---|
| PySceneDetect | https://www.scenedetect.com/docs/latest/ | Content/adaptive families are useful baselines, not continuity proofs | Not installed. Our named baselines are explicitly independent implementations |
| FFmpeg `scdet` | https://ffmpeg.org/ffmpeg-filters.html#scdet-1 | Native scene metric and explicit threshold | Local evaluation only; no source-derived results are published |
| TransNetV2 | https://github.com/soCzech/TransNetV2 | Temporal learned boundary model; MIT repository; official TensorFlow and PyTorch paths | No weights obtained, no inference timing or accuracy claimed |
| AutoShot | https://github.com/wentaozhu/AutoShot | Short-video-oriented learned detector; MIT code repository | External weight artifact not acquired/audited; not benchmarked |
| OmniShotCut | https://github.com/UVA-Computer-Vision-Lab/OmniShotCut | Current 2026 work, temporal/motion-aware model; CUDA-oriented examples and external checkpoint distribution | Not benchmarked; CPU/MPS/Core ML viability unverified |
| Temporal geometry | OpenCV optical flow, affine RANSAC, SIFT APIs at https://docs.opencv.org/4.x/ | Small deterministic CPU alternative, explicitly handling duplicates and photometric/geometric continuity | Implemented; only synthetic evidence is published |

OmniShotCut paper: https://arxiv.org/abs/2604.24762 . Model authors' benchmark claims
are not measurements on this workload. Its reference loading/memory pattern would need
review for long batches. A PyTorch implementation is not itself proof that MPS supports
all operations correctly or efficiently. None of the learned alternatives was rejected
because of a measured accuracy deficit: code/weight acquisition was blocked by runtime
outbound network/DNS restrictions. Public web research was available; execution-side
downloads were not. These remain open comparison gates.

A code license does not automatically establish the terms of every externally hosted
weight artifact. No weights, converted checkpoints or third-party model code are included
in this release. Consequently, there is no unverified model redistribution in the wheel.

## Distributed and installed components

| Component | Terms reviewed | Distribution policy |
|---|---|---|
| FrameCleave code | MIT, repository `LICENSE` | Wheel/sdist/source supplied |
| NumPy 2.3.5 | BSD-3-Clause plus included third-party notices | Exact dependency pin; not vendored |
| OpenCV 4.13 | Apache-2.0 for current OpenCV; Python packaging MIT | `opencv-python==4.13.0.92`; not vendored |
| OpenCV wheel components | Upstream documents FFmpeg LGPL-2.1 components; Linux desktop wheels include Qt LGPL-3.0 components and other notices | Pip installs upstream dependency; do not claim the dependency tree is all MIT |
| System FFmpeg | LGPL baseline; enabling GPL components changes the binary's obligations | Required separately; no FFmpeg executable in our archives |
| libx264/libx265 | GPL components in the selected system FFmpeg | Required for tested lossless fallback; never relabel them as MIT |
| Pytest / Ruff / setuptools | Development tools with their own licenses | Development requirements only, not bundled runtime executables |

Primary license references:

- https://numpy.org/doc/2.3/license.html
- https://opencv.org/license/
- https://pypi.org/project/opencv-python/4.13.0.92/#licensing
- https://ffmpeg.org/legal.html
- https://formulae.brew.sh/formula/ffmpeg

Using a subprocess boundary is a packaging decision, **not** a blanket legal conclusion
that every possible future combined distribution avoids copyleft obligations. Re-audit
before shipping FFmpeg, OpenCV, model weights or standalone application bundles.

## Runtime provenance and installation qualification

The shared build environment initially advertised both desktop and headless OpenCV,
which share the same `cv2` namespace. Inspecting build information and original wheel
RECORD hashes showed the actual binary matched **opencv-python**, not headless. Runtime
requirements were corrected to the distribution actually exercised. `doctor` detects
multiple distributions and reports the actual GUI build. FrameCleave never opens a GUI.
A headless migration is desirable for reducing Linux desktop dependencies, but requires
its own clean installation and parity check; it is not silently claimed as tested.

The Linux installation test used a new venv without system site packages. Network access
was unavailable, so dependency wheels were reconstructed locally from installed files,
verifying their contents against the original installed RECORD hashes before installation.
These local reconstruction archives are **not distributed** and are not presented as
fresh downloads of official PyPI wheel archives. FrameCleave's own newly built wheel was
installed through pip normally. Official online resolution and native macOS installation
remain separate gates. Installation environment evidence is retained locally.

Native macOS ARM64 upstream wheels are available; that is an availability finding, not
an execution/performance measurement. The package pins two runtime versions, rather than
allowing silent detector dependency upgrades. System FFmpeg remains an external versioned
input, captured in every job's diagnostics.

## Current FFmpeg compatibility check

At the final check, Homebrew's unversioned formula was **9.0.1**, while the versioned
`ffmpeg@7` formula was **7.1.5**, keg-only and available as an Apple-Silicon bottle.
See https://formulae.brew.sh/formula/ffmpeg and
https://formulae.brew.sh/formula/ffmpeg@7 . Installation instructions explicitly select
the tested 7.1.x family instead of silently suggesting that the Linux 7.1.5 results
qualify Homebrew 9. This still does not constitute Mac execution.

Filter-file loading uses the current documented `-/filter:v` argument syntax from
https://ffmpeg.org/ffmpeg.html#Options rather than the legacy `-filter_script:v` form.
A real decoder integration test confirms sparse ordinal/PTS selection still works
with the new spelling on FFmpeg 7.1.5. No FFmpeg 9 runtime parity is asserted.

## Name and publication

“FrameCleave” had no obvious conflict in web/name checks; a GitHub name search during
execution returned no matching repositories. This is not a trademark clearance or registry
reservation. No PyPI package name was claimed and no public release was attempted. The
available GitHub connector exposed read actions, not a repository creation/push action.
The handoff therefore includes local Git history. Any later remote should be private first.
