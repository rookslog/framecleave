import io

from framecleave.presentation import OutputMode, TerminalProgressSink
from framecleave.progress import ProgressEvent


class FakeTTY(io.StringIO):
    def __init__(self, width=80):
        super().__init__()
        self.width = width

    def isatty(self):
        return True


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def event(name, *, sequence=0, phase="analysis", **values):
    return ProgressEvent(run_id="run-1", event=name, phase=phase, sequence=sequence, **values)


def test_default_tty_replaces_one_status_line():
    stream = FakeTTY(width=80)
    sink = TerminalProgressSink(stream, OutputMode.DEFAULT, is_tty=True, width=80, clock=FakeClock())
    sink.emit(event("analysis_progress", completed=100, total=1000, unit="frames", job_id="video.mkv"))
    sink.emit(event("scene_started", sequence=1, phase="encoding", scene_id="2", job_id="video.mkv"))
    value = stream.getvalue()
    assert value.count("\r") == 2
    assert "\n" not in value
    assert "video.mkv" in value
    assert "encoding" in value


def test_non_tty_uses_milestones_without_ansi_or_carriage_returns():
    stream = io.StringIO()
    sink = TerminalProgressSink(stream, OutputMode.DEFAULT, is_tty=False, width=80, clock=FakeClock())
    sink.emit(event("job_started", job_id="video.mkv"))
    sink.emit(event("analysis_progress", sequence=1, completed=100, total=1000, unit="frames"))
    sink.emit(event("job_finished", sequence=2, phase="complete", job_id="video.mkv", outcome="success"))
    value = stream.getvalue()
    assert "\r" not in value
    assert "\x1b" not in value
    assert "started" in value
    assert "complete" in value
    assert "100/1000" not in value


def test_quiet_prints_only_terminal_failures():
    stream = io.StringIO()
    sink = TerminalProgressSink(stream, OutputMode.QUIET, is_tty=False, width=80, clock=FakeClock())
    sink.emit(event("job_started", job_id="video.mkv"))
    sink.emit(event("job_failed", sequence=1, phase="failed", job_id="video.mkv", outcome="failed",
                    reason_code="media-error"))
    value = stream.getvalue()
    assert "started" not in value
    assert "failed" in value
    assert "media-error" in value


def test_verbose_prints_attempt_and_scene_milestones_as_lines():
    stream = io.StringIO()
    sink = TerminalProgressSink(stream, OutputMode.VERBOSE, is_tty=True, width=80, clock=FakeClock())
    sink.emit(event("attempt_rejected", phase="verification", scene_id="5", attempt_id="copy",
                    reason_code="muxer-rejected"))
    sink.emit(event("scene_certified", sequence=1, phase="complete", scene_id="5", recovered=True))
    value = stream.getvalue()
    assert value.count("\n") == 2
    assert "attempt rejected" in value
    assert "scene 5 certified" in value
    assert "recovered" in value


def test_default_tty_line_never_exceeds_width():
    stream = FakeTTY(width=36)
    sink = TerminalProgressSink(stream, OutputMode.DEFAULT, is_tty=True, width=36, clock=FakeClock())
    sink.emit(event("scene_started", phase="encoding-a-very-long-phase", job_id="a-very-long-video-name.mkv",
                    scene_id="123", completed=12, total=38))
    line = stream.getvalue().split("\r")[-1]
    assert len(line) <= 36
