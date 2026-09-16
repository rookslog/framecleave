"""Structured progress events and sinks for CLI and batch processing."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
import json
import math
import os
from pathlib import Path
import shutil
import threading
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
    observed_bytes: int | None = None
    peak_bytes: int | None = None
    free_bytes: int | None = None

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
        for name in ("completed", "total", "observed_bytes", "peak_bytes", "free_bytes"):
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
        for descriptor in fields(self):
            value = getattr(self, descriptor.name)
            if value is not None:
                result[descriptor.name] = value
        return result

    @classmethod
    def from_dict(cls, value: dict) -> "ProgressEvent":
        if not isinstance(value, dict):
            raise ValueError("progress event payload must be an object")
        data = dict(value)
        if data.pop("schema_version", None) != 1:
            raise ValueError("unsupported progress event schema")
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown progress event fields: {', '.join(unknown)}")
        try:
            return cls(**data)
        except TypeError as exc:
            raise ValueError(f"invalid progress event: {exc}") from exc


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


class QueueProgressSink:
    """Serialize events into primitive dictionaries for a multiprocessing queue."""

    def __init__(self, transport) -> None:
        self.transport = transport

    def emit(self, event: ProgressEvent) -> None:
        self.transport.put(event.to_dict())

    def close(self, result: dict | None = None) -> None:
        pass


@dataclass
class BatchStatus:
    total: int
    pending: int = field(init=False)
    active: int = 0
    succeeded: int = 0
    failed: int = 0
    interrupted: int = 0
    recovered_fallbacks: int = 0
    active_phases: dict[str, str] = field(default_factory=dict)
    event_log: str = "batch-events.jsonl"
    current_bytes: int = 0
    peak_bytes: int = 0
    free_bytes: int | None = None
    _terminal_jobs: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if type(self.total) is not int or self.total < 0:
            raise ValueError("batch total must be a nonnegative integer")
        self.pending = self.total

    def apply(self, event: ProgressEvent) -> None:
        job_id = event.job_id
        if event.event == "scene_certified" and event.recovered:
            self.recovered_fallbacks += 1
        if not job_id:
            return
        if event.event == "job_started" and job_id not in self.active_phases and job_id not in self._terminal_jobs:
            self.pending = max(0, self.pending - 1)
            self.active += 1
        if job_id not in self._terminal_jobs:
            self.active_phases[job_id] = event.phase
        if event.event in {"job_finished", "job_failed", "worker_lost"} and job_id not in self._terminal_jobs:
            self._terminal_jobs.add(job_id)
            if job_id in self.active_phases:
                self.active = max(0, self.active - 1)
                self.active_phases.pop(job_id, None)
            else:
                self.pending = max(0, self.pending - 1)
            if event.event == "job_finished":
                self.succeeded += 1
            elif event.reason_code == "interrupted":
                self.interrupted += 1
            else:
                self.failed += 1
        if event.observed_bytes is not None:
            self.current_bytes = event.observed_bytes
        if event.peak_bytes is not None:
            self.peak_bytes = max(self.peak_bytes, event.peak_bytes)
        if event.free_bytes is not None:
            self.free_bytes = event.free_bytes

    def to_dict(self) -> dict:
        result = {
            "total": self.total,
            "pending": self.pending,
            "active": self.active,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "interrupted": self.interrupted,
            "recovered_fallbacks": self.recovered_fallbacks,
            "active_phases": dict(sorted(self.active_phases.items())),
            "event_log": self.event_log,
            "current_bytes": self.current_bytes,
            "peak_bytes": self.peak_bytes,
        }
        if self.free_bytes is not None:
            result["free_bytes"] = self.free_bytes
        return result


class CompositeProgressSink:
    def __init__(self, sinks) -> None:
        self.sinks = tuple(sinks)

    def emit(self, event: ProgressEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)

    def close(self, result: dict | None = None) -> None:
        for sink in reversed(self.sinks):
            sink.close(result)


class ProgressCoordinator:
    """Drain worker events and keep all durable/terminal writes in the parent."""

    _STOP = {"framecleave_control": "stop"}

    def __init__(self, transport, sinks, *, total: int, root: Path, status_path: Path) -> None:
        self.transport = transport
        self.sink = CompositeProgressSink(sinks)
        self.status = BatchStatus(total)
        self.root = Path(root)
        self.status_path = Path(status_path)
        self.results: list[dict] = []
        self.lock = threading.Lock()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._drain, name="framecleave-progress", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def emit(self, event: ProgressEvent) -> None:
        self._accept(event)

    def record_result(self, result: dict) -> None:
        with self.lock:
            self.results.append(result)
            self._observe_storage()
            self._persist()

    def summary(self) -> dict:
        with self.lock:
            return self._summary()

    def close(self, result: dict | None = None) -> None:
        self.drain()
        self.sink.close(result)

    def drain(self) -> None:
        if self.thread.is_alive():
            self.transport.put(dict(self._STOP))
            self.thread.join()
        if self.error is not None:
            raise RuntimeError("invalid worker progress event") from self.error

    def _drain(self) -> None:
        try:
            while True:
                payload = self.transport.get()
                if payload == self._STOP:
                    return
                self._accept(ProgressEvent.from_dict(payload))
        except BaseException as exc:
            self.error = exc

    def _accept(self, event: ProgressEvent) -> None:
        with self.lock:
            if event.event in TERMINAL_EVENTS or event.event == "scene_certified":
                self._observe_storage()
            if event.event in TERMINAL_EVENTS:
                event = replace(
                    event,
                    observed_bytes=self.status.current_bytes,
                    peak_bytes=self.status.peak_bytes,
                    free_bytes=self.status.free_bytes,
                )
            self.status.apply(event)
            self.sink.emit(event)
            self._persist()

    def _observe_storage(self) -> None:
        current = 0
        for base, directories, files in os.walk(self.root, followlinks=False):
            directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
            for name in files:
                path = Path(base) / name
                if not path.is_symlink():
                    try:
                        current += path.stat().st_size
                    except FileNotFoundError:
                        pass
        self.status.current_bytes = current
        self.status.peak_bytes = max(self.status.peak_bytes, current)
        self.status.free_bytes = shutil.disk_usage(self.root).free

    def _summary(self) -> dict:
        value = self.status.to_dict()
        value.update(
            processed=len(self.results),
            files=sorted(self.results, key=lambda item: item["source"]),
        )
        return value

    def _persist(self) -> None:
        from .storage import atomic_json

        atomic_json(self.status_path, self._summary())


class JsonlProgressSink:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if self.path.is_symlink():
            raise FileExistsError("Progress event log must not be a symlink")
        self._repair_final_line()
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        self.handle = os.fdopen(descriptor, "a", encoding="utf-8")

    def _repair_final_line(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("r+b") as handle:
            payload = handle.read()
            if payload.endswith(b"\n"):
                return
            boundary = payload.rfind(b"\n") + 1
            try:
                json.loads(payload[boundary:])
            except (json.JSONDecodeError, UnicodeDecodeError):
                handle.truncate(boundary)
            else:
                handle.seek(0, os.SEEK_END)
                handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def emit(self, event: ProgressEvent) -> None:
        self.handle.write(json.dumps(event.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        self.handle.flush()
        if event.event in TERMINAL_EVENTS:
            os.fsync(self.handle.fileno())

    def close(self, result: dict | None = None) -> None:
        if not self.handle.closed:
            self.handle.flush()
            self.handle.close()
