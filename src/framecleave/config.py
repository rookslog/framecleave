"""Small, strict TOML configuration; unknown keys never silently fall through."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Config:
    threads: int = 2
    analysis_width: int = 128
    analysis_height: int = 96
    detector: str = "temporal"
    context_updates: int = 12
    min_change: float = 4.0
    cut_ratio: float = 3.0
    histogram_threshold: float = 0.65

    def __post_init__(self) -> None:
        for name, lo, hi in (
            ("threads", 1, 64), ("analysis_width", 64, 1024),
            ("analysis_height", 48, 1024), ("context_updates", 4, 60),
        ):
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name} must be an integer in [{lo}, {hi}]")
        if self.detector not in {"temporal", "pixel", "histogram", "adaptive"}:
            raise ValueError("Unknown detector; use temporal, pixel, histogram, adaptive")
        for name, lo, hi in (
            ("min_change", 0.01, 255), ("cut_ratio", 1, 100),
            ("histogram_threshold", 0, 1),
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not lo <= value <= hi:
                raise ValueError(f"{name} must be in [{lo}, {hi}]")

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def load_config(path: Path | None = None, **overrides) -> Config:
    values = {}
    if path is not None:
        with Path(path).open("rb") as handle:
            document = tomllib.load(handle)
        if set(document) - {"framecleave"}:
            raise ValueError("Configuration must contain only a [framecleave] table")
        values = document.get("framecleave", {})
        if not isinstance(values, dict):
            raise ValueError("[framecleave] must be a TOML table")
    known = {field.name for field in fields(Config)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    values.update({key: value for key, value in overrides.items() if value is not None})
    return Config(**values)
