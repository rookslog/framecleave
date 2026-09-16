import json

import pytest

from framecleave.progress import CompositeProgressSink, JsonlProgressSink, NullProgressSink, ProgressEvent


def test_progress_event_serializes_only_declared_fields():
    event = ProgressEvent(
        run_id="run-1",
        event="scene_started",
        phase="encoding",
        sequence=3,
        job_id="job-1",
        scene_id="5",
        completed=4,
        total=18,
    )
    assert event.to_dict() == {
        "schema_version": 1,
        "run_id": "run-1",
        "event": "scene_started",
        "phase": "encoding",
        "sequence": 3,
        "job_id": "job-1",
        "scene_id": "5",
        "completed": 4,
        "total": 18,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"sequence": -1},
        {"completed": -1},
        {"completed": 5, "total": 4},
        {"elapsed_seconds": float("nan")},
        {"diagnostics": "/absolute/diagnostics.log"},
        {"diagnostics": "../outside.log"},
    ],
)
def test_progress_event_rejects_invalid_values(changes):
    values = {"run_id": "run-1", "event": "tick", "phase": "analysis", "sequence": 0}
    values.update(changes)
    with pytest.raises(ValueError):
        ProgressEvent(**values)


def _event(name="scene_started"):
    return ProgressEvent(run_id="run-1", event=name, phase="encoding", sequence=1)


def test_jsonl_sink_writes_one_compact_event_per_line(tmp_path):
    sink = JsonlProgressSink(tmp_path / "events.jsonl")
    sink.emit(_event("job_finished"))
    sink.close()
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "job_finished"


def test_jsonl_sink_refuses_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("")
    (tmp_path / "events.jsonl").symlink_to(outside)
    with pytest.raises(FileExistsError):
        JsonlProgressSink(tmp_path / "events.jsonl")


def test_jsonl_sink_fsyncs_terminal_events(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("framecleave.progress.os.fsync", calls.append)
    sink = JsonlProgressSink(tmp_path / "events.jsonl")
    sink.emit(_event())
    assert calls == []
    sink.emit(_event("job_finished"))
    assert len(calls) == 1
    sink.close()


def test_composite_and_null_sinks_share_the_interface():
    class Collector:
        def __init__(self):
            self.events = []
            self.result = None

        def emit(self, event):
            self.events.append(event)

        def close(self, result=None):
            self.result = result

    collector = Collector()
    sink = CompositeProgressSink([NullProgressSink(), collector])
    sink.emit(_event())
    sink.close({"ok": True})
    assert collector.events == [_event()]
    assert collector.result == {"ok": True}
