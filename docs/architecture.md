# Architecture

FrameCleave is a local Python CLI with system FFmpeg as its media boundary. It has no
service, telemetry, facial identity analysis, model download, GUI toolkit usage or npm
wrapper. The `cv2` distribution used in the evaluated environment is the desktop OpenCV
wheel; its GUI functions are not used. Exactly one OpenCV distribution belongs in the
isolated tool environment. `doctor` reports the actual build and conflicting installs.

## Layers and contracts

| Module | Responsibility | Important invariant |
|---|---|---|
| `config` | Strict explicit TOML plus CLI overrides | Unknown options fail; settings fingerprinted |
| `model` | Rational presentation timeline, intervals and schema | Decoded ordinals partition source exactly once |
| `media` | Probe, canonical decode, native frame hashes, per-frame audit | No FPS-derived timestamps or automatic rotation |
| `detector` | Streaming signals and contextual boundary decisions | Cut/review are distinct; evidence is not probability |
| `evaluate` | Exact or tolerance-window one-to-one matching | One prediction cannot satisfy two edits |
| `audio` | Canonical native-precision samples and sample-clock slicing | Preserve sample values and original audio offset |
| `export` | Copy/re-encode attempts and independent decoding | Only verified, readable output is finalized |
| `review_copy` | Compressed audiovisual previews and intended ranges | No encoders, PCM caches or equality claims |
| `assemble` | Selected independent decodes, trim/concat and one encode | Copies need not depend on available originals |
| `tempbudget`, `limited_process` | Pre-growth logical-byte reservations and OS media cap | Review temp space composes within 1.5× input |
| `report` | Exact-ordinal JPEGs, CSV and escaped local HTML | Review candidates are not silently accepted |
| `storage` | Owned job directories, locks, atomic JSON and logs | Never overwrite an unowned output |
| `workflow` | Per-file orchestration, certificates, resume and verify | Source/configuration/certificates bind each job |
| `batch` | Bounded spawned workers, failure isolation, aggregate state | One damaged input does not erase other successes |
| `cli`, `diagnostics` | Unix CLI and truthful capabilities | JSON on stdout; diagnostic progress on stderr |

Detection uses every decoded frame at a small aspect-preserving resolution (default
bounding box 128 by 96), retaining only numeric metrics and timing. An optional second
pass obtains candidate neighborhoods at twice that resolution. It does not persist a
directory of full-resolution frames. Context is indexed partly by visual updates,
rather than blindly by wall-clock frame count, to avoid diluting motion with duplicates.

A detector produces records with `frame`, `pts`, `decision`, `reason`, and `evidence`.
Only `decision=cut` creates a scene boundary. `decision=review` remains visible in the
HTML and JSON. CLI `--cuts` or an imported index provides an explicit correction route;
there is no claim that evidence scores are calibrated confidence percentages.

## Timeline interface

Frame zero is the first decoded presentation frame, not the first compressed packet.
A cut at N makes N the first frame of the next shot. Scenes use **[start, end)**, with
`last_frame=end-1`. Actual integer PTS, actual displayed durations, keyframe ordinals
and one rational source time base are retained. The index includes all source PTS so
VFR reconstruction does not depend on rounded human-readable timestamps.

`model.validate_index` supplements the shipped JSON Schema with arithmetic checks:
strictly increasing PTS, positive durations, exact end time, contiguous nonoverlapping
partition, matching boundary list, consistent frame counts, digest shape and safe
relative output paths. Imported indexes are not trusted merely because they parse.

Repeated image content is legal. Duplicate/nonmonotonic presentation timestamps are
not silently repaired. The last frame requires a decoded duration or an exact stream
endpoint; nominal frame rate is not an acceptable guess. Quantized 30 fps in a 1 ms
container clock is distinguished from genuinely variable timing.

## Export transaction

The original file is probed and fingerprinted. Scene output is written to an owned
`.partial`. Default CLI review copying checks its codec/geometry/audio inventory and
digest, saves intended ranges, and publishes without a decoded-equality claim.
Explicit exact-mode media is decoded independently, compared with source frames and audio samples, and
only then finalized without clobbering an existing target. Certificates contain the
method, tested native properties, timings, sample/pixel equality and content digest.

Resume is conservative: a completed clip is reused only when its certificate and
current output digest agree. `verify` follows certificate policy: review integrity and
inventory, or explicit-mode decoded comparison. A source, option, tool/detector version or imported-index change requires a new
job directory. No existing clip is deleted to make a rerun appear successful.

An abrupt kill can occur after media finalization but before certificate persistence.
Such an uncertified orphan is refused on resume, not assumed valid. Move that orphan
out of the job directory and retry, or start a new output directory. Catchable
interruptions unwind locks and subprocesses; an uncatchable kill can leave scratch data.

## Concurrency and resource limits

Batch uses spawned processes, not shared OpenCV RNG state in Python threads. Default
one job and two decoder threads are deliberately conservative. `--jobs` is bounded to
1–8 and warns about CPU oversubscription. Each file has independent failure/state data.
The operator controls output disk location. Lossless export can greatly expand data;
there is no reliable universal preflight size prediction.

Review processing creates no full-source raw cache. A per-input logical temporary-byte
ledger tracks filter scripts, streamed metrics, metadata and the reserved partial-media
ceiling; the media child receives an OS file-size limit. Batch reporting uses a shared
parent ledger backed by reserved bytes deducted from each worker's allowance. Published
assets/logs and filesystem block overhead are excluded; explicit legacy-mode caches
remain unbounded. Selected assembly uses one bounded partial output and no joined cache.

Pool worker handles are retained so an actual early worker exit resolves unreturned
jobs as unconfirmed failures instead of waiting forever for a replaced worker's result.
Progress drain has a bounded shutdown wait. Controlled worker exit is tested, not every
mid-IPC hard-kill scenario. No elapsed-time media-job timeout is imposed on live workers.

The approved next-generation design for compact export, structured progress, transition
review, and constrained keyframe planning is documented in
[Compact Export, Progress, and Editorial Planning Design](superpowers/specs/2026-09-16-compact-export-progress-design.md).

Analysis is bounded in image memory, but numeric timelines scale with frame count.
The per-frame preservation audit collects FFprobe JSON for the source, and reference
hashes scale with frame count. Canonical PCM audio is temporary disk data. These are
not constant-memory promises for unlimited-duration inputs. The measured corpus and
normal twenty-minute workload fit comfortably; arbitrary multi-day inputs are untested.
