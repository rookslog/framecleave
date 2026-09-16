# Astra stream-copy consult — 2026-09-16

## 1. Conclusion

**[Recommendation]** Treat arbitrary-boundary video **and audio** stream-copy as the first implementation candidate for fast review. Imperfect edges are an accepted tradeoff, not automatic grounds for re-encoding or refusal. My earlier advice overconstrained this workflow around preservation guarantees the user did not require.

**[Inference]** Practicality depends on the measured preview experience, speed, storage, and eventual join—not whether each temporary slice independently reproduces every requested frame. Parent-run experiments should decide the command policy.

## 2. What current primary sources establish

**[Source-supported] Input `-ss`:** FFmpeg seeks to an earlier seek point when necessary; stream-copy preserves the intervening material. This is a credible fast, potentially padded preview strategy. **`-copyinkf`** explicitly permits copying initial non-keyframes. Neither option promises exact visible edges. [FFmpeg CLI documentation](https://ffmpeg.org/ffmpeg.html#Main-options)

**[Source-supported] Output `-ss`:** Current `of_streamcopy()` applies start-time packet gates and, absent `copy_initial_nonkeyframes`, skips initial non-key packets. Therefore compare output seeking both with and without `-copyinkf`; do not describe stream-copy as decoding and precisely trimming frames. Master source is not proof of the installed version’s behavior. [FFmpeg stream-copy implementation](https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/fftools/ffmpeg_mux.c)

**[Source-supported] Segment muxer:** `break_non_keyframes=1` allows non-keyframe starts. FFmpeg documents player-dependent playback/seeking behavior. It warrants a one-pass performance comparison against launching one command per scene. [Segment documentation](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment)

**[Source-supported] Concat demuxer:** Inputs need matching streams/codecs/time bases. `inpoint` can yield preceding packets and overlapping timestamps; `outpoint` uses decoding timestamps and can yield displayed frames beyond the requested endpoint. These are documented semantics, not evidence that the parent’s material will be unusable. [Concat documentation](https://ffmpeg.org/ffmpeg-formats.html#concat)

**[Source-supported] Decoded alternatives:** FFmpeg documents `segment_time_metadata` with `select=concatdec_select` and `aselect=concatdec_select` for filtering concat-demuxer intervals. The concat filter instead joins decoded streams; segments must start at zero, matching parameters are required, and shorter audio can be padded. [Official filter documentation source](https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/doc/filters.texi)

**[Recommendation]** Compare: input-seek copies for padded playback; output-seek copies with `-copyinkf` for tighter packet selection; concat-demuxer selection followed by one encode; and independently decoded, trimmed inputs followed by concat and one encode. Do not require a large intermediate joined file.

## 3. Can joining recover missing references?

**[Inference]** Encoding cannot reconstruct unavailable original reference information. But “slice starts on a non-keyframe” does **not** establish that references are unavailable: preroll may remain in the container, or adjacent original packets may be present in a joined stream.

**[Inference]** Joining contiguous, compatible slices could restore useful decoder context if the required packets survive in the correct sequence. Joining noncontiguous selections cannot be assumed to supply the correct references. A successful re-encode may also preserve concealed artifacts. These possibilities require experiments, not categorical predictions.

**[Recommendation]** Retain source-range provenance independently of temporary clips. A source-backed final render can read the original with decoder lead-in, discard unwanted decoded material, and encode selected content once. Padded copies are another option, but record both requested and physically retained ranges; padding costs space and must not become unintended final content.

## 4. Focused experiments

**[Recommendation]** Use the parent’s bounded corpus and installed FFmpeg version; compare:

1. Input `-ss` plus `-c:v copy -c:a copy`.
2. Output `-ss`, with/without `-copyinkf`.
3. Segment muxing with `break_non_keyframes=1`.
4. Joining adjacent clips, then nonadjacent selections, followed by one encode.
5. The same selected ranges rendered from originals, including concat-demuxer and decoded-concat variants.

**[Recommendation]** Record wall time, aggregate bytes, packet timestamp spans, first playable picture, visible edge anomalies, audio continuity, and final joins. Include clips shorter than a GOP, B-frame edges, VFR, delayed audio, and EOF. Decode comparisons are useful diagnostics here—not mandatory acceptance gates. Inspect the actual intended player; successful muxing alone does not settle review usability.

**[Source-supported]** The repository always supplies `-xerror`: `src/framecleave/media.py:40`, "‑loglevel", level, "‑xerror". Current FFmpeg source makes non-monotonic DTS fatal under `exit_on_error`, otherwise adjusting timestamps with a warning. [Mux implementation](https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/fftools/ffmpeg_mux.c)

**[Recommendation]** Test that strictness independently; do not let preservation-oriented error policy prejudge tolerant previews.

## 5. Minimal plan adjustment and material caveats

**[Recommendation]** Keep observability work. Replace per-scene compact encoding as the primary workflow with fast audiovisual copies, explicit no-reencode behavior, selection provenance, then one final encode. Keep exact/lossless modes optional. Defer hybrid GOP work and mandatory snapping.

**[Source-supported]** x265 CRF controls quality, not target bitrate; complexity determines size. CRF16/18 cannot promise near-original size. [x265 CRF documentation](https://x265.readthedocs.io/en/master/cli.html#cmdoption-crf)

**[Recommendation]** Enforce the 1.5× temporary ceiling across copies, padding, partials, and concurrency; establish whether final output counts toward it. If copies plus final output exceed the ceiling, use original-backed rendering or reclaim regenerable previews under an explicit lifecycle. Cross-source stream differences and audio join timing—not pixel equality—are the remaining architecture-changing constraints.
