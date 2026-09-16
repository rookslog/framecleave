"""Structured progress events and sinks for CLI and batch processing."""

from __future__ import annotations

from dataclasses import dataclass, fields
import json
import math
import os
from pathlib import Path
import time
from typing import Protocol
import uuid


TERMINAL_EVENTS = frozenset({"job_finished", "job_failed", "batch_finished", "batch_interrupted", "worker_lost"})


class ProgressSink(Protocol):
    def emit(self, event: "ProgressEvent") -> None: ...

    def close(self, result: dict | None = None) -> None: ...


@dataclass(frozen=True)
class ProgressEvent:
    run_id: str
    event: str
    phase: str
    sequence: int
    job_id: str | None = None
    scene_id: str | None = None
    attempt_id: str | None = None
    completed: int | None = None
    total: int | None = None
    unit: str | None = None
    elapsed_seconds: float | None = None
    outcome: str | None = None
    reason_code: str | None = None
    diagnostics: str | None = None
    recovered: bool | None = None

    def __post_init__(self) -> None:
        for name in ("run_id", "event", "phase"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a nonempty string")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a nonnegative integer")
        for name in ("job_id", "scene_id", "attempt_id", "unit", "outcome", "reason_code"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a nonempty string when provided")
        for name in ("completed", "total"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer when provided")
        if self.completed is not None and self.total is not None and self.completed > self.total:
            raise ValueError("completed cannot exceed total")
        if self.elapsed_seconds is not None and (
            not isinstance(self.elapsed_seconds, (int, float))
            or isinstance(self.elapsed_seconds, bool)
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("elapsed_seconds must be finite and nonnegative")
        if self.diagnostics is not None:
            path = Path(self.diagnostics)
            if not self.diagnostics or path.is_absolute() or ".." in path.parts:
                raise ValueError("diagnostics must be a contained relative path")
        if self.recovered is not None and type(self.recovered) is not bool:
            raise ValueError("recovered must be a boolean when provided")

    def to_dict(self) -> dict:
        result = {"schema_version": 1}
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                result[field.name] = value
        return result


class NullProgressSink:
    def emit(self, event: ProgressEvent) -> None:
        pass

    def close(self, result: dict | None = None) -> None:
        pass


class ProgressReporter:
    """Create ordered events for one job while leaving sink ownership to the caller."""

    def __init__(self, sink: ProgressSink | None = None, *, run_id: str | None = None,
                 job_id: str | None = None, clock=time.monotonic) -> None:
        self.sink = sink or NullProgressSink()
        self.run_id = run_id or uuid.uuid4().hex
        self.job_id = job_id
        self.clock = clock
        self.started = clock()
        self.sequence = 0

    def emit(self, event: str, phase: str, **values) -> ProgressEvent:
        values.setdefault("job_id", self.job_id)
        values.setdefault("elapsed_seconds", self.clock() - self.started)
        progress_event = ProgressEvent(
            run_id=self.run_id,
            event=event,
            phase=phase,
            sequence=self.sequence,
            **values,
        )
        self.sequence += 1
        self.sink.emit(progress_event)
        return progress_event


class CompositeProgressSink:
    def __init__(self, sinks) -> None:
        self.sinks = tuple(sinks)

    def emit(self, event: ProgressEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)

    def close(self, result: dict | None = None) -> None:
        for sink in reversed(self.sinks):
            sink.close(result)


class JsonlProgressSink:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if self.path.is_symlink():
            raise FileExistsError("Progress event log must not be a symlink")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        self.handle = os.fdopen(descriptor, "a", encoding="utf-8")

    def emit(self, event: ProgressEvent) -> None:
        self.handle.write(json.dumps(event.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        self.handle.flush()
        if event.event in TERMINAL_EVENTS:
            os.fsync(self.handle.fileno())

    def close(self, result: dict | None = None) -> None:
        if not self.handle.closed:
            self.handle.flush()
            self.handle.close()
