# Exact cutting and preservation policy

Correct decoded boundaries take precedence over compressed-byte copying. FFmpeg seek
options alone are not proof of exactness. Every exported scene must decode to exactly
the requested source ordinals with matching native pixel hashes and presentation times.
The code never relocates a cut to a convenient keyframe.

## Three paths

**Whole-file copy.** When the requested scene is the entire source and mode is not
`lossless`, copy all bytes, verify the full-file SHA-256, and decode/verify all video
frames. Container, audio, ancillary streams and metadata are unchanged by construction.
This does not claim to repair corrupt source media.

**Eligible video stream copy.** A start at a decoded keyframe and end at another
keyframe or EOF permit an attempt, not a correctness presumption. Decoder references,
B-frame ordering, muxer constraints or incomplete final GOPs can invalidate it. Decode
verification checks all native pixels, frame count, each PTS, endpoint, sample data and
A/V offsets. A failed attempt is discarded and logged. `copy-only` fails rather than
snapping a boundary or falling back. Audio for a partial scene still follows the PCM
sample-exact policy below; `copy-only` means video stream copying, not all-stream copying.

**Full-scene lossless re-encode.** Arbitrary H.264 or HEVC cuts use libx264 QP 0 or
libx265 lossless mode. Restricted FFV1 is supported for compatible Matroska timing.
Original resolution, native pixel format/bit depth, aspect/rotation and known color
attributes are retained and independently compared. Output profiles, rate control,
bitrate and container may differ. MOV is used for partial H.264/HEVC to preserve exact
video/audio clocks. Lossless re-encoding is not compressed-byte preservation.

This release does not join newly encoded edge GOPs to copied interior GOPs. Such a
hybrid requires codec-parameter/extradata, reference, timestamps and audio handling that
were not established as safe here. Choosing a simpler verified fallback is preferable
to advertising unproven “smart lossless cuts.” Key-aligned copy and fallback were
actually exercised, including real source attempts rejected for nonmonotonic DTS.

## What verification really checks

For every native decoded source/output video frame: ordinal order, pixel SHA-256,
frame count and rational relative PTS must agree. First and last frames are therefore
checked as part of *all-frame* comparison, not as approximate image matching. The last
frame's displayed duration is checked too. Native hashes retain 10-bit pixels; RGB
analysis thumbnails are never used as export references.

An empirical MOV failure drove a specific regression: FFmpeg's filtered frame had no
usable final duration, so a muxed last packet was marked discardable even though the
command succeeded. Explicit encoder time base and a `setts` final-duration policy fix
this for tested MOV paths. The suite includes one-frame clips, actual B-frame inputs,
irregular VFR and nonzero source timestamps. Packet count alone is not the test.

Rotation metadata is preserved rather than applied to pixels. Tests actually set a
display rotation and check the output matrix and native frame hashes. Stream-only color
flags proved insufficient in an HDR test, so fixtures embed color properties in frames
and the exporter performs a full per-frame side-data/property audit.

## Audio clocks

Each audio stream is decoded once into a native-precision PCM representation. A partial
scene includes samples whose original presentation instants fall in the half-open
video interval. Both endpoints use the original audio sample clock, rounded upward;
there is no resampling or accumulated rounding from successive scenes. When the first
included sample falls after the video's first frame, its offset is represented as closely
as the output audio clock permits. The verifier enforces at most one output audio-clock
tick (normally one sample) and records the exact rational timing error; arbitrary
fractional offsets are not promised to be exactly representable. Streams with no
temporal overlap are recorded, not fabricated. Leading or trailing audio outside the
requested video's half-open interval is not included in partial exports; whole-file
copying retains all original bytes.

The output is decoded again and its samples, count, rate, layout and offset are compared.
AAC generally becomes 32-bit float PCM, not another AAC generation. Quantized container
packet timestamps may jitter by one source-clock tick; the decoder checks bounded
jitter without silently smoothing a real gap or drift. Missing/unsupported audio layouts
or discontinuous clocks are rejected. Actual 44.1/48 kHz and multiple-stream tests cover
different clocks and a delayed stream. No-audio video is supported.

Audio packet copying could avoid this conversion when a suitable codec/container cut
is independently proven safe, but is not implemented for partial scenes. The choice
preserves decoded sound and synchronization at the cost of file size and original codec.

## Explicit refusals and remaining risks

Partial export refuses HDR/PQ/HLG/Dolby Vision or unsupported dynamic side data, interlacing,
changing native geometry/color/pixel properties, subtitles/data/chapters that require
retiming, unhandled codecs and incompatible time bases. They are not silently normalized
or discarded. Whole-file copying preserves such data unchanged. General HDR-preserving
splitting is **not** a delivered capability.

A keyframe flag is not proof of an independently decodable GOP. Testing covers B-frame
streams, long GOPs through arbitrary cuts, nonzero PTS and explicit copy failures, not
every codec's open-GOP/leading-picture behavior. Unsafe attempts fall back or fail closed.

Lossless H.264 may use a profile unavailable to some consumer players. QuickTime playback,
Apple hardware decode and macOS 27 behavior remain unverified. FFmpeg decode equality is
strong evidence of media correctness for the tested decoder, not universal player
compatibility. VideoToolbox is not used by production paths until native pixel/timestamp
and preservation behavior has been measured on the target hardware.

Metadata is preserved where explicitly mapped and tested; this is not a claim that all
possible private container tags, encryption, attachments or vendor metadata survive a
container conversion. The verification certificate states the fields actually checked.

## Primary implementation references

- FFmpeg CLI seeking, timestamp and encoder-time-base semantics: https://ffmpeg.org/ffmpeg.html
- Trim/atrim/setpts/asetpts filter definitions: https://ffmpeg.org/ffmpeg-filters.html
- Packet `setts` bitstream filter: https://ffmpeg.org/ffmpeg-bitstream-filters.html#setts
- MOV timescales and edit-list behavior: https://ffmpeg.org/ffmpeg-formats.html
- Apple's VideoToolbox API: https://developer.apple.com/documentation/videotoolbox

References were reviewed during 2026-09-15/16 UTC execution. The evidence is the actual
export certificates and regression tests, not an inference from these manuals alone.

## Output filesystem constraint

Finalization uses an atomic, no-clobber hard link beside the staged clip. The chosen
output filesystem must support hard links. Unsupported filesystems fail rather than
falling back to an overwrite-prone rename. Existing output directories retain their
permissions; newly created job directories are owner-only.
