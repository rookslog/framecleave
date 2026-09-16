# Compact Export, Progress, and Editorial Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Current goal:** Deliver structured CLI progress, fast audiovisual review copying and
one selected final encode with bounded temporary space; preserve explicit exact modes.
The original compact/editorial-planning sections below are retained as amended history.

**Current architecture:** Preserve `scene-index.json` as the complete analysis partition.
Review certificates bind intended ranges and integrity; selected copied inputs are decoded,
trimmed, concatenated and encoded once. Progress uses terminal/JSONL/multiprocessing adapters.
Standalone editorial plans and keyframe movement are intentionally deferred.

**Tech Stack:** Python 3.13, argparse, multiprocessing, JSON/JSONL, NumPy, OpenCV, FFmpeg/FFprobe, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-16-compact-export-progress-design.md`

## Privacy cleanup checkpoint

The owner authorized synthetic-only public evidence and branch/tag history rewriting on 2026-09-16. Private measurements have been removed; original records are retained in the private backup. Historical receipts below predate the rewrite. Final standalone pytest passed 210 tests in 93.70 seconds; Ruff and whitespace passed. Sanitized main passed 89 tests. Runtime source is unchanged; the release audit has generated-only artifact guards and eight new tests. Standard Git history searches found no matches for 43 known private markers. The source/archive/history audit covered 85 tracked files, two archives and 23 commits/181 blobs. Both branches and the existing tag were atomically published with exact leases; PR description is sanitized and the old Actions package artifact is removed. **Blocked on an owner decision:** GitHub still serves an old annotation by its original commit ID. PR 1 stays draft; connector review is not requested until the cache/privacy condition is resolved. See the public privacy cleanup record for the remaining boundary; exact old-object reproduction details are private.

## Execution State

Linux CI follow-up: the gray-card integration fixture omitted an explicit output
rate. Native FFmpeg 7.1 reproduced the Linux failure locally: all 50 frames decode,
but the final frame has zero duration and its PTS equals the stream endpoint.
Explicit `-r 30` restores the fixture's intended 30 fps and final duration; the
same integration test changed from failing to passing with FFmpeg 7.1 generation.
Production timing checks are unchanged. Fresh local gate: 210 tests passed in
62.70 seconds, Ruff clean, release audit passed for 85 tracked files (no archives),
whitespace clean. The pushed fix still needs fresh remote CI; privacy readiness
remains blocked on the independent owner cache decision above.

- Tasks 1–6: committed on `feat/compact-export-and-progress`.
- Task 7: original runner/generated evidence implemented; private evaluation stays local. Its per-scene compact-default gate is paused after clarification; separate stream-copy/one-final-encode experiments are complete.
- Last committed-slice software gate, before Task 9 red tests: 167 tests passed; full Ruff and release audit clean. This is historical software evidence, not a claim that the pending red tests pass.
- Task 8: annotations and validated decision resolver implemented; CLI plan hook remains pending Task 9's validated output schema.
- Tasks 9–10: standalone export-plan/keyframe work intentionally deferred. Draft tests are preserved in committed `tests/deferred_export_plan.py`, not collected automatically.
- Task 11: old per-scene compact-default gate superseded by the approved stream-copy amendment below. No merge, tag or registry publication is authorized here.

### Current research checkpoint — stream-copy-first workflow

Owner approved implementation of the researched adjustment after the recommendation. The existing branch is retained and implementation stays inline/test-first. The amended write set is review-copy export/temporary-media limiting, policy/workflow/resume/verification, CLI and dependent report/docs/tests. Optional final assembly is separate from slicing. The earlier plan-module tests are preserved but remain deferred; they do not gate the ordinary stream-copy path.

Current implementation slices:
- [x] Packet-copy exporter and OS-enforced single partial-media size ceiling; no encoders/caches or automatic encoding fallback.
- [x] Workflow/policy/resume/verification integration and saved intended ranges; preserve explicit legacy modes (27 focused tests passed before further work).
- [x] Default CLI/help/docs, selected assembly, temporary accounting, independent review
  disposition, production smoke and isolated-wheel verification/install implemented.
- [x] Closing state: source and wheel gates passed; implementation committed as
  the pre-cleanup implementation checkpoint, branch pushed, [PR #1](https://github.com/rookslog/framecleave/pull/1)
  created against main. No merge/tag/registry publication.
- **Intentionally deferred:** consumer-player/subjective-quality and general delayed-
  audio/VFR/damaged-tail qualification; not claimed by this engineering candidate.

Integration checkpoint: current CLI default is review-copy in 0.2.0rc1; library
`process_video`/`process_batch` defaults retain auto for compatibility. Review resume
reports `skipped_integrity_checked`, not sample/pixel equality. Independent copied-input
assembly passed generated H.264/HEVC nonadjacent selection/decode tests with unavailable
original paths. Media-budget failures preserve clips. Owned logical scripts, streamed
metrics and atomic metadata now share pre-growth reservations; batch reporting draws
from a reserved parent allowance deducted from workers. Explicit legacy-mode caches and
persistent outputs/logs are outside the cap. Controlled hard worker exit handling and
aggregate/narrow-terminal status regressions were added; full fresh gate follows.

Read-only review: reused `/root/astra_framecleave_architecture` by owner model preference
and required review-gate skill, not implementation delegation. Requested Astra/high;
follow-up surface provides no served model/effort attestation. Scope is copy/budget/
workflow/assembly/batch current source/tests, no writes or descendants. Root preserves
the complete response verbatim and dispositions findings with new test evidence.

Temporary budget convention for the first slice: one owned unfinished media file at a time per input, ceiling `floor(1.5 × input bytes)`, enforced before filesystem growth by the child OS file-size limit, not polling. No full PCM/reference caches are created. Per-input ceilings compose across active workers without borrowing from other inputs. Persistent review outputs are not disposable scratch; they remain untouched. Whole-job atomic metadata temporary writes and final assembly lifecycle need their own accounting before claiming the complete temporary budget is enforced.

First-slice verification: generated H.264/HEVC compressed-packet hashes remain subsets of originals; an invocation fence rejects encoder/filter/reference commands; AAC remains AAC. Real 128-byte media-limit refusal cleans owned partials and preserves sources. Whole-copy digest/no-clobber/policy tests pass. The old export-plan draft is preserved as `tests/deferred_export_plan.py` (not collected automatically; optional plan work is deferred). Full active suite and Ruff are run before committing; CLI/default/workflow integration is not yet claimed.

The owner's clarification restates the intended workflow: detect boundaries, produce fast video-and-audio packet-copy slices for review/selection without automatic per-scene re-encoding, then encode the selected assembly once (trial CRF 16/18). Imperfect boundary playback is acceptable; output should remain roughly near source size and temporary working storage should be bounded to 1.5× processed input bytes. The prior sample/pixel-exact contract is not the acceptance criterion for these review slices. Existing exact/lossless paths remain available and their certificates are not reinterpreted.

Historical research rationale is retained in `docs/streamcopy-research.md` and the advisor response. Private measurements are omitted from public documentation. The approved implementation supersedes the old compact-default gate.

### Read-only review disposition and production receipts

The complete reviewer-owned response is preserved verbatim in
`docs/astra-streamcopy-code-review.md`. Root dispositions:

1. **Accept after revision:** generated 250ms delayed, distinct-rate audio onset test
   reproduced advancement. Assembly now uses a common video origin and explicit
   leading/trailing audio padding; waveform onset regression passes.
2. **Accept after revision:** 128-byte failure followed by normal retry reproduced
   sidecar refusal. Unique retained attempt logs allow retry; post-publication failure
   now reports retained media explicitly. Retry regression passes.
3. **Accept after revision:** live lock bytes were unreserved. Locks now retain a
   pre-write reservation. A controlled writer at the actual media ceiling sums physical
   logical `.lock`/partial sizes and stays within the input ceiling; cleanup passes.
4. **Accept after revision:** injected progress-storage failure reproduced unbounded
   batch waiting. Coordinator keeps draining after error; root monitors health and
   performs unconditional shutdown. Spawned failure test returns, leaves zero workers,
   persists failed state when storage allows, and preserves the original error.
5. **Accept after revision:** finished→worker-lost reproduced false success counts.
   Worker-loss now retires earlier successful events as unconfirmed failures. Counter
   regression passes; arbitrary mid-IPC hard kills remain unqualified.

Private production measurements are intentionally omitted from public documentation. Generated physical-limit, corrected-resume and assembly checks supply the public regression evidence; no consumer-player or subjective-quality qualification is claimed.

Closing receipts: isolated **installed-wheel** full suite passed 202 tests in 55.89s.
It ran outside the checkout, with pytest `pythonpath` disabled and the package loaded
from site-packages. Repository root was supplied only for `scripts` benchmark helpers;
an initial run without those helpers had six import failures (195 passed), not six
product failures. The corrected complete run passed. A final reserve-validation
regression also rejects negative internal allowances before any job-directory writes.

Ruff 0.15.7 and staged whitespace checks pass. Release audit covers 110 tracked files
and both new 0.2.0rc1 wheel/source archives with no forbidden media/path entries.
`uv tool install --force --python 3.13 <audited-wheel>` refreshed the local executable;
`framecleave --version` reports 0.2.0rc1, `doctor --json` exits 0 with native arm64,
Python3.13.11/FFmpeg9.0.1 and exactly one OpenCV distribution. `assemble --help` exposes
the selected-scene/CRF16/18 and quiet/verbose/debug contract. Original delivery artifacts
and private media are untouched. Fresh complete source suite passed **202 tests in
52.78s** after the final source change. This is the pre-cleanup implementation receipt; public
PR: https://github.com/rookslog/framecleave/pull/1. Source checkout and feature branch
remain available for review. Consumer-player/quality and remote CI qualification are
not inferred from local checks; no merge or stable-release completion is claimed.

## Global Constraints

- `scene-index.json` remains a complete contiguous decoded-frame partition.
- No source file or existing certified output is overwritten or deleted.
- Compact output preserves exact requested frame ordinals and rational timing but never claims native-pixel equality.
- Explicit `auto`, `lossless`, and `copy-only` behavior remains compatible during the transition.
- The no-flag default changes only in `0.2.0rc1`, after the CRF 16/18/20 evidence checkpoint selects a profile.
- Compact partial-scene audio uses verified ALAC for supported native 16-bit integer streams and native-precision PCM otherwise; both must decode to sample-equal output.
- Keyframe movement is confined to an owner-approved transition mask and capped at `min(30 frames, 1 second)` unless the user explicitly lowers it.
- `--quiet` remains errors-only; `--json` emits exactly one result object on stdout.
- Private reports, media, annotations, source hashes, timings and aggregates remain local and never enter Git history, fixtures or PR artifacts.
- Every behavioral slice follows red-green-refactor and ends with a focused test, full relevant suite, Ruff, diff review, and coherent commit.

## Verification Commands

Use these exact commands throughout:

```sh
TEST='uv run --no-project --isolated --python 3.13 --with-editable . --with-requirements requirements-dev.txt python -m pytest'
$TEST
uvx --from ruff==0.15.7 ruff check .
python3 scripts/audit_release.py
```

Do not use `ruff format` as a repository-wide rewrite; the inherited tree is not Ruff-formatted.

---

### Task 1: Progress event model and durable JSONL sink

**Files:**
- Create: `src/framecleave/progress.py`
- Create: `tests/test_progress.py`

**Interfaces:**
- Produces: `ProgressEvent`, `ProgressSink`, `NullProgressSink`, `CompositeProgressSink`, `JsonlProgressSink`.
- Event identity: `schema_version`, `run_id`, `event`, `phase`, `sequence`, optional job/scene/attempt IDs, progress counts, elapsed time, outcome, reason code, diagnostics reference.
- `JsonlProgressSink` appends one compact object per line, rejects symlinks, flushes terminal events, and records bounded values only.

- [x] **Step 1: Write failing event serialization tests**

```python
def test_progress_event_serializes_only_declared_fields():
    event = ProgressEvent(run_id="run-1", event="scene_started", phase="encoding",
                          sequence=3, job_id="job-1", scene_id="5", completed=4, total=18)
    assert event.to_dict() == {
        "schema_version": 1, "run_id": "run-1", "event": "scene_started",
        "phase": "encoding", "sequence": 3, "job_id": "job-1",
        "scene_id": "5", "completed": 4, "total": 18,
    }

def test_progress_event_rejects_unknown_or_negative_progress():
    with pytest.raises(ValueError):
        ProgressEvent(run_id="run-1", event="tick", phase="analysis", sequence=-1)
```

- [x] **Step 2: Run the focused test and confirm RED**

Run:

```sh
$TEST tests/test_progress.py -q
```

Expected: import failure because `framecleave.progress` does not exist.

- [x] **Step 3: Implement the minimal typed event interface**

```python
@dataclass(frozen=True)
class ProgressEvent:
    run_id: str
    event: str
    phase: str
    sequence: int
    job_id: str | None = None
    scene_id: str | None = None
    attempt_id: str | None = None
    completed: int | None = None
    total: int | None = None
    unit: str | None = None
    elapsed_seconds: float | None = None
    outcome: str | None = None
    reason_code: str | None = None
    diagnostics: str | None = None
    recovered: bool | None = None

class ProgressSink(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...
    def close(self, result: dict | None = None) -> None: ...
```

Validate nonempty identifiers, nonnegative sequences/counts, `completed <= total`, finite elapsed values, and relative diagnostic paths.

- [x] **Step 4: Add RED tests for JSONL durability and symlink refusal**

```python
def test_jsonl_sink_writes_one_compact_event_per_line(tmp_path):
    sink = JsonlProgressSink(tmp_path / "events.jsonl")
    sink.emit(ProgressEvent(run_id="r", event="job_finished", phase="complete",
                            sequence=1, outcome="success"))
    sink.close()
    assert json.loads((tmp_path / "events.jsonl").read_text())['event'] == 'job_finished'

def test_jsonl_sink_refuses_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("")
    (tmp_path / "events.jsonl").symlink_to(outside)
    with pytest.raises(FileExistsError):
        JsonlProgressSink(tmp_path / "events.jsonl")
```

- [x] **Step 5: Implement JSONL, composite, and null sinks; verify GREEN**

Terminal outcomes are `job_finished`, `job_failed`, `batch_finished`, `batch_interrupted`, and `worker_lost`; flush and `os.fsync` those events. Do not include raw exceptions or FFmpeg stderr in event fields.

Run:

```sh
$TEST tests/test_progress.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave/progress.py tests/test_progress.py
```

- [x] **Step 6: Commit the slice**

```sh
git add src/framecleave/progress.py tests/test_progress.py
git diff --cached --check
git commit -m "feat: add structured progress event model"
```

---

### Task 2: Terminal presenter and CLI output modes

**Files:**
- Create: `src/framecleave/presentation.py`
- Create: `tests/test_presentation.py`
- Modify: `src/framecleave/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ProgressEvent` and `ProgressSink` from Task 1.
- Produces: `OutputMode(QUIET, DEFAULT, VERBOSE, DEBUG)` and `TerminalProgressSink(stream, mode, is_tty, width, clock)`.
- CLI flags remain mutually exclusive: `--quiet`, `--verbose`, `--debug`.

- [x] **Step 1: Write failing presenter tests**

```python
def test_default_tty_replaces_one_status_line():
    stream = FakeTTY(width=80)
    sink = TerminalProgressSink(stream, OutputMode.DEFAULT, is_tty=True, clock=FakeClock())
    sink.emit(event("analysis_progress", completed=100, total=1000))
    sink.emit(event("scene_started", phase="encoding", scene_id="2"))
    assert "\r" in stream.value
    assert stream.value.count("\n") == 0

def test_non_tty_uses_milestones_without_ansi():
    stream = io.StringIO()
    sink = TerminalProgressSink(stream, OutputMode.DEFAULT, is_tty=False, clock=FakeClock())
    sink.emit(event("job_started"))
    sink.emit(event("job_finished", outcome="success"))
    assert "\r" not in stream.getvalue()
    assert "\x1b" not in stream.getvalue()
```

- [x] **Step 2: Run focused tests and confirm RED**

```sh
$TEST tests/test_presentation.py -q
```

- [x] **Step 3: Implement renderer behavior**

Default TTY rendering order:

```text
[3/38] source-name · encoding · scene 5/18 · 00:31 · fallbacks 1
```

Drop optional fields from the right when width is insufficient. Quiet renders terminal errors only. Verbose renders lifecycle events as lines. Debug renders verbose events and permits the CLI debug logging handler.

- [x] **Step 4: Add CLI parser and channel tests**

```python
@pytest.mark.parametrize("flag", ["--quiet", "--verbose", "--debug"])
def test_presentation_flags_are_accepted(flag):
    result = call_cli("doctor", flag, "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True

def test_presentation_flags_are_mutually_exclusive():
    result = call_cli("doctor", "--verbose", "--debug")
    assert result.returncode == 2
```

Assert `--quiet --json` still emits one stdout object and default/verbose/debug never put progress on stdout.

- [x] **Step 5: Wire the CLI without changing workflow behavior**

Replace the boolean logging-level expression with an `OutputMode` parser. Attach a console logging handler only in debug mode. Keep error rendering and JSON results in `main`; inject a presenter sink into later tasks through a local `sink` variable.

- [x] **Step 6: Verify and commit**

```sh
$TEST tests/test_presentation.py tests/test_cli.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave/presentation.py src/framecleave/cli.py tests/test_presentation.py tests/test_cli.py
git add src/framecleave/presentation.py src/framecleave/cli.py tests/test_presentation.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: add quiet default verbose and debug presentation"
```

---

### Task 3: Emit workflow and export lifecycle events

**Files:**
- Modify: `src/framecleave/workflow.py`
- Modify: `src/framecleave/export.py`
- Modify: `src/framecleave/media.py`
- Modify: `src/framecleave/cli.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_export.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `process_video(..., progress: ProgressSink | None = None, job_id: str | None = None)`.
- `ExportSession(..., progress: ProgressSink | None = None, job_id: str | None = None)`.
- The default `None` uses `NullProgressSink` and preserves library callers.

- [x] **Step 1: Write RED tests for recovered and terminal attempts**

Use a collecting sink around the existing copy-failure fixtures:

```python
assert [e.event for e in sink.events].count("attempt_rejected") == 1
assert sink.events[-1].event == "scene_certified"
assert sink.events[-1].recovered is True
assert not any(e.event == "scene_failed" for e in sink.events)
```

Add a separate exhausted-attempt test asserting one terminal `scene_failed` event.

- [x] **Step 2: Confirm RED**

```sh
$TEST tests/test_export.py -q
```

Expected: `ExportSession` does not accept a progress sink and emits no events.

- [x] **Step 3: Emit stable domain events**

Instrument these decision points:

- probing/analyzing started;
- decoded-frame progress, rate-limited by the presenter;
- boundaries detected;
- export and scene started;
- attempt started/rejected;
- scene certified;
- report started/finished;
- job completed/failed/interrupted.

Change the recoverable `LOG.warning` to `LOG.debug`; the durable `attempt_rejected` event becomes the user-facing signal. Store only a bounded diagnostic tail in the per-job log and reference it from the event.

- [x] **Step 4: Add CLI integration tests**

Run a generated two-scene fixture through default, verbose, and debug modes. Assert default stderr has no raw `Non-monotonic DTS` block, verbose contains a concise rejected-attempt line, and debug contains command diagnostics.

- [x] **Step 5: Verify and commit**

```sh
$TEST tests/test_export.py tests/test_workflow.py tests/test_cli.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests/test_export.py tests/test_workflow.py tests/test_cli.py
git add src/framecleave/workflow.py src/framecleave/export.py src/framecleave/media.py src/framecleave/cli.py tests/test_workflow.py tests/test_export.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: report workflow and export lifecycle events"
```

---

### Task 4: Parent-owned batch events and multiprocessing transport

**Files:**
- Modify: `src/framecleave/progress.py`
- Modify: `src/framecleave/batch.py`
- Modify: `src/framecleave/cli.py`
- Modify: `tests/test_progress.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Produces: `QueueProgressSink`, `ProgressCoordinator`, and `BatchStatus`.
- Worker initializer receives a spawned-context queue and constructs a worker sink.
- Parent coordinator is the sole writer for console output, `batch-events.jsonl`, and active batch status.

- [x] **Step 1: Write RED multiprocessing tests**

```python
def test_spawned_batch_events_are_parent_serialized(source_video, tmp_path):
    result = call_cli("batch", inputs, "-o", tmp_path / "out", "--dry-run", "--jobs", "2")
    events = [json.loads(line) for line in (tmp_path / "out" / "batch-events.jsonl").read_text().splitlines()]
    assert {e["event"] for e in events} >= {"batch_started", "job_started", "job_finished", "batch_finished"}
    assert all("ffmpeg stderr" not in json.dumps(e) for e in events)
```

Add tests for worker exit without terminal event, interrupt draining, partial final JSONL line, and jobs=1 using the same coordinator path.

- [x] **Step 2: Confirm RED**

```sh
$TEST tests/test_cli.py -k 'batch and event' -q
```

- [x] **Step 3: Implement queue transport and coordinator**

Use `multiprocessing.get_context("spawn").Queue()` as an initializer argument and a parent drain thread. Queue payloads are event dictionaries validated back into `ProgressEvent`; arbitrary pickled objects are rejected.

The coordinator updates:

```json
{
  "total": 38,
  "pending": 35,
  "active": 2,
  "succeeded": 1,
  "failed": 0,
  "interrupted": 0,
  "recovered_fallbacks": 4,
  "active_phases": {},
  "event_log": "batch-events.jsonl"
}
```

Write `batch-summary.json` atomically. Flush terminal events before pool shutdown completes.

- [x] **Step 4: Add disk-byte observations**

Record current and peak observed job bytes at file completion and terminal batch events. These are measurements, not estimates. Add a low-space event using `shutil.disk_usage(output).free` without automatically deleting or moving data.

- [x] **Step 5: Verify and commit**

```sh
$TEST tests/test_progress.py tests/test_cli.py tests/test_storage.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests/test_progress.py tests/test_cli.py tests/test_storage.py
git add src/framecleave/progress.py src/framecleave/batch.py src/framecleave/cli.py tests/test_progress.py tests/test_cli.py tests/test_storage.py
git diff --cached --check
git commit -m "feat: persist and aggregate batch progress events"
```

---

### Task 5: Versioned export policies and policy-aware certificates

**Files:**
- Create: `src/framecleave/policy.py`
- Create: `tests/test_policy.py`
- Modify: `src/framecleave/export.py`
- Modify: `src/framecleave/workflow.py`
- Modify: `src/framecleave/cli.py`
- Modify: `tests/test_export.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `ExportPolicy`, `VideoPolicy`, `AudioPolicy`, and `policy_digest()`.
- Modes: `compact`, `auto`, `lossless`, `copy-only`.
- Certificates carry `schema_version: 2`, policy digest, equality status, structural verification, and attempt records.

- [x] **Step 1: Write RED policy identity tests**

```python
def test_policy_digest_changes_with_quality_or_audio():
    base = ExportPolicy.compact(crf=18, audio="alac")
    assert policy_digest(base) != policy_digest(replace(base, crf=20))
    assert policy_digest(base) != policy_digest(replace(base, audio=AudioPolicy("pcm")))
```

Test strict deserialization, unknown keys, supported source-codec mapping, and backward-compatible resolution of explicit `auto`.

- [x] **Step 2: Confirm RED and implement policy module**

```sh
$TEST tests/test_policy.py -q
```

Initial compact candidates use CRF 16/18/20 and a fixed `medium` preset for both `libx264` and `libx265`. Unsupported compact source codecs fail explicitly rather than silently changing families.

- [x] **Step 3: Write RED certificate-vocabulary tests**

Assert compact certificates cannot contain `all_native_pixels_equal: true`; lossless/copy certificates retain exact equality booleans; old certificate fixtures remain readable under schema 1.

- [x] **Step 4: Split exact and compact verification paths**

Keep the existing exact verifier unchanged behind `verify_exact_video`. Add `verify_compact_video` for decoded frame count, rational PTS, endpoint, properties, decode success, and quality evidence. Use an enum-like status (`equal`, `different`, `not_applicable`) rather than overloaded booleans in schema 2.

Implementation checkpoint: structural compact verification is in place; quality evidence is added with Task 6's SSIM/PSNR filters. Compact media encoding remains explicitly disabled until that slice, so this intermediate commit cannot certify an incomplete compact path.

Update `verify_job` and CLI success text to report the policy actually checked. Never print the universal “all pixels/samples match” message for compact jobs.

- [x] **Step 5: Bind resume to policy identity**

Add the complete resolved policy and digest to the workflow request fingerprint. Resume rejects changed profiles, audio policy, or certificate schema.

- [x] **Step 6: Verify and commit**

```sh
$TEST tests/test_policy.py tests/test_export.py tests/test_workflow.py tests/test_cli.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests
git add src/framecleave/policy.py src/framecleave/export.py src/framecleave/workflow.py src/framecleave/cli.py tests/test_policy.py tests/test_export.py tests/test_workflow.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: add versioned export policies and certificates"
```

---

### Task 6: Explicit compact video with verified lossless audio

**Owner amendment approved (2026-09-16): floating-point audio preservation**

Generated audio probe: The local `ffmpeg -h encoder=alac` lists only `s16p` and `s32p`; a generated AAC → ALAC → float-PCM probe produced different decoded-sample SHA-256 values, with the ALAC output reporting 24-bit precision. This confirms that integer ALAC conversion cannot satisfy native float-sample equality for that supported input shape. No private identifiers or samples were copied into this artifact.

Decision: the owner approved verified ALAC with native-precision PCM fallback for unsupported float/full-width integer audio. Quantized ALAC and deferral were not selected. The reason is to address the measured lossless-video expansion without weakening audio equality. The load-bearing assumption is that native decoded-sample equality remains more important than the smallest audio stream; a preference for audio compression over equality, or evidence that PCM dominates storage, would require revisiting the policy.

The approval amends compact audio policy, resolved-policy identity, encoder selection, certificates, tests, calibration matrix, and public documentation together. ALAC eligibility is initially limited to native 16-bit integer samples in supported channel layouts; all other verified formats use native PCM. The original ALAC-only assumption is superseded by this amendment.

Verification implementation: compact output is compared with an independent full-decode, frame-ordinal reference encode under the same policy. Encoder build and thread settings are bound for replay. This adds a second encode, which Task 7 must include in runtime measurements; SSIM/PSNR are evidence, not correspondence thresholds.

**Files:**
- Modify: `src/framecleave/export.py`
- Modify: `src/framecleave/audio.py`
- Modify: `src/framecleave/policy.py`
- Modify: `tests/test_export.py`
- Modify: `tests/test_audio.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: resolved `ExportPolicy` from Task 5.
- Compact encoder: source-codec matched `libx264` or `libx265`, CRF/preset from policy, source bit depth/chroma retained.
- Compact partial audio: verified ALAC or native PCM fallback, decoded sample equality and timing required.

- [x] **Step 1: Write RED compact export tests**

Create generated H.264 and HEVC fixtures with uniquely identifiable frames. Assert:

```python
certificate = export_scene(mode="compact", start=7, end=47)
assert certificate["method"] == "compact-reencode"
assert certificate["video"]["frames_verified"] == 40
assert certificate["video"]["pixel_equality"] == "not_applicable"
assert certificate["video"]["all_pts_equal"] is True
assert certificate["audio"][0]["sample_equality"] == "equal"
assert certificate["audio"][0]["codec"] == "alac"
```

Add a negative fixture that substitutes, duplicates, or reorders an output frame and must fail compact verification.

- [x] **Step 2: Confirm RED**

```sh
$TEST tests/test_export.py -k compact -q
```

- [x] **Step 3: Add compact command generation**

For compact HEVC use:

```text
-c:v libx265 -preset medium -crf <16|18|20> -x265-params bframes=0:log-level=error
```

For compact H.264 use:

```text
-c:v libx264 -preset medium -crf <16|18|20> -bf 0
```

Retain the exact trim, PTS, encoder time base, final-duration bitstream filter, pixel format, color, aspect, rotation, and MOV timescale handling. Copy eligibility remains provisional and is independently verified.

- [x] **Step 4: Add ALAC output and verification**

Feed supported native 16-bit integer slices to `-c:a alac`; otherwise preserve the native PCM codec. Retain per-stream metadata/disposition, decode output, and compare samples/count/rate/layout/offset exactly. Record the selected codec and reason in the certificate; no automatic integer quantization is allowed.

- [x] **Step 5: Add compact quality comparison**

Run FFmpeg's built-in SSIM and PSNR filters over the exact source interval and compact output after structural verification. Record aggregate and minimum values as evidence; do not call them calibrated probabilities or pixel equality. A missing metric is a compact-verification failure, not an ignored warning.

- [x] **Step 6: Verify focused and full media suites; commit**

```sh
$TEST tests/test_audio.py tests/test_export.py tests/test_media.py tests/test_workflow.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests
git add src/framecleave/export.py src/framecleave/audio.py src/framecleave/policy.py tests/test_export.py tests/test_audio.py tests/conftest.py
git diff --cached --check
git commit -m "feat: add compact exact-boundary export with lossless audio"
```

---

### Task 7: Compact calibration evidence and default-policy checkpoint

**Files:**
- Create: `scripts/benchmark_compact.py`
- Create: `tests/test_benchmark_compact.py`
- Create after execution: `benchmarks/results/compact-export.json`
- Modify: `benchmarks/README.md`
- Modify after owner selection: `src/framecleave/policy.py`

**Interfaces:**
- Evaluates CRF 16/18/20 with the fixed medium preset for each supported source codec.
- Produces privacy-safe aggregate JSON with structural result, SSIM/PSNR evidence, bytes, source/output ratio, wall time, and playback observations.
- Never writes private source names, paths, frame images, per-file hashes or derived aggregates to repository artifacts.

- [x] **Step 1: Write RED benchmark aggregation tests**

```python
def test_compact_benchmark_redacts_private_inputs(tmp_path):
    result = summarize_runs([private_run(path="/private/name.mkv", crf=18)])
    text = json.dumps(result)
    assert "/private/" not in text
    assert "name.mkv" not in text
    assert result["profiles"]["hevc-crf18"]["runs"] == 1
```

- [x] **Step 2: Implement deterministic benchmark and generated corpus path**

The script accepts generated fixtures by default and an explicit private directory only for local evaluation. It writes raw results and aggregates locally, both outside the repository. It refuses to overwrite an existing result without `--force`.

- [x] **Step 3: Run generated calibration**

```sh
uv run --no-project --isolated --python 3.13 --with-editable . --with-requirements requirements-dev.txt \
  python scripts/benchmark_compact.py --generated --output benchmarks/results/compact-export.json
```

- [ ] **Step 4: Run private holdout locally without committing raw output**

Private holdout calibration records, aggregate measurements and local storage inventory remain outside Git. Generated per-scene calibration is explicitly not qualification of the review-copy default. The owner clarification supersedes the earlier preservation-first calibration gate; audiovisual copying belongs to review, audio encoding to final assembly.

- [ ] **Step 5: Owner checkpoint—select CRF 16, 18, or 20**

Present one compact table: size ratio, encode speed, minimum/mean quality evidence, structural failures, and private visual-review outcome. Record any private-derived profile decision and measurement locally, not in the generated result artifact. Do not proceed to the default flip without explicit owner selection.

- [ ] **Step 6: Commit evidence and selected profile**

```sh
$TEST tests/test_benchmark_compact.py -q
python3 scripts/audit_release.py
git add scripts/benchmark_compact.py tests/test_benchmark_compact.py benchmarks/README.md benchmarks/results/compact-export.json src/framecleave/policy.py
git diff --cached --check
git commit -m "bench: qualify compact export profile"
```

---

### Task 8: Transition annotations and review decisions

**Files:**
- Create: `src/framecleave/transitions.py`
- Create: `tests/test_transitions.py`
- Modify: `src/framecleave/report.py`
- Modify: `src/framecleave/workflow.py`
- Modify: `src/framecleave/cli.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `TransitionAnnotation(classification, evidence, source_range)` with values `transition_candidate`, `ordinary`, `ambiguous`.
- Adds `framecleave plan` command input surface for `keep`, `collapse`, or `omit` decisions.
- Batch approval accepts a default action plus explicit per-scene overrides.

- [x] **Step 1: Write RED classifier tests with generated frames**

Cover uniform gray cards, real dark scenes, fades, flashes, overlays, changing frames, meaningful audio, and first/last candidates. Assert short duration alone never returns an automatic omission.

```python
assert classify_transition(gray_card).classification == "transition_candidate"
assert classify_transition(dark_real_scene).classification != "transition_candidate"
assert classify_transition(gray_card_with_speech).classification == "ambiguous"
```

- [x] **Step 2: Implement evidence-only classification**

Inspect every frame for candidates under 30 frames. Record temporal stability, luminance/chroma distribution, texture/edge evidence, scoped template similarity, neighboring context, and audio activity. Emit evidence scores, not probabilities.

- [x] **Step 3: Add static report presentation**

Keep reports script-free. Show candidate label, exact range, evidence, and copyable commands for generating a decisions file. Do not add JavaScript that writes local files.

- [ ] **Step 4: Add explicit CLI decisions input**

Integration note: strict keep/collapse/omit resolution and override validation are implemented in the transition module. The CLI hook and batch-qualified IDs are integrated with Task 9's validated export-plan output schema.

```text
framecleave plan JOB --default-transition keep \
  --transition 2=collapse --transition 4=omit \
  -o JOB/export-plan.json
```

Batch form:

```text
framecleave plan BATCH --default-transition collapse \
  --transition job-id:4=keep -o BATCH/export-plans
```

Reject duplicate, unknown, or noncandidate scene IDs. Default action is `keep`.

- [x] **Step 5: Verify and commit**

```sh
$TEST tests/test_transitions.py tests/test_report.py tests/test_cli.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests
git add src/framecleave/transitions.py src/framecleave/report.py src/framecleave/workflow.py src/framecleave/cli.py tests/test_transitions.py tests/test_report.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: annotate and review transition micro-scenes"
```

---

### Task 9: Versioned export-plan schema and validator

**Files:**
- Create: `src/framecleave/export_plan.py`
- Create: `src/framecleave/schemas/export-plan-v1.json`
- Create: `tests/test_export_plan.py`
- Modify: `src/framecleave/cli.py`
- Modify: `src/framecleave/workflow.py`

**Interfaces:**
- Produces: `ExportPlan`, `PlanInterval`, `BoundaryDecision`, `read_export_plan`, `validate_export_plan`, `plan_digest`.
- Consumes transition decisions from Task 8 and immutable `scene-index.json`.
- `collapse` retires two boundaries and places one retained-frame boundary; `omit` creates an approved gap; neither mutates the scene index.

- [ ] **Step 1: Write RED schema and coverage tests**

```python
def test_plan_preserves_every_unomitted_frame_once(index):
    plan = make_plan(index, decisions={2: "omit"})
    validate_export_plan(plan, index)
    assert coverage(plan) == all_frames(index) - frames_of_scene(index, 2)

def test_plan_rejects_stale_index_digest(index):
    plan = make_plan(index)
    plan["scene_index_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="scene index digest"):
        validate_export_plan(plan, index)
```

Add tests for invalid paths, overlaps, unauthorized gaps, duplicate frames, empty intervals, stale policy, and unknown decision values.

- [ ] **Step 2: Implement the deep plan interface**

The plan records source/index/policy digests, original and effective boundaries, omission masks, protected boundaries, signed deltas, decision provenance, and approval time. Canonical JSON serialization determines `plan_digest`.

- [ ] **Step 3: Integrate `framecleave plan` output**

Plan generation never exports media. Refuse overwrite and symlink targets. Print a concise summary with kept/collapsed/omitted candidate counts and the plan digest.

- [ ] **Step 4: Bind processing and resume to a plan**

Add `split --plan PATH` and batch plan lookup. `--plan` is mutually exclusive with `--cuts` and `--index`. The workflow validates source/index/policy/plan digests before creating media.

- [ ] **Step 5: Verify and commit**

```sh
$TEST tests/test_export_plan.py tests/test_cli.py tests/test_workflow.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests
git add src/framecleave/export_plan.py src/framecleave/schemas/export-plan-v1.json src/framecleave/cli.py src/framecleave/workflow.py tests/test_export_plan.py tests/test_cli.py tests/test_workflow.py
git diff --cached --check
git commit -m "feat: add auditable export plans"
```

---

### Task 10: Constrained keyframe planner and plan execution

**Files:**
- Modify: `src/framecleave/export_plan.py`
- Modify: `src/framecleave/workflow.py`
- Modify: `src/framecleave/export.py`
- Modify: `src/framecleave/cli.py`
- Modify: `tests/test_export_plan.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_export.py`

**Interfaces:**
- Produces: `plan_keyframes(index, decisions, *, max_frames=30, max_seconds=Fraction(1))`.
- Movement is legal only within an approved transition mask and within both absolute limits.
- No candidate means exact compact export; `copy-only` refuses.
- CLI plan flags are `--boundary-strategy exact|keyframe-nearest`, `--max-snap-frames`, and `--max-snap-seconds`; values above 30 frames or 1 second are refused in this release.

- [ ] **Step 1: Write RED property and counterexample tests**

Encode the three observed shapes as generated timelines:

- a transition ending exactly on a keyframe;
- a transition with keyframes far on both sides;
- a keyframe two frames beyond the approved transition mask.

Assert the third case is rejected despite being only two frames away.

```python
assert plan_keyframes(index, decisions).effective_boundary == transition_end_keyframe
assert plan_keyframes(far_index, decisions).effective_boundary == original_boundary
assert plan_keyframes(outside_mask_index, decisions).reason == "outside-approved-mask"
```

Use property tests over generated timelines to assert ordering, nonempty intervals, no protected-boundary crossing, exact coverage outside omissions, and deterministic tie-breaking.

- [ ] **Step 2: Confirm RED and implement joint planning**

Build candidate sets for every editable boundary, intersect with the approved mask and distance limits, then solve in source order. Optimize for the number of copy-eligible adjacent outputs, then total displacement, then lower frame ordinal as a deterministic tie-breaker.

- [ ] **Step 3: Distinguish collapse from omit execution**

- `collapse`: retain all frames, remove the micro-scene as a separate output, and assign its frames around one approved effective boundary.
- `omit`: create separate outputs ending before and starting after the approved gap; do not concatenate them in this release.

Persist original/effective mapping and rejection reasons in the plan and certificates.

- [ ] **Step 4: Integrate exporter fallbacks**

For each planned interval: attempt verified stream copy only when both ends are eligible; on rejection emit `attempt_rejected`; then use compact exact-boundary encoding. Explicit lossless and copy-only policies retain their documented fallbacks/refusals.

- [ ] **Step 5: Verify and commit**

```sh
$TEST tests/test_export_plan.py tests/test_workflow.py tests/test_export.py -q
uvx --from ruff==0.15.7 ruff check src/framecleave tests
git add src/framecleave/export_plan.py src/framecleave/workflow.py src/framecleave/export.py src/framecleave/cli.py tests/test_export_plan.py tests/test_workflow.py tests/test_export.py
git diff --cached --check
git commit -m "feat: plan constrained keyframe boundaries"
```

---

### Task 11: Default flip, documentation, full verification, and draft PR

**Files:**
- Modify: `src/framecleave/__init__.py`
- Modify: `src/framecleave/policy.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cutting-strategy.md`
- Modify: `docs/release.md`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_schema.py`

**Interfaces:**
- Version becomes `0.2.0rc1`.
- Omitting `--mode` selects the owner-approved compact profile from Task 7.
- Explicit `--mode auto` retains the v0.1 copy-then-lossless behavior.

- [ ] **Step 1: Write RED default/version/help tests**

```python
def test_default_mode_is_selected_compact_profile():
    args = parser().parse_args(["split", "input.mkv", "-o", "out"])
    assert args.mode == "compact"

def test_explicit_auto_remains_available():
    args = parser().parse_args(["split", "input.mkv", "-o", "out", "--mode", "auto"])
    assert args.mode == "auto"
```

Assert `--version` is `0.2.0rc1` and help describes compact/lossless/copy-only/auto truthfully.

- [ ] **Step 2: Update version and public documentation**

Document:

- four output modes and stderr/stdout behavior;
- `batch-events.jsonl` and bounded diagnostics;
- compact versus exact lossless claims;
- ALAC sample equality;
- transition review and `framecleave plan` examples;
- collapse versus omit semantics;
- constrained keyframe limits and refusal;
- compatibility for explicit `--mode auto`;
- disk/scratch caveats and private job artifacts.

- [ ] **Step 3: Run the complete local gate**

```sh
$TEST
uvx --from ruff==0.15.7 ruff check .
python3 scripts/audit_release.py
uv run --no-project --isolated --python 3.13 --with-requirements requirements-dev.txt python -m build
git diff --check
git status --short
```

Read the full output. Do not claim completion if any test is skipped unexpectedly or if the audit/build fails.

- [ ] **Step 4: Perform private holdout validation without staging private artifacts**

Run report classification, plan generation, compact export, and verification on the supplied private corpus. Keep every private-derived measurement, including aggregates, outside Git. Publish only generated-fixture evidence. Re-run `python3 scripts/audit_release.py` and inspect `git status --short` before staging.

- [ ] **Step 5: Commit the release transition**

```sh
git add src/framecleave/__init__.py src/framecleave/policy.py pyproject.toml README.md CHANGELOG.md \
  docs/architecture.md docs/cutting-strategy.md docs/release.md \
  tests/test_cli.py tests/test_schema.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat: make compact export the 0.2 release default"
```

- [ ] **Step 6: Push and open a draft PR**

```sh
git push -u origin feat/compact-export-and-progress
gh pr create -R rookslog/framecleave --draft \
  --base main --head feat/compact-export-and-progress \
  --title "feat: add compact export and structured progress" \
  --body-file /tmp/framecleave-pr-body.md
```

The PR body must include: problem/evidence, architecture, compatibility, privacy boundary, commit/slice list, calibration decision, exact verification commands/results, known limitations, and deferred hybrid work.

- [ ] **Step 7: Monitor remote CI and review the PR diff**

```sh
gh pr checks -R rookslog/framecleave --watch
gh pr diff -R rookslog/framecleave --name-only
git status --short --branch
```

Resolve failures through new commits; do not rewrite published history or force-push.
