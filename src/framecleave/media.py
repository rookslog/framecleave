"""Canonical local FFmpeg decoding. Frame numbers are decode ordinals, never FPS math."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import logging
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import tempfile
from typing import Iterator

import numpy as np

LOG = logging.getLogger(__name__)


class MediaError(RuntimeError):
    """An input, dependency, decoding, or media-verification failure."""


class PreservationError(MediaError):
    """Cannot export without an unapproved loss of media characteristics."""


def executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise MediaError(f"{name} is missing. On macOS: brew install ffmpeg")
    return found


def ffmpeg_base(*, level: str = "error") -> list[str]:
    return [executable("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", level, "-xerror"]


def run(command: list[str], *, timeout: float | None = None) -> bytes:
    """Run an argv, never a shell. Capture errors and kill children on cancellation."""
    LOG.debug("exec %s", json.dumps(command, ensure_ascii=False))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate(timeout=timeout)
    except BaseException:
        process.kill()
        process.communicate()
        raise
    if process.returncode:
        detail = err.decode("utf-8", "replace")[-6000:]
        raise MediaError(f"{Path(command[0]).name} failed ({process.returncode}): {detail.strip()}")
    if err:
        LOG.debug("ffmpeg stderr: %s", err.decode("utf-8", "replace")[-6000:])
    return out


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    document: dict
    sha256: str

    @property
    def video(self) -> dict:
        candidates = [
            s for s in self.document["streams"]
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ]
        if len(candidates) != 1:
            raise MediaError("Exactly one non-attached video stream is required")
        return candidates[0]

    @property
    def audio(self) -> list[dict]:
        return [s for s in self.document["streams"] if s.get("codec_type") == "audio"]

    @property
    def time_base(self) -> Fraction:
        return Fraction(self.video["time_base"])

    def source_dict(self, frame_count: int) -> dict:
        return {
            "path": str(self.path), "display_name": self.path.name, "sha256": self.sha256,
            "size_bytes": self.path.stat().st_size, "frame_count": frame_count,
            "streams": self.document["streams"], "format": self.document.get("format", {}),
            "chapters": self.document.get("chapters", []),
        }


def probe(path: Path, *, fingerprint: bool = True) -> MediaInfo:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise MediaError(f"Input is not a regular file: {path}")
    command = [
        executable("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe,crypto",
        "-show_streams", "-show_format", "-show_chapters", "-of", "json", str(path),
    ]
    try:
        document = json.loads(run(command, timeout=60))
        info = MediaInfo(path, document, sha256_file(path) if fingerprint else "")
        video = info.video
        if info.time_base <= 0 or not video.get("width") or not video.get("height"):
            raise MediaError("Invalid video geometry or time base")
        return info
    except (ValueError, KeyError) as exc:
        raise MediaError(f"Invalid media metadata: {exc}") from exc


@dataclass(frozen=True)
class DecodedFrame:
    number: int
    pts: int
    duration: int
    keyframe: bool
    image: np.ndarray


_FRAME = re.compile(
    r"\bn:\s*(\d+)\s+pts:\s*(-?\d+).*?\bduration:\s*(-?\d+).*?\biskey:(\d+)"
)
_TIMEBASE = re.compile(r"config in time_base:\s*(\d+/\d+)")


def selection_expression(selected: list[int]) -> str:
    """Balanced sums avoid FFmpeg's expression-parser recursion limit on long videos."""
    runs = []
    first = last = selected[0]
    for n in selected[1:]:
        if n == last + 1:
            last = n
        else:
            runs.append(f"between(n,{first},{last})")
            first = last = n
    runs.append(f"between(n,{first},{last})")
    while len(runs) > 1:
        runs = [f"({runs[i]}+{runs[i + 1]})" if i + 1 < len(runs) else runs[i]
                for i in range(0, len(runs), 2)]
    return runs[0]


def iter_video(
    info: MediaInfo, *, width: int, height: int, threads: int = 2, selected: list[int] | None = None,
) -> Iterator[DecodedFrame]:
    """Bounded raw RGB stream plus showinfo's *integer* presentation timestamps.

    Software decoding is intentional: it establishes a reproducible reference path.
    RGB here is analysis-only, never the export representation.
    """
    if selected is not None:
        if selected != sorted(set(selected)) or any(type(n) is not int or n < 0 for n in selected):
            raise ValueError("Selected ordinals must be sorted, unique, nonnegative integers")
        if not selected:
            return
    filters = f"scale={width}:{height}:flags=area,format=rgb24,showinfo"
    temporary = tempfile.TemporaryDirectory(prefix="framecleave-filter-")
    script = Path(temporary.name) / "filter.txt"
    if selected is not None:
        expression = selection_expression(selected)
        filters = f"select='{expression}'," + filters
    script.write_text(filters, encoding="utf-8")
    command = ffmpeg_base(level="info") + [
        "-err_detect", "explode", "-threads", str(threads),
        "-protocol_whitelist", "file,pipe,crypto", "-copyts", "-noautorotate", "-i", str(info.path),
        "-map", f"0:{info.video['index']}", "-an", "-sn", "-dn",
        "-filter_script:v", str(script),
        "-fps_mode", "passthrough", "-threads", "1", "-f", "rawvideo", "pipe:1",
    ]
    if selected is not None:
        command[-1:-1] = ["-frames:v", str(len(selected))]
    LOG.debug("exec %s", json.dumps(command))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    metadata: queue.Queue = queue.Queue()
    errors: deque[str] = deque(maxlen=30)
    bases: list[Fraction] = []
    done = threading.Event()

    def drain() -> None:
        try:
            assert process.stderr is not None
            for raw in process.stderr:
                text = raw.decode("utf-8", "replace")
                match = _FRAME.search(text)
                if match:
                    metadata.put(tuple(map(int, match.groups())))
                else:
                    base = _TIMEBASE.search(text)
                    if base:
                        bases.append(Fraction(base.group(1)))
                    if "showinfo" not in text:
                        errors.append(text.rstrip())
        finally:
            done.set()

    worker = threading.Thread(target=drain, name="framecleave-ffmpeg-stderr", daemon=True)
    worker.start()
    frame_bytes = width * height * 3
    count = 0
    try:
        assert process.stdout is not None
        while True:
            data = process.stdout.read(frame_bytes)
            if not data:
                break
            if len(data) != frame_bytes:
                raise MediaError("Truncated RGB frame returned by decoder")
            try:
                number, pts, duration, key = metadata.get(timeout=30)
            except queue.Empty as exc:
                raise MediaError("Decoder returned pixels without exact PTS metadata") from exc
            if number != count:
                raise MediaError(f"Decoder ordinal mismatch: expected {count}, got {number}")
            if bases and bases[0] != info.time_base:
                raise MediaError("Decoder time base differs from the source stream time base")
            source_number = number if selected is None else selected[number]
            yield DecodedFrame(source_number, pts, duration, bool(key), np.frombuffer(data, np.uint8).reshape(height, width, 3))
            count += 1
        code = process.wait()
        worker.join(timeout=5)
        if code:
            raise MediaError(f"Video decoding failed ({code}): {'; '.join(errors)}")
        if selected is not None and count != len(selected):
            raise MediaError("Some requested source frame ordinals could not be decoded")
        if not count:
            raise MediaError("No video frames could be decoded")
        if not bases or not metadata.empty():
            raise MediaError("Incomplete or inconsistent decoder frame metadata")
    finally:
        if process.poll() is None:
            process.kill()
        if process.stdout:
            process.stdout.close()
        process.wait()
        worker.join(timeout=5)
        if process.stderr:
            process.stderr.close()
        temporary.cleanup()


def video_hashes(info: MediaInfo, *, threads: int = 2) -> list[dict]:
    """Hash every native decoded frame without colour conversion or auto-rotation."""
    tb = info.time_base
    command = ffmpeg_base() + [
        "-err_detect", "explode", "-threads", str(threads), "-copyts", "-noautorotate",
        "-protocol_whitelist", "file,pipe,crypto", "-i", str(info.path),
        "-map", f"0:{info.video['index']}", "-an", "-sn", "-dn", "-fps_mode", "passthrough",
        "-enc_time_base", f"{tb.numerator}:{tb.denominator}",
        "-c:v", "rawvideo", "-pix_fmt", info.video["pix_fmt"], "-threads", "1",
        "-f", "framehash", "-hash", "sha256", "pipe:1",
    ]
    text = run(command).decode("ascii")
    rows = []
    actual_base = None
    for line in text.splitlines():
        if line.startswith("#tb 0:"):
            actual_base = Fraction(line.split(":", 1)[1].strip())
        elif line and not line.startswith("#"):
            fields = [s.strip() for s in line.split(",")]
            if len(fields) != 6:
                raise MediaError("Unsupported FFmpeg framehash output")
            rows.append({"pts": int(fields[2]), "duration": int(fields[3]), "size": int(fields[4]), "sha256": fields[5]})
    if actual_base != tb or not rows:
        raise MediaError("Framehash output changed time base or contains no frames")
    return rows
