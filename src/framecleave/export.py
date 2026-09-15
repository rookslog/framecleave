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

from .audio import AudioSlice, extract_audio, slice_track
from .media import MediaError, MediaInfo, PreservationError, ffmpeg_base, probe, run, sha256_file, video_hashes
from .model import Timeline

LOG = logging.getLogger(__name__)
KNOWN = {None, "unknown", "unspecified", "N/A"}
ATTRIBUTES = ("width", "height", "pix_fmt", "sample_aspect_ratio", "color_range",
              "color_space", "color_transfer", "color_primaries", "chroma_location")


def whole_scene(scene: dict, timeline: Timeline) -> bool:
    return scene["start_frame"] == 0 and scene["end_frame"] == timeline.frame_count


def output_suffix(info: MediaInfo, timeline: Timeline, scene: dict, mode: str = "auto") -> str:
    if whole_scene(scene, timeline) and mode != "lossless":
        return info.path.suffix.lower() or ".mkv"
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
    side = str(video.get("side_data_list", [])).lower()
    if video.get("color_transfer") in {"smpte2084", "arib-std-b67"} or any(k in side for k in ("dovi", "dolby", "mastering", "content light", "hdr")):
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
    def __init__(self, info: MediaInfo, timeline: Timeline, work_directory: Path, *, threads: int = 2, mode: str = "auto"):
        if mode not in {"auto", "lossless", "copy-only"}:
            raise ValueError("Export mode must be auto, lossless, or copy-only")
        self.info = info
        self.timeline = timeline
        parent = Path(work_directory)
        parent.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="framecleave-export-", dir=parent))
        self.threads = threads
        self.mode = mode
        self.reference: list[dict] | None = None
        self.audio = None
        self.work.mkdir(parents=True, exist_ok=True)

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
        if audio and self.audio is None:
            self.audio = extract_audio(self.info, self.work / "canonical-audio", threads=self.threads)

    def verify_video(self, scene: dict, output: MediaInfo, *, whole: bool = False) -> dict:
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
            "frames_verified": len(decoded), "all_native_pixels_equal": True, "all_pts_equal": True,
            "first_source_frame": scene["start_frame"], "last_source_frame": scene["end_frame"] - 1,
            "first_frame_sha256": decoded[0]["sha256"], "last_frame_sha256": decoded[-1]["sha256"],
            "ordered_frame_hashes_sha256": digest, "end_time_rational": str(end),
            "preserved_attributes": properties,
            "source_profile": self.info.video.get("profile"), "output_profile": output.video.get("profile"),
        }

    def verify_audio(self, output: MediaInfo, slices: list[AudioSlice], directory: Path) -> list[dict]:
        decoded = extract_audio(output, directory, threads=self.threads)
        if len(decoded) != len(slices):
            raise MediaError("Export changed the number of overlapping audio streams")
        verified = []
        for track, expected in zip(decoded, slices, strict=True):
            if (track.rate, track.channels, track.layout) != (expected.track.rate, expected.track.channels, expected.track.layout):
                raise PreservationError("Audio sample rate or channel layout changed")
            if track.samples != expected.samples or sha256_file(track.path) != expected.sha256:
                raise MediaError("Export changed, lost, or duplicated decoded audio samples")
            tolerance = max(Fraction(1, track.rate), Fraction(output.audio[len(verified)]["time_base"]))
            error = abs(track.origin - expected.delay)
            if error > tolerance:
                raise MediaError(f"Audio/video synchronization error {error} exceeds one output clock tick {tolerance}")
            verified.append({**expected.evidence(), "samples_verified": track.samples,
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
                        "-pix_fmt", self.info.video["pix_fmt"], "-threads:v", str(self.threads)]
            codec = self.info.video["codec_name"]
            if codec == "hevc":
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
            command += [f"-c:a:{i}", a.codec, f"-filter:a:{i}",
                        f"asetpts=PTS+({part.delay.numerator}/{part.delay.denominator})/TB",
                        f"-map_metadata:s:a:{i}", f"0:s:{a.stream_index}"]
            flags = [key for key, value in a.metadata.get("disposition", {}).items() if value]
            command += [f"-disposition:a:{i}", "+".join(flags) or "0"]
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
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.monotonic()
        partial = target.with_name(target.name + ".partial")
        if partial.exists() or partial.is_symlink():
            raise FileExistsError(f"Unowned partial output exists: {partial}")
        try:
            if whole_scene(scene, self.timeline) and self.mode != "lossless":
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
                    failures = []
                    for copy, seek in attempts:
                        try:
                            command = self._command(scene, partial, parts, copy=copy, seek=seek)
                            run(command)
                            output = probe(partial, fingerprint=False)
                            video = self.verify_video(scene, output)
                            audio = self.verify_audio(output, parts, directory / "verify-audio")
                            result = {"method": "stream-copy-video" if copy else "lossless-reencode",
                                      "video": video, "audio": audio, "output_timestamp_origin": "scene-video-start",
                                      "attempt_failures": failures, "seek_optimization_used": seek,
                                      "audio_streams_without_overlap": [a.stream_index for a in self.audio if a not in [p.track for p in parts]],
                                      "command": command}
                            break
                        except MediaError as exc:
                            partial.unlink(missing_ok=True)
                            failures.append(str(exc))
                            LOG.warning("Export verification/attempt failed: %s", exc)
                    else:
                        raise MediaError("No verified export could be produced: " + "; ".join(failures))
            result["output_sha256"] = sha256_file(partial)
            result["output_size_bytes"] = partial.stat().st_size
            result["wall_seconds"] = time.monotonic() - start_time
            # Link is no-clobber and atomic on the same filesystem; unlike replace(),
            # it cannot overwrite an output created concurrently after our first check.
            os.link(partial, target)
            partial.unlink()
            return result
        finally:
            partial.unlink(missing_ok=True)
