# Release and installation procedure

Only synthetic evaluation evidence is publishable. Private labels, source hashes,
timings and aggregate results stay local along with footage/reports. Read the
[public-data boundary and history cleanup](privacy-cleanup.md) before publishing.

The current artifact is **0.1.0rc1**. This is a working, tested engineering candidate,
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
  permissions. No PyPI name, public repository or external release was created.

CI definitions have not run on GitHub in this environment. Ruff configuration is
provided, but the Ruff executable could not be acquired here, so a local Ruff pass is
not claimed. The local pytest/build/install results are recorded separately.

## Installation for users

From the supplied wheel in a native Apple-Silicon terminal:

```sh
brew install ffmpeg@7 uv
export PATH="$(brew --prefix ffmpeg@7)/bin:$PATH"
uv tool install --python 3.13 ./framecleave-0.1.0rc1-py3-none-any.whl
framecleave doctor
framecleave --help
```

Python 3.13 is the version exercised here. The package declares Python >=3.11; other
supported versions and actual macOS installation still require their own qualification.
The versioned FFmpeg formula is keg-only; keep its `bin` directory on PATH in shells
that run FrameCleave. It matches the tested 7.1.x family, not a claim that the macOS
binary itself was tested. Homebrew's current default is 9.0.1; that version remains an
additional compatibility gate. The wheel is Python-only; NumPy/OpenCV's platform wheels must resolve to native arm64.
FFmpeg is a separate system dependency. `doctor` reports architecture, actual OpenCV
build/distribution conflicts, executable versions and available encoders. It does not
pretend that merely listing VideoToolbox validates it.

For a source installation use `uv tool install --python 3.13 .` in the repository.
With pipx already configured, `pipx install ./framecleave-0.1.0rc1-py3-none-any.whl`
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
ruff format --check .
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

## Private remote creation

The supplied Git bundle retains history without requiring access to the development
container:

```sh
git clone framecleave.git.bundle framecleave
cd framecleave
git status
```

No remote is configured. A later authenticated maintainer can create an **empty private**
repository and push `main` after the artifact/privacy audit. Keep registry publication
and switching repository visibility as distinct, explicit decisions. The project name
has not been reserved and the name search was not trademark clearance.
