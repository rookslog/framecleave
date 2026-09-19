## Review verdict: changes requested

**Scope:** `b1d2371..a9e1e3d` plus the current unstaged implementation and tests, including untracked assembly/budget modules. Read-only review; no Git mutations, media exports, or descendants.

The ordinary CLI correctly selects audiovisual packet-copy without entering the exact exporter. The principal concerns are assembly synchronization, failure recovery, and budget/status edge cases.

### 1. Important — Assembly erases relative A/V offsets

**Source:** `src/framecleave/assemble.py:98–102`.

Video and each audio track independently receive `PTS-STARTPTS`. This advances delayed audio to the beginning of the video and destroys relative offsets between audio tracks. This is not merely tolerated packet-copy edge imprecision: it systematically changes synchronization during final encoding.

**Falsifier:** Generate a video with audio starting 250 ms later, export an unsplit review copy, then assemble it. Measure the output’s audio onset relative to video. Repeat with two differently delayed tracks. Existing `tests/test_assemble.py:11–33` checks frame count/codecs, not synchronization.

**Recommendation:** Establish one intended segment origin shared by video and audio; preserve offsets, with explicit leading padding where needed. Do not normalize each stream independently.

**Evidence status:** Source-confirmed transformation; resulting media timing not executed in this review.

### 2. Important — A failed assembly permanently blocks ordinary retry to the same target

**Source:** `src/framecleave/assemble.py:36–37`, `:127–128`, `:149–152`.

Assembly creates `<output>.diagnostics.log` before running FFmpeg. Failure removes the owned partial but retains diagnostics. The next invocation rejects that diagnostic file as an existing sidecar—even when no output or manifest was published.

A budget error, interruption, or transient encoder failure therefore requires manual file intervention or a different output name. Neither a retry nor a recovery interface is provided.

**Falsifier:** Run the existing budget-failure scenario with `max_temp_bytes=128`; then retry the same selection/output with the normal budget. The second attempt reaches the sidecar refusal rather than encoding.

**Recommendation:** Preserve logs, but provide ownership-bound retry semantics or distinct per-attempt diagnostic filenames. Also distinguish failure after media publication (`:140–143`) from failure before publication: a manifest-write failure currently leaves a published output while reporting generic assembly failure.

**Evidence status:** Source-confirmed lifecycle; retry not executed here.

### 3. Important — The all-owned-temporary-byte ceiling omits live lock files

**Source:** `src/framecleave/storage.py:82–83`; `src/framecleave/review_copy.py:64`, `:125`; `src/framecleave/limited_process.py:56`.

`.lock` is temporary, owned, and removed on exit, but its bytes are written without a reservation. The review writer can reserve and grow to the entire remaining budget. Thus a partial at the limit plus the live job lock exceeds the stated ceiling. Batch root and worker locks have the same accounting omission.

The existing budget tests compare reservation counters, so they cannot detect unreserved files.

**Falsifier:** Under a single-source review budget, use a controlled writer that fills the partial to its allowed cap and pauses. Sum the logical sizes of owned temporary files, including `.lock`; compare against `floor(1.5 × source_bytes)`.

**Recommendation:** Reserve lock bytes before writing and retain that reservation for the lock’s lifetime. Alternatively, explicitly negotiate a narrower budget contract; do not silently exempt them.

**Evidence status:** Source-confirmed accounting gap; peak-filesystem counterexample not executed.

### 4. Important — Progress persistence failure can defeat batch shutdown and truthful terminal state

**Source:** `src/framecleave/progress.py:283–291`, `:336–341`; `src/framecleave/batch.py:152–155`, `:169–180`.

A summary write/budget exception terminates the coordinator consumer thread and stores `self.error`. The batch does not monitor this while processing and calls `pool.join()` before `coordinator.drain()` checks it. With enough queued events, workers can block flushing their multiprocessing queues while the parent waits for them. The five-second drain timeout does not protect that earlier join.

Furthermore, exception handling calls `coordinator.drain()` before persisting interrupted state; a stored coordinator error therefore skips that state update and subsequent cleanup.

**Falsifier:** Inject `TemporaryBudgetError` or `ENOSPC` into coordinator summary persistence after startup. Have spawned workers emit enough events to fill the pipe, then finish. Assert bounded return, no surviving workers, and a non-running terminal batch state.

**Recommendation:** Monitor coordinator health during the result loop; stop workers and perform unconditional cleanup without depending on a healthy drain. Preserve the original storage error.

**Evidence status:** Source-confirmed control-flow gap; hang requires the proposed concurrency counterexample.

### 5. Important — Worker-loss results can disagree with summary counts and CLI exit status

**Source:** `src/framecleave/batch.py:139–143`; `src/framecleave/progress.py:183–195`, `:323–328`; `src/framecleave/cli.py:129`.

If `job_finished` arrives before a worker dies without returning its result, batch records `ok=False`, then emits `worker_lost`. `BatchStatus` ignores the latter because the job is already terminal. The summary can consequently contain failed file results but `failed=0`; CLI exit status uses that zero.

**Falsifier:** A worker flushes its successful terminal event, then exits before returning. Assert consistency between `files`, aggregate counts, and exit status.

**Evidence status:** I executed the read-only in-memory sequence `job_started → job_finished → worker_lost`; it retained `succeeded=1, failed=0`. Full multiprocessing reproduction remains untested.

**Recommendation:** Reconcile authoritative results and durable completed state explicitly; do not derive final status solely from first-arriving terminal events.

### Limits

No critical destructive overwrite was demonstrated. No test suite or FFmpeg trial was run, so media effects and concurrency failures above remain bounded, falsifiable review findings—not measured production failures. The reservation and stream-copy separation are useful foundations, but the five issues should be dispositioned before completion claims.
