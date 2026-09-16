"""Exact source presentation timeline and versioned, half-open scene indexes."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path

SCHEMA_VERSION = 1


def rational(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def display_time(value: Fraction) -> str:
    milliseconds = round(abs(value) * 1000)
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{'-' if value < 0 else ''}{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


@dataclass
class Timeline:
    pts: list[int]
    durations: list[int]
    keyframes: list[int]
    time_base: Fraction

    def __post_init__(self) -> None:
        if not self.pts or len(self.pts) != len(self.durations):
            raise ValueError("Timeline requires one positive duration for every frame")
        if not isinstance(self.time_base, Fraction) or self.time_base <= 0:
            raise ValueError("A positive rational time base is required")
        if any(type(p) is not int for p in self.pts):
            raise ValueError("PTS must be integers")
        if any(b <= a for a, b in zip(self.pts, self.pts[1:])):
            raise ValueError("Decoded PTS must be strictly increasing; repair input explicitly")
        if any(type(d) is not int or d <= 0 for d in self.durations):
            raise ValueError("Missing/non-positive frame duration; cannot establish exact endpoint")
        if self.durations[:-1] != [b - a for a, b in zip(self.pts, self.pts[1:])]:
            raise ValueError("Frame durations must equal adjacent display-time intervals")
        if self.keyframes != sorted(set(self.keyframes)) or any(
            type(i) is not int or not 0 <= i < len(self.pts) for i in self.keyframes
        ):
            raise ValueError("Invalid keyframe ordinal list")

    @property
    def frame_count(self) -> int:
        return len(self.pts)

    @property
    def end_pts(self) -> int:
        return self.pts[-1] + self.durations[-1]

    @property
    def duration(self) -> Fraction:
        return (self.end_pts - self.pts[0]) * self.time_base

    def endpoint(self, frame: int) -> int:
        if type(frame) is not int or not 0 <= frame <= self.frame_count:
            raise ValueError("Frame endpoint outside source")
        return self.end_pts if frame == self.frame_count else self.pts[frame]

    def scenes(self, cuts: list[int]) -> list[dict]:
        if cuts != sorted(set(cuts)) or any(
            type(cut) is not int or not 0 < cut < self.frame_count for cut in cuts
        ):
            raise ValueError("Cuts must be sorted, unique interior decoded frame ordinals")
        points = [0, *cuts, self.frame_count]
        scenes = []
        for number, (start, end) in enumerate(zip(points, points[1:]), 1):
            a, b = self.endpoint(start), self.endpoint(end)
            scenes.append({
                "number": number, "start_frame": start, "end_frame": end,
                "last_frame": end - 1, "frame_count": end - start,
                "start_pts": a, "end_pts": b,
                "start_time_rational": rational(a * self.time_base),
                "end_time_rational": rational(b * self.time_base),
                "duration_rational": rational((b - a) * self.time_base),
                "start_relative": display_time((a - self.pts[0]) * self.time_base),
                "end_relative": display_time((b - self.pts[0]) * self.time_base),
                "output_file": None, "thumbnails": {},
            })
        return scenes

    def to_dict(self) -> dict:
        return {
            "time_base": rational(self.time_base), "pts": self.pts,
            "durations": self.durations, "keyframes": self.keyframes,
        }

    @classmethod
    def from_dict(cls, value: dict) -> Timeline:
        return cls(
            list(value["pts"]), list(value["durations"]),
            list(value["keyframes"]), Fraction(value["time_base"]),
        )


def validate_index(value: dict) -> Timeline:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported scene index schema_version")
    if value.get("interval_semantics") != "decoded-frames-half-open":
        raise ValueError("Unsupported interval semantics")
    timeline = Timeline.from_dict(value["timeline"])
    scenes = value["scenes"]
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Index must contain at least one scene")
    cuts = [scene["start_frame"] for scene in scenes[1:]]
    expected = timeline.scenes(cuts)
    for actual, correct in zip(scenes, expected, strict=True):
        for key in (
            "number", "start_frame", "end_frame", "last_frame", "frame_count",
            "start_pts", "end_pts", "duration_rational",
            "start_time_rational", "end_time_rational", "start_relative", "end_relative",
        ):
            if actual.get(key) != correct[key]:
                raise ValueError(f"Invalid scene partition: {key}")
        output = actual.get("output_file")
        if output and (Path(output).is_absolute() or ".." in Path(output).parts):
            raise ValueError("Output paths must be relative and contained in the job directory")
    boundaries = value.get("boundaries", [])
    numbers = [b["frame"] for b in boundaries]
    if numbers != sorted(set(numbers)) or any(type(n) is not int or not 0 < n < timeline.frame_count for n in numbers):
        raise ValueError("Invalid boundary ordinal list")
    if any(b.get("decision") not in {"cut", "review"} or b.get("pts") != timeline.pts[b["frame"]] for b in boundaries):
        raise ValueError("Invalid boundary decision or PTS")
    if [b["frame"] for b in boundaries if b["decision"] == "cut"] != cuts:
        raise ValueError("Accepted boundaries disagree with the scene partition")
    source = value.get("source", {})
    digest = source.get("sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("A source SHA-256 fingerprint is required")
    if source.get("frame_count") != timeline.frame_count:
        raise ValueError("Source frame count disagrees with timeline")
    return timeline


def read_index(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    validate_index(value)
    return value
