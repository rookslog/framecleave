"""Canonical decoded PCM, exact sample slicing, and explicit timestamp-jitter bounds.

Audio is decoded once per source. Slice boundaries use integer sample ordinals and
ceilings against the *video's* time origin; each stream retains its original offset.
Unexplained audio gaps/drift are rejected rather than silently stretched or padded.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import logging
import math
from pathlib import Path
import re
import subprocess

from .media import MediaError, MediaInfo, PreservationError, ffmpeg_base

LOG = logging.getLogger(__name__)
FORMATS = {
    "u8": ("u8", "pcm_u8", 1), "s16": ("s16le", "pcm_s16le", 2),
    "s32": ("s32le", "pcm_s32le", 4), "flt": ("f32le", "pcm_f32le", 4),
    "dbl": ("f64le", "pcm_f64le", 8),
}
_AUDIO = re.compile(r"\bn:(\d+)\s+pts:(-?\d+).*?\brate:(\d+)\s+nb_samples:(\d+)")


@dataclass(frozen=True)
class AudioTrack:
    stream_index: int
    path: Path
    rate: int
    channels: int
    layout: str
    raw_format: str
    codec: str
    sample_bytes: int
    samples: int
    first_pts: int  # in 1/rate, as decoded by FFmpeg's audio filter graph
    max_jitter_samples: int
    metadata: dict

    @property
    def origin(self) -> Fraction:
        return Fraction(self.first_pts, self.rate)

    @property
    def stride(self) -> int:
        return self.sample_bytes * self.channels


@dataclass(frozen=True)
class AudioSlice:
    track: AudioTrack
    path: Path
    first_sample: int
    end_sample: int
    delay: Fraction
    sha256: str

    @property
    def samples(self) -> int:
        return self.end_sample - self.first_sample

    def evidence(self) -> dict:
        return {
            "source_stream_index": self.track.stream_index,
            "first_sample": self.first_sample, "end_sample": self.end_sample,
            "samples": self.samples, "sample_rate": self.track.rate,
            "channels": self.track.channels, "channel_layout": self.track.layout,
            "output_delay_rational": str(self.delay), "pcm_sha256": self.sha256,
            "decoded_pcm_codec": self.track.codec,
            "source_timestamp_jitter_samples": self.track.max_jitter_samples,
        }


def extract_audio(info: MediaInfo, directory: Path, *, threads: int = 2) -> list[AudioTrack]:
    directory.mkdir(parents=True, exist_ok=True)
    tracks = []
    for stream in info.audio:
        sample_format = stream.get("sample_fmt", "").removesuffix("p")
        if sample_format not in FORMATS:
            raise PreservationError(f"Unsupported decoded audio format: {sample_format}")
        raw_format, codec, sample_bytes = FORMATS[sample_format]
        rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        layout = stream.get("channel_layout")
        if not layout:
            layout = {1: "mono", 2: "stereo"}.get(channels)
        if not layout:
            raise PreservationError("Multichannel audio has no unambiguous channel layout")
        target = directory / f"audio-{stream['index']:02d}.{raw_format}"
        partial = target.with_suffix(target.suffix + ".partial")
        command = ffmpeg_base(level="info") + [
            "-y", "-err_detect", "explode", "-threads", str(threads), "-copyts",
            "-protocol_whitelist", "file,pipe,crypto", "-i", str(info.path),
            "-map", f"0:{stream['index']}", "-vn", "-sn", "-dn", "-af", "ashowinfo",
            "-c:a", codec, "-f", raw_format, str(partial),
        ]
        LOG.debug("audio cache command: %r", command)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        first = None
        samples = 0
        frame_count = 0
        jitter = 0
        errors: deque[str] = deque(maxlen=20)
        try:
            assert process.stderr is not None
            for line in process.stderr:
                text = line.decode("utf-8", "replace")
                match = _AUDIO.search(text)
                if match:
                    n, pts, decoded_rate, count = map(int, match.groups())
                    if n != frame_count or decoded_rate != rate:
                        raise PreservationError("Audio format changes or decoded frame ordinals are inconsistent")
                    if first is None:
                        first = pts
                    jitter = max(jitter, abs(pts - first - samples))
                    samples += count
                    frame_count += 1
                else:
                    errors.append(text.rstrip())
            code = process.wait()
            if code or first is None or not samples:
                raise MediaError(f"Audio decode failed: {'; '.join(errors)}")
            tolerance = math.ceil(Fraction(stream["time_base"]) * rate) + 2
            if jitter > tolerance:
                raise PreservationError(
                    f"Audio stream {stream['index']} has gaps/drift of {jitter} samples; "
                    f"only container quantization up to {tolerance} samples is supported"
                )
            if partial.stat().st_size != samples * channels * sample_bytes:
                raise MediaError("Decoded PCM byte count disagrees with decoded sample count")
            partial.replace(target)
            tracks.append(AudioTrack(stream["index"], target, rate, channels, layout,
                                     raw_format, codec, sample_bytes, samples, first, jitter, stream))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stderr:
                process.stderr.close()
            partial.unlink(missing_ok=True)
    return tracks


def slice_track(track: AudioTrack, start: Fraction, end: Fraction, directory: Path) -> AudioSlice | None:
    if end <= start:
        raise ValueError("Audio slice must have positive duration")
    first = max(0, min(track.samples, math.ceil((start - track.origin) * track.rate)))
    stop = max(0, min(track.samples, math.ceil((end - track.origin) * track.rate)))
    if first >= stop:
        return None
    delay = track.origin + Fraction(first, track.rate) - start
    if delay < 0:
        raise MediaError("Audio slice would begin before the video boundary")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"audio-{track.stream_index:02d}.{track.raw_format}"
    remaining = (stop - first) * track.stride
    digest = hashlib.sha256()
    with track.path.open("rb") as source, target.open("xb") as output:
        source.seek(first * track.stride)
        while remaining:
            block = source.read(min(4 * 1024 * 1024, remaining))
            if not block:
                raise MediaError("Canonical audio cache was truncated")
            output.write(block)
            digest.update(block)
            remaining -= len(block)
    return AudioSlice(track, target, first, stop, delay, digest.hexdigest())
