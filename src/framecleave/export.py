"""Fail-closed frame-exact export with decoded-pixel and PCM-sample verification.

Arbitrary cuts use same-codec lossless re-encoding, not a lossy 'visually exact' test.
Verified whole-file/closed-boundary copying is preferred. Hybrid GOP splicing is not
assumed safe. Incompatible auxiliary/HDR/interlaced media is rejected before encoding.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import logging
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

from .audio import AudioSlice, audio_encoding, extract_audio, slice_track
from .media import (MediaError, MediaInfo, PreservationError, audit_frame_metadata, ffmpeg_base,
                    hdr_metadata_present, probe, run, sha256_file, video_hashes)
from .model import Timeline
from .policy import ExportPolicy, bind_encoder_build, policy_digest, resolve_policy
from .progress import ProgressReporter, ProgressSink

LOG = logging.getLogger(__name__)
KNOWN = {None, "unknown", "unspecified", "N/A"}
ATTRIBUTES = ("codec_name", "width", "height", "pix_fmt", "sample_aspect_ratio", "color_range",
              "color_space", "color_transfer", "color_primaries", "chroma_location")


def whole_scene(scene: dict, timeline: Timeline) -> bool:
    return scene["start_frame"] == 0 and scene["end_frame"] == timeline.frame_count


def output_suffix(info: MediaInfo, timeline: Timeline, scene: dict, mode: str = "auto") -> str:
    if whole_scene(scene, timeline) and mode != "lossless":
        return info.path.suffix.lower() or ".mkv"
    if mode == 'review-copy':
        return '.mp4'
    return ".mkv" if info.video["codec_name"] == "ffv1" else ".mov"


def decimal_seconds(value: Fraction) -> str:
    # FFmpeg seeking is microsecond-granular. It is only an optimization; exact filters
    # and decoded verification, not this rounded value, establish the cut boundary.
    return f"{float(value):.12f}"


def check_preservation(info: MediaInfo) -> None:
    video = info.video
    extras = [s for s in info.document["streams"] if s["index"] != video["index"] and s.get("codec_type") != "audio"]
    if extras:
        raise PreservationError("Auxiliary/subtitle/data/attached-picture streams require unsupported retiming; none were dropped")
    if info.document.get("chapters"):
        raise PreservationError("Chapter retiming is not yet verified; no chapter metadata was silently discarded")
    if video.get("field_order") not in KNOWN | {"progressive"}:
        raise PreservationError("Interlaced export is not verified")
    if video.get("codec_name") not in {"h264", "hevc", "ffv1"}:
        raise PreservationError("Exact export currently supports H.264, HEVC and FFV1; detection is broader")
    if hdr_metadata_present(video):
        raise PreservationError("HDR/Dolby Vision side-data preservation is not verified; export refused")
    if video["codec_name"] == "ffv1" and info.time_base.denominator != 1000:
        raise PreservationError("FFV1 export requires the Matroska millisecond time base to avoid hidden timestamp quantization")
    if info.time_base.denominator > 2**31 - 1:
        raise PreservationError("Source time base exceeds the MOV track-timescale range")


def compare_properties(source: MediaInfo, output: MediaInfo) -> dict:
    checked = {}
    for name in ATTRIBUTES:
        value = source.video.get(name)
        if value not in KNOWN:
            actual = output.video.get(name)
            if actual != value:
                raise PreservationError(f"Export changed {name}: {value!r} -> {actual!r}")
            checked[name] = value
    source_rotation = [d.get("rotation") for d in source.video.get("side_data_list", []) if "rotation" in d]
    output_rotation = [d.get("rotation") for d in output.video.get("side_data_list", []) if "rotation" in d]
    if source_rotation != output_rotation:
        raise PreservationError("Export changed rotation/display orientation metadata")
    checked["rotation"] = source_rotation
    return checked


class ExportSession:
    def __init__(self, info: MediaInfo, timeline: Timeline, work_directory: Path, *, threads: int = 2,
                 mode: str = "auto", progress: ProgressSink | None = None, job_id: str | None = None,
                 reporter: ProgressReporter | None = None, diagnostics: str | None = None,
                 policy: ExportPolicy | None = None, bind_reference_encoder: bool = True,
                 defer_certified: bool = False):
        if mode not in {"compact", "auto", "lossless", "copy-only"}:
            raise ValueError("Export mode must be compact, auto, lossless, or copy-only")
        self.info = info
        self.timeline = timeline
        self.threads = threads
        self.policy = (bind_encoder_build(policy) if policy and bind_reference_encoder else policy) or (
                       resolve_policy(mode, source_codec=info.video["codec_name"], threads=threads))
        if self.policy.mode != mode:
            raise ValueError("Export policy mode differs from the requested mode")
        self.mode = self.policy.mode
        if mode == 'compact' and self.policy.video.encoder != {'h264': 'libx264', 'hevc': 'libx265'}.get(info.video['codec_name']):
            raise ValueError('Compact policy encoder differs from the source codec family')
        self.progress = reporter or ProgressReporter(progress, job_id=job_id)
        self.diagnostics = diagnostics
        self.defer_certified = defer_certified
        self._pending_certified: tuple[str, str, bool] | None = None
        self.reference: list[dict] | None = None
        self.audio = None
        self.frame_audit = None
        parent = Path(work_directory)
        parent.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="framecleave-export-", dir=parent))

    def __enter__(self) -> "ExportSession":
        return self

    def __exit__(self, *_) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def prepare(self, *, audio: bool = True) -> None:
        if self.reference is None:
            self.reference = video_hashes(self.info, threads=self.threads)
            if len(self.reference) != self.timeline.frame_count:
                raise MediaError("Source decoded frame count changed since analysis")
            if [r["pts"] for r in self.reference] != self.timeline.pts:
                raise MediaError("Source decoded PTS changed since analysis")
        if audio and self.frame_audit is None:
            self.frame_audit = audit_frame_metadata(self.info, threads=self.threads)
        if audio and self.audio is None:
            self.audio = extract_audio(self.info, self.work / "canonical-audio", threads=self.threads)

    def verify_exact_video(self, scene: dict, output: MediaInfo, *, whole: bool = False) -> dict:
        self.prepare(audio=False)
        assert self.reference is not None
        decoded = video_hashes(output, threads=self.threads)
        expected = self.reference[scene["start_frame"]:scene["end_frame"]]
        if len(decoded) != len(expected):
            raise MediaError(f"Export decoded {len(decoded)} frames, expected {len(expected)}")
        origin = Fraction(0) if whole else self.timeline.endpoint(scene["start_frame"]) * self.timeline.time_base
        for offset, (actual, source) in enumerate(zip(decoded, expected, strict=True)):
            if actual["sha256"] != source["sha256"] or actual["size"] != source["size"]:
                raise MediaError(f"Export changed decoded pixels at source frame {scene['start_frame'] + offset}")
            expected_time = source["pts"] * self.info.time_base - origin
            if actual["pts"] * output.time_base != expected_time:
                raise MediaError(f"Export changed the PTS of source frame {scene['start_frame'] + offset}")
        end = (decoded[-1]["pts"] + decoded[-1]["duration"]) * output.time_base
        expected_end = self.timeline.endpoint(scene["end_frame"]) * self.timeline.time_base - origin
        if end != expected_end:
            raise MediaError(f"Export final-frame endpoint {end} differs from expected {expected_end}")
        properties = compare_properties(self.info, output)
        digest = hashlib.sha256("".join(x["sha256"] for x in decoded).encode()).hexdigest()
        return {
            "frames_verified": len(decoded), "pixel_equality": "equal",
            "all_native_pixels_equal": True, "all_pts_equal": True,
            "first_source_frame": scene["start_frame"], "last_source_frame": scene["end_frame"] - 1,
            "first_frame_sha256": decoded[0]["sha256"], "last_frame_sha256": decoded[-1]["sha256"],
            "ordered_frame_hashes_sha256": digest, "end_time_rational": str(end),
            "preserved_attributes": properties,
            "source_profile": self.info.video.get("profile"), "output_profile": output.video.get("profile"),
        }

    def verify_video(self, scene: dict, output: MediaInfo, *, whole: bool = False) -> dict:
        """Backward-compatible exact verifier name for library callers and schema-1 jobs."""
        return self.verify_exact_video(scene, output, whole=whole)

    def verify_compact_video(self, scene: dict, output: MediaInfo) -> dict:
        """Check compact structure without making a native-pixel equality claim."""
        self.prepare(audio=False)
        assert self.reference is not None
        decoded = video_hashes(output, threads=self.threads)
        expected = self.reference[scene['start_frame']:scene['end_frame']]
        if len(decoded) != len(expected):
            raise MediaError(f'Export decoded {len(decoded)} frames, expected {len(expected)}')
        origin = self.timeline.endpoint(scene['start_frame']) * self.timeline.time_base
        for offset, (actual, source) in enumerate(zip(decoded, expected, strict=True)):
            expected_time = source['pts'] * self.info.time_base - origin
            if actual['pts'] * output.time_base != expected_time:
                raise MediaError(f"Export changed the PTS of source frame {scene['start_frame'] + offset}")
        end = (decoded[-1]['pts'] + decoded[-1]['duration']) * output.time_base
        expected_end = self.timeline.endpoint(scene['end_frame']) * self.timeline.time_base - origin
        if end != expected_end:
            raise MediaError(f'Export final-frame endpoint {end} differs from expected {expected_end}')
        with tempfile.TemporaryDirectory(prefix='compact-reference-', dir=self.work) as temporary:
            reference_path = Path(temporary) / 'reference.mov'
            command = self._command(scene, reference_path, [], copy=False, seek=False)
            command[command.index('-vf') + 1] = (
                f"trim=start_frame={scene['start_frame']}:end_frame={scene['end_frame']},"
                f"setpts=PTS-{self.timeline.endpoint(scene['start_frame'])}"
            )
            run(command)
            reference = video_hashes(probe(reference_path, fingerprint=False), threads=self.threads)
            if len(reference) != len(decoded) or any(
                actual['sha256'] != expected['sha256'] or actual['size'] != expected['size']
                for actual, expected in zip(decoded, reference, strict=True)
            ):
                raise MediaError('Export changed compact frame correspondence under the resolved policy')
            quality = self._compact_quality(scene, output, Path(temporary))
        return {
            'frames_verified': len(decoded), 'pixel_equality': 'not_applicable',
            'all_pts_equal': True, 'decode_success': True,
            'first_source_frame': scene['start_frame'], 'last_source_frame': scene['end_frame'] - 1,
            'end_time_rational': str(end), 'preserved_attributes': compare_properties(self.info, output),
            'content_correspondence': 'independent-frame-ordinal-reference-encode-v1',
            'reference_encoder_build': self.policy.video.encoder_build,
            'ordered_reference_frame_hashes_sha256': hashlib.sha256(
                ''.join(row['sha256'] for row in reference).encode()).hexdigest(),
            'quality': quality,
        }

    def _compact_quality(self, scene: dict, output: MediaInfo, directory: Path) -> dict:
        evidence = {'frames_compared': scene['frame_count']}
        start_pts = self.timeline.endpoint(scene['start_frame'])
        end_pts = self.timeline.endpoint(scene['end_frame'])
        keyframe = max((k for k in self.timeline.keyframes if k <= scene['start_frame']), default=0)
        # -copyts keeps the source's absolute PTS, but a container start-time offset
        # (e.g. an MP4 edit list) is not applied to -ss; seek within the raw media.
        raw_origin = self.info.document.get('format', {}).get('start_time')
        origin = (self.timeline.pts[0] * self.timeline.time_base if raw_origin in {None, 'N/A'}
                  else Fraction(raw_origin))
        seek_time = self.timeline.pts[keyframe] * self.timeline.time_base - origin
        for metric, key in (('ssim', 'All'), ('psnr', 'psnr_avg')):
            stats = directory / f'{metric}.txt'
            graph = (
                f"[0:{self.info.video['index']}]trim=start_pts={start_pts}:"
                f"end_pts={end_pts},setpts=PTS-STARTPTS[source];"
                f"[1:{output.video['index']}]setpts=PTS-STARTPTS[output];"
                f"[source][output]{metric}=stats_file={metric}.txt:shortest=1:repeatlast=0[metric]"
            )
            command = ffmpeg_base() + ['-filter_complex_threads', '1', '-threads', str(self.threads), '-copyts']
            if seek_time >= 0:
                command += ['-seek_timestamp', '1', '-ss', decimal_seconds(seek_time)]
            command += ['-noautorotate', '-protocol_whitelist', 'file,pipe,crypto',
                        '-i', str(self.info.path), '-noautorotate',
                        '-protocol_whitelist', 'file,pipe,crypto', '-i', str(output.path),
                        '-filter_complex', graph, '-map', '[metric]', '-an', '-f', 'null', '-']
            run(command, cwd=directory)
            values = []
            if not stats.is_file():
                raise MediaError(f'Missing compact {metric} quality metric file')
            with stats.open(encoding='utf-8') as handle:
                for line in handle:
                    entries = dict(part.split(':', 1) for part in line.split() if ':' in part)
                    try:
                        value = float(entries[key])
                    except (KeyError, ValueError) as exc:
                        raise MediaError(f'Missing compact {metric} quality metric') from exc
                    if math.isnan(value) or (metric == 'ssim' and not math.isfinite(value)):
                        raise MediaError(f'Invalid compact {metric} quality metric')
                    values.append(value)
            if len(values) != scene['frame_count']:
                raise MediaError(f'Compact {metric} metric count differs from requested frames')
            mean = sum(values) / len(values)
            minimum = min(values)
            evidence[metric] = {'mean': mean if math.isfinite(mean) else 'infinity',
                                'minimum': minimum if math.isfinite(minimum) else 'infinity'}
        return evidence

    def verify_audio(self, output: MediaInfo, slices: list[AudioSlice], directory: Path) -> list[dict]:
        decoded = extract_audio(output, directory, threads=self.threads)
        if len(decoded) != len(slices):
            raise MediaError("Export changed the number of overlapping audio streams")
        verified = []
        for track, expected in zip(decoded, slices, strict=True):
            codec, encoding_reason = audio_encoding(expected.track, self.policy.audio.codec)
            if output.audio[len(verified)]['codec_name'] != codec:
                raise PreservationError('Export audio codec differs from the resolved encoding policy')
            if (track.rate, track.channels, track.layout) != (expected.track.rate, expected.track.channels, expected.track.layout):
                raise PreservationError("Audio sample rate or channel layout changed")
            if track.samples != expected.samples or sha256_file(track.path) != expected.sha256:
                raise MediaError("Export changed, lost, or duplicated decoded audio samples")
            tolerance = max(Fraction(1, track.rate), Fraction(output.audio[len(verified)]["time_base"]))
            error = abs(track.origin - expected.delay)
            if error > tolerance:
                raise MediaError(f"Audio/video synchronization error {error} exceeds one output clock tick {tolerance}")
            verified.append({**expected.evidence(), "samples_verified": track.samples,
                             "sample_equality": "equal",
                             "codec": codec, "encoding_reason": encoding_reason,
                             "all_samples_equal": True, "first_sample_timing_error_rational": str(error),
                             "timing_error_limit_rational": str(tolerance)})
        return verified

    def _command(self, scene: dict, target: Path, slices: list[AudioSlice], *, copy: bool, seek: bool) -> list[str]:
        t = self.timeline
        start_pts = t.endpoint(scene["start_frame"])
        end_pts = t.endpoint(scene["end_frame"])
        start = start_pts * t.time_base
        duration = (end_pts - start_pts) * t.time_base
        command = ffmpeg_base() + ["-y", "-filter_threads", "1", "-threads", str(self.threads)]
        if not copy:
            command += ["-copyts"]
        if seek:
            key = max((k for k in t.keyframes if k <= scene["start_frame"]), default=0)
            seek_time = start if copy else t.pts[key] * t.time_base
            if seek_time >= 0:
                command += ["-seek_timestamp", "1", "-ss", decimal_seconds(seek_time)]
        command += ["-noautorotate", "-protocol_whitelist", "file,pipe,crypto", "-i", str(self.info.path)]
        for part in slices:
            a = part.track
            command += ["-f", a.raw_format, "-ar", str(a.rate), "-ch_layout", a.layout, "-i", str(part.path)]
        command += ["-map", f"0:{self.info.video['index']}"]
        for i in range(len(slices)):
            command += ["-map", f"{i + 1}:a:0"]
        command += ["-map_metadata", "0", "-map_chapters", "-1", "-avoid_negative_ts", "disabled"]
        if copy:
            command += ["-c:v", "copy", "-t", decimal_seconds(duration)]
        else:
            command += ["-vf", f"trim=start_pts={start_pts}:end_pts={end_pts},setpts=PTS-{start_pts}",
                        "-fps_mode", "passthrough", "-enc_time_base", f"{t.time_base.numerator}:{t.time_base.denominator}",
                        "-pix_fmt", self.info.video["pix_fmt"], "-threads:v",
                        str(self.policy.video.encoder_threads if self.mode == 'compact' else self.threads)]
            codec = self.info.video["codec_name"]
            if self.mode == 'compact':
                video = self.policy.video
                command += ['-c:v', video.encoder, '-preset', video.preset, '-crf', str(video.crf)]
                if codec == 'hevc':
                    command += ['-x265-params', f'bframes=0:pools={video.encoder_threads}:frame-threads=1:log-level=error']
                else:
                    command += ['-bf', '0']
            elif codec == "hevc":
                command += ["-c:v", "libx265", "-preset", "ultrafast", "-x265-params",
                            f"lossless=1:bframes=0:pools={self.threads}:frame-threads=1:log-level=error"]
            elif codec == "h264":
                command += ["-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-bf", "0"]
            else:
                command += ["-c:v", "ffv1", "-level", "3", "-slicecrc", "1"]
            # setpts clears frame duration in FFmpeg 7. The final packet must not have
            # zero duration: MOV otherwise marks the last decoded frame discardable.
            last_duration = end_pts - t.pts[scene["end_frame"] - 1]
            command += ["-bsf:v", f"setts=duration={last_duration}"]
            for field, option in (("color_range", "-color_range"), ("color_space", "-colorspace"),
                                  ("color_transfer", "-color_trc"), ("color_primaries", "-color_primaries"),
                                  ("chroma_location", "-chroma_sample_location")):
                value = self.info.video.get(field)
                if value not in KNOWN:
                    command += [option, str(value)]
        for i, part in enumerate(slices):
            a = part.track
            codec, _ = audio_encoding(a, self.policy.audio.codec)
            command += [f"-c:a:{i}", codec, f"-filter:a:{i}",
                        f"asetpts=PTS+({part.delay.numerator}/{part.delay.denominator})/TB",
                        f"-map_metadata:s:a:{i}", f"0:s:{a.stream_index}"]
            flags = [key for key, value in a.metadata.get("disposition", {}).items() if value]
            command += [f"-disposition:a:{i}", "+".join(flags) or "0"]
            if codec == 'alac':
                command += [f'-sample_fmt:a:{i}', 's16p']
        if self.info.video["codec_name"] != "ffv1":
            timescale = math.lcm(t.time_base.denominator, *(p.track.rate for p in slices))
            if timescale > 2**31 - 1:
                raise PreservationError("No exact common MOV timescale for these video/audio clocks")
            command += ["-video_track_timescale", str(t.time_base.denominator), "-movie_timescale", str(timescale),
                        "-movflags", "+faststart+use_metadata_tags", "-f", "mov"]
            if self.info.video["codec_name"] == "hevc":
                command += ["-tag:v", "hvc1"]
        else:
            command += ["-f", "matroska"]
        command.append(str(target))
        return command

    def export(self, scene: dict, target: Path) -> dict:
        target = Path(target)
        scene_id = str(scene["number"])
        self.progress.emit("scene_started", "exporting", scene_id=scene_id)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.monotonic()
        partial = target.with_name(target.name + ".partial")
        if partial.exists() or partial.is_symlink():
            raise FileExistsError(f"Unowned partial output exists: {partial}")
        failures = []
        attempt_records = []
        certified = False
        try:
            if whole_scene(scene, self.timeline) and self.mode != "lossless":
                self.progress.emit("attempt_started", "exporting", scene_id=scene_id,
                                   attempt_id="whole-file-copy")
                attempt_records.append({"attempt_id": "whole-file-copy", "method": "whole-file-copy",
                                        "outcome": "certified"})
                self.prepare(audio=False)
                shutil.copyfile(self.info.path, partial)
                if sha256_file(partial) != self.info.sha256:
                    raise MediaError("Whole-file copy digest mismatch")
                video = self.verify_video(scene, probe(partial, fingerprint=False), whole=True)
                result = {"method": "whole-file-copy", "video": video, "audio": [],
                          "all_streams_byte_identical": True, "output_timestamp_origin": "source"}
            else:
                check_preservation(self.info)
                self.prepare()
                with tempfile.TemporaryDirectory(prefix="scene-", dir=self.work) as temp:
                    directory = Path(temp)
                    start = self.timeline.endpoint(scene["start_frame"]) * self.timeline.time_base
                    end = self.timeline.endpoint(scene["end_frame"]) * self.timeline.time_base
                    parts = [p for a in self.audio for p in [slice_track(a, start, end, directory / "slices")] if p is not None]
                    aligned = scene["start_frame"] in self.timeline.keyframes and (
                        scene["end_frame"] in self.timeline.keyframes or scene["end_frame"] == self.timeline.frame_count)
                    if self.mode == "copy-only" and not aligned:
                        raise PreservationError("copy-only requires decoded keyframe-aligned boundaries; no snapping is permitted")
                    attempts = [(True, True)] if aligned and self.mode != "lossless" else []
                    if self.mode != "copy-only":
                        attempts += [(False, True), (False, False)]
                    for attempt_number, (copy, seek) in enumerate(attempts, 1):
                        method = "stream-copy" if copy else "compact" if self.mode == 'compact' else "lossless"
                        attempt_id = f"{method}-{'seek' if seek else 'full'}-{attempt_number}"
                        self.progress.emit("attempt_started", "exporting", scene_id=scene_id,
                                           attempt_id=attempt_id)
                        try:
                            command = self._command(scene, partial, parts, copy=copy, seek=seek)
                            run(command)
                            output = probe(partial, fingerprint=False)
                            video = (self.verify_compact_video(scene, output)
                                     if self.mode == 'compact' and not copy else self.verify_exact_video(scene, output))
                            audio = self.verify_audio(output, parts, directory / "verify-audio")
                            export_method = "stream-copy-video" if copy else "compact-reencode" if self.mode == 'compact' else "lossless-reencode"
                            result = {"method": export_method,
                                      "video": video, "audio": audio, "output_timestamp_origin": "scene-video-start",
                                      "attempt_failures": failures, "seek_optimization_used": seek,
                                      "source_frame_audit": self.frame_audit,
                                      "audio_streams_without_overlap": [a.stream_index for a in self.audio if a not in [p.track for p in parts]],
                                      "command": command}
                            attempt_records.append({"attempt_id": attempt_id,
                                                    "method": export_method,
                                                    "outcome": "certified"})
                            break
                        except MediaError as exc:
                            partial.unlink(missing_ok=True)
                            failures.append(str(exc))
                            attempt_records.append({"attempt_id": attempt_id, "method": method,
                                                    "outcome": "rejected",
                                                    "reason_code": "verification-or-mux-failed"})
                            LOG.debug("Export verification/attempt failed: %s", exc)
                            self.progress.emit(
                                "attempt_rejected", "exporting", scene_id=scene_id,
                                attempt_id=attempt_id, outcome="rejected",
                                reason_code="verification-or-mux-failed", diagnostics=self.diagnostics,
                            )
                    else:
                        raise MediaError("No verified export could be produced: " + "; ".join(failures))
            if self.mode == 'compact':
                result['video'].pop('all_native_pixels_equal', None)
            result.update(schema_version=2, policy=self.policy.to_dict(),
                          policy_digest=policy_digest(self.policy), attempts=attempt_records,
                          verification={"video": result["video"].get("pixel_equality", "equal"),
                                        "audio": "equal" if all(item.get("sample_equality") == "equal"
                                                                 for item in result["audio"]) else "different"})
            result["output_sha256"] = sha256_file(partial)
            result["output_size_bytes"] = partial.stat().st_size
            result["wall_seconds"] = time.monotonic() - start_time
            # Link is no-clobber and atomic on the same filesystem; unlike replace(),
            # it cannot overwrite an output created concurrently after our first check.
            os.link(partial, target)
            partial.unlink()
            certified = True
            if self.defer_certified:
                self._pending_certified = ("exporting", scene_id, bool(failures))
            else:
                self.progress.emit("scene_certified", "exporting", scene_id=scene_id,
                                   outcome="success", recovered=bool(failures))
            return result
        except BaseException as exc:
            if not certified:
                reason = "interrupted" if isinstance(exc, KeyboardInterrupt) else "export-failed"
                self.progress.emit("scene_failed", "exporting", scene_id=scene_id,
                                   outcome="failed", reason_code=reason,
                                   diagnostics=self.diagnostics)
            raise
        finally:
            partial.unlink(missing_ok=True)

    def publish_certified(self) -> None:
        """Emit the deferred success event once the caller has durably persisted the job."""
        if self._pending_certified is None:
            return
        phase, scene_id, recovered = self._pending_certified
        self._pending_certified = None
        self.progress.emit("scene_certified", phase, scene_id=scene_id, outcome="success", recovered=recovered)
