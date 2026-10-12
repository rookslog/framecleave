# Stream-copy review and one final encode

Audience: contributors evaluating the review workflow. This sanitized research
record keeps the decision rationale and primary-source findings. Source-specific
measurements, aggregate private results and raw experiments remain local.

## Owner-approved workflow

Detect scenes; packet-copy compressed audiovisual slices for review; select wanted
clips; decode/trim/concat the selected copies and encode once at CRF16/18 with AAC.
Imperfect review edges are acceptable. Do not introduce automatic per-scene encoding
or PCM/reference caches. Explicit exact/lossless contracts remain separate.

## Primary-source findings

- FFmpeg `-c copy` copies compressed packets without decoding/filtering/encoding;
  raw PCM caches are not inherent to slicing. [Streamcopy](https://ffmpeg.org/ffmpeg.html#Streamcopy)
- Input `-ss` may seek earlier than requested and retain lead-in material when
  copying. Output seeking and `-copyinkf` are distinct policies, neither a promise
  of exact displayed edges. [Main options](https://ffmpeg.org/ffmpeg.html#Main-options)
- Non-keyframe segmenting has documented player/seeking caveats. Successful muxing
  alone does not settle playback usability. [Segment muxer](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment)
- Concat-demuxer inputs need compatible streams/codecs/time bases. In/out points
  and shared-decoder joins are not interchangeable with independently decoded,
  trimmed inputs. [Concat demuxer](https://ffmpeg.org/ffmpeg-formats.html#concat)
- CRF controls quality, not a final size target. Lower values preserve more quality;
  CRF16/18 cannot promise a fixed ratio. [x265 CRF](https://x265.readthedocs.io/en/master/cli.html#cmdoption-crf)

## Command family and rationale

```sh
ffmpeg -ss START -i source.mkv -t DURATION \
  -map 0:v:0 -map '0:a:0?' -c copy -tag:v hvc1 slice.mp4
```

Omit the HEVC-specific tag for H.264. Container edit-list behavior and retained
decoder context can affect visible starts; a blanket prediction of broken starts
is unjustified. Conversely, a later successful encode cannot reconstruct missing
original references or guarantee artifact-free edges. Joining adjacent compatible
packets can restore useful context in bounded cases, but nonadjacent selection
must be tested independently. Record intended source ranges even when copied
physical packet spans differ.

The approved implementation uses input-seek MP4 review copies and independently
decoded, trimmed final assembly. Generated regression tests cover H.264/HEVC
selection, unavailable originals, audio padding and budget refusal. The complete
advisor response and independent code review remain in the advisor records.

## Limits and deferred alternatives

The temporary ceiling applies to owned unfinished media and logical metadata,
not persistent published clips/logs or explicit legacy caches. Budget refusal
must preserve originals and completed outputs, not silently lower quality.
Consumer playback, subjective quality, damaged tails, general media-format cases
and decoder concealment need separate qualification. No private throughput, final
size ratio, frame/sample equivalence or visual-quality measurement is published.
One-pass non-key segmenting, source-backed alternatives and hybrid GOP work remain
research options, not requirements for the approved review workflow.
