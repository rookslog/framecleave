# Release and installation procedure

Only synthetic evaluation evidence is publishable. Private labels, source hashes,
timings and aggregate results stay local along with footage/reports. Read the
[publication guidelines](publication.md) before publishing.

The current source candidate is **0.2.0rc1**; the supplied 0.1.0rc1 delivery artifacts
are historical and are not overwritten. This is an engineering candidate,
not a completed qualification for unattended processing on macOS 27. The release
status is intentional; passing the generated-media suite does not erase real detector
errors, provisional labels, or missing target-hardware measurements.

## What is prepared

- Python wheel and source distribution, containing original code and notices only.
- An independent Git repository with the detector-freeze commit preserved.
- Exact runtime dependency pins, development requirements, a source privacy audit,
  generated integration fixtures, and benchmark/research documentation.
- Linux and macOS-26-arm64 CI definitions, plus a separate manually dispatched
  **self-hosted macOS-27-arm64** validation workflow. macOS 26 is not mislabelled 27.
- An artifact-only release workflow. It has no registry publishing or public-release
  permissions. No package-registry publication is authorized by this workflow.

Local generated-media tests and Ruff now run on Apple-Silicon macOS with FFmpeg 9.0.1.
Current check/build/install receipts are recorded in the feature plan. Remote CI and
consumer-player qualification must be reported separately, not inferred from local tests.

## Installation for users

From the supplied wheel in a native Apple-Silicon terminal:

```sh
brew install ffmpeg uv
uv tool install --python 3.13 ./framecleave-0.2.0rc1-py3-none-any.whl
framecleave doctor
framecleave --help
```

Python 3.13 is the version exercised here. The package declares Python >=3.11; other
supported Python versions still require their own qualification. FFmpeg 7 or later is
required; the current local feature gate uses 9.0.1. Keep the selected executable on PATH.
The wheel is Python-only; NumPy/OpenCV's platform wheels must resolve to native arm64.
FFmpeg is a separate system dependency. `doctor` reports architecture, actual OpenCV
build/distribution conflicts, executable versions and available encoders. It does not
pretend that merely listing VideoToolbox validates it.

For a source installation use `uv tool install --python 3.13 .` in the repository.
With pipx already configured, `pipx install ./framecleave-0.2.0rc1-py3-none-any.whl`
is an alternative. Neither command requires a public package registry entry for
FrameCleave; fetching third-party dependencies still requires normal network access.

## Maintainer verification

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt -e .
framecleave doctor
pytest
ruff check .
python scripts/audit_release.py
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"
python -m build
python scripts/audit_release.py dist/*.whl dist/*.tar.gz
```

Inspect both archive contents and Git history. The audit rejects media/model/image
extensions in the **repository/package**. It is deliberately stricter than necessary;
original generated demonstration images, when supplied separately, are not part of
the publishable source package. Never put the private job directories, source videos,
thumbnail reports or dependency-reconstruction wheelhouse in a release.

Install the newly built wheel into a second venv and run tests from outside the checkout
without the pytest `pythonpath=src` setting. The installation evidence explains the
network-constrained local wheel reconstruction used during this execution; that is not
a claim of a fresh online installation of official upstream archives.

## Remaining qualification before a stable/public release

1. Independently annotate more representative footage, re-evaluate exact-frame false
   negatives/positives, and resolve the documented missed cuts and motion errors.
   Compare an acquired, license-audited neural detector on the same protocol.
2. Run `scripts/validate_macos.py --output <new-directory> --input <permitted-video>`
   on native macOS 27 arm64, then reproduce the domain benchmark there. Measure
   VideoToolbox parity, real process-group memory, disk expansion and throughput.
3. Test consumer-player compatibility and decide whether additional export formats,
   audio codecs, HDR/auxiliary-stream handling or faster verified encoders are justified.
4. Execute the prepared CI/lint/format and clean online installation matrix. Re-audit
   any new dependency binary or model weight before redistributing it.

These are open gates, not background tasks or promises that work is continuing elsewhere.

## Repository and PR boundary

The owner authorized moving the Git checkout to `~/Development/framecleave` and creating
the public `rookslog/framecleave` repository. Private videos, reports, generated media
and run artifacts stay outside Git/packages. Feature work belongs on
`feat/compact-export-and-progress`, with coherent audited commits and a draft PR;
merging, tagging and registry publication are separate actions.

The original delivery bundle remains available for recovery:

The supplied Git bundle retains history without requiring access to the development
container:

```sh
git clone framecleave.git.bundle framecleave
cd framecleave
git status
```

The current checkout has a configured public remote. The old bundle itself is unchanged.
The project name has not been registered; the earlier name search was not trademark clearance.
