import json
import queue

import pytest

from framecleave.progress import (
    BatchStatus,
    CompositeProgressSink,
    JsonlProgressSink,
    NullProgressSink,
    ProgressEvent,
    QueueProgressSink,
)


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


def test_jsonl_sink_discards_only_an_incomplete_final_line(tmp_path):
    path = tmp_path / 'events.jsonl'
    first = json.dumps(_event('job_started').to_dict(), separators=(',', ':'))
    path.write_text(first + '\n{"schema_version":1,"event":"partial')
    sink = JsonlProgressSink(path)
    sink.emit(_event('job_finished'))
    sink.close()
    lines = path.read_text().splitlines()
    assert [json.loads(line)['event'] for line in lines] == ['job_started', 'job_finished']


def test_queue_sink_transports_validated_event_dictionaries():
    transport = queue.SimpleQueue()
    QueueProgressSink(transport).emit(_event('job_started'))
    payload = transport.get_nowait()
    assert isinstance(payload, dict)
    assert ProgressEvent.from_dict(payload).event == 'job_started'
    with pytest.raises(ValueError, match='unknown'):
        ProgressEvent.from_dict({**payload, 'raw_exception': 'private'})


def test_batch_status_tracks_active_terminal_and_recovered_counts():
    status = BatchStatus(total=2)
    status.apply(ProgressEvent(run_id='r', event='job_started', phase='starting', sequence=0,
                               job_id='one'))
    status.apply(ProgressEvent(run_id='r', event='scene_certified', phase='exporting', sequence=1,
                               job_id='one', recovered=True))
    status.apply(ProgressEvent(run_id='r', event='job_finished', phase='complete', sequence=2,
                               job_id='one', outcome='success'))
    value = status.to_dict()
    assert value['pending'] == 1
    assert value['active'] == 0
    assert value['succeeded'] == 1
    assert value['recovered_fallbacks'] == 1
    assert value['event_log'] == 'batch-events.jsonl'


def test_batch_synthesizes_worker_lost_when_result_has_no_terminal_event(tmp_path, monkeypatch):
    from framecleave.batch import process_batch
    from framecleave.config import Config

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'fixture placeholder')
    monkeypatch.setattr('framecleave.batch.process_video',
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('worker vanished')))
    result = process_batch([source], tmp_path / 'out', Config(), jobs=1, dry_run=True)
    events = [json.loads(line) for line in (tmp_path / 'out/batch-events.jsonl').read_text().splitlines()]
    assert result['failed'] == 1
    assert [event['event'] for event in events][-2:] == ['worker_lost', 'batch_finished']


def test_interrupted_batch_drains_queued_events_before_terminal_event(tmp_path, monkeypatch):
    from framecleave.batch import process_batch
    from framecleave.config import Config
    from framecleave.progress import ProgressEvent
    import framecleave.batch as batch_module

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'fixture placeholder')

    def interrupt(payload):
        batch_module._WORKER_PROGRESS.emit(
            ProgressEvent(run_id='worker', event='job_started', phase='starting', sequence=0,
                          job_id=payload[-1])
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(batch_module, '_process', interrupt)
    with pytest.raises(KeyboardInterrupt):
        process_batch([source], tmp_path / 'out', Config(), jobs=1, dry_run=True)
    events = [json.loads(line)['event']
              for line in (tmp_path / 'out/batch-events.jsonl').read_text().splitlines()]
    assert events[-2:] == ['job_started', 'batch_interrupted']


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
