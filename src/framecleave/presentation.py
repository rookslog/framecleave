"""Human terminal presentation for structured progress events."""

from __future__ import annotations

from enum import Enum
import shutil
import time

from .progress import BatchStatus, ProgressEvent


class OutputMode(str, Enum):
    QUIET = "quiet"
    DEFAULT = "default"
    VERBOSE = "verbose"
    DEBUG = "debug"


_DEFAULT_MILESTONES = frozenset(
    {
        "batch_started",
        "batch_finished",
        "batch_interrupted",
        "job_started",
        "job_finished",
        "job_failed",
        "worker_lost",
    }
)
_FAILURES = frozenset({"batch_interrupted", "job_failed", "scene_failed", "worker_lost"})


class TerminalProgressSink:
    def __init__(self, stream, mode: OutputMode, *, is_tty: bool | None = None,
                 width: int | None = None, clock=time.monotonic) -> None:
        self.stream = stream
        self.mode = OutputMode(mode)
        self.is_tty = stream.isatty() if is_tty is None else is_tty
        self.width = width or shutil.get_terminal_size((100, 24)).columns
        self.clock = clock
        self.started = clock()
        self.last_event: ProgressEvent | None = None
        self.recovered_fallbacks = 0
        self.line_active = False
        self.batch: BatchStatus | None = None

    def emit(self, event: ProgressEvent) -> None:
        self.last_event = event
        if event.event == 'batch_started':
            self.batch = BatchStatus(event.total or 0)
        if self.batch:
            self.batch.apply(event)
        if event.recovered:
            self.recovered_fallbacks += 1
        if self.mode is OutputMode.QUIET:
            if event.event in _FAILURES or event.outcome == "failed":
                self._write_permanent(self._format_event(event))
            return
        if self.mode in {OutputMode.VERBOSE, OutputMode.DEBUG}:
            self._write_permanent(self._format_event(event))
            return
        if self.is_tty:
            if event.event in _FAILURES:
                self._write_permanent(self._format_event(event))
            else:
                self._write_status(event)
            return
        if event.event in _DEFAULT_MILESTONES:
            self._write_permanent(self._format_event(event))

    def close(self, result: dict | None = None) -> None:
        if self.is_tty and self.line_active:
            self.stream.write("\n")
            self.stream.flush()
            self.line_active = False

    def _format_status(self, event: ProgressEvent) -> str:
        parts = []
        if self.batch:
            done = self.batch.succeeded + self.batch.failed + self.batch.interrupted
            parts += [f'[{done}/{self.batch.total}]', f'active {self.batch.active}', f'pending {self.batch.pending}']
        elif event.completed is not None and event.total is not None:
            parts.append(f"[{event.completed}/{event.total}]")
        parts.append(event.phase)
        elapsed = event.elapsed_seconds if event.elapsed_seconds is not None else self.clock() - self.started
        minutes, seconds = divmod(max(0, int(elapsed)), 60)
        parts.append(f"{minutes:02d}:{seconds:02d}")
        optional = ([f'fallbacks {self.recovered_fallbacks}'] if self.recovered_fallbacks else [])
        optional += ([f'scene {event.scene_id}'] if event.scene_id else [])
        optional += ([event.job_id] if event.job_id else [])
        for item in optional:
            if len(' · '.join([*parts, item])) <= self.width:
                parts.append(item)
        return " · ".join(parts)[: self.width]

    def _format_event(self, event: ProgressEvent) -> str:
        if event.event == "scene_certified":
            message = f"scene {event.scene_id or '?'} certified"
            if event.recovered:
                message += " (recovered fallback)"
            return message
        message = event.event.replace("_", " ")
        details = []
        if event.job_id:
            details.append(event.job_id)
        if event.scene_id:
            details.append(f"scene {event.scene_id}")
        if event.attempt_id:
            details.append(event.attempt_id)
        if event.reason_code:
            details.append(event.reason_code)
        if event.phase not in message:
            details.append(event.phase)
        if details:
            message += ": " + " · ".join(details)
        return message

    def _write_status(self, event: ProgressEvent) -> None:
        line = self._format_status(event)
        self.stream.write("\r" + line.ljust(self.width))
        self.stream.flush()
        self.line_active = True

    def _write_permanent(self, line: str) -> None:
        if self.is_tty and self.line_active:
            self.stream.write("\r" + " " * self.width + "\r")
            self.line_active = False
        self.stream.write(line + "\n")
        self.stream.flush()
