import json
from pathlib import Path
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


def test_jsonl_sink_repairs_large_tail_with_bounded_reads(tmp_path, monkeypatch):
    path = tmp_path / 'events.jsonl'
    complete = b'{"event":"analysis_progress"}\n' * 100_000
    path.write_bytes(complete + b'{"event":')
    real_open = Path.open
    read_sizes = []

    class TrackingFile:
        def __init__(self, handle):
            self.handle = handle

        def read(self, size=-1):
            read_sizes.append(size)
            return self.handle.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def __getattr__(self, name):
            return getattr(self.handle, name)

    def tracking_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return TrackingFile(handle) if self == path else handle

    monkeypatch.setattr(Path, 'open', tracking_open)
    sink = JsonlProgressSink(path)
    sink.close()
    repair_reads = list(read_sizes)
    assert path.read_bytes() == complete
    assert repair_reads and all(0 < size <= 64 * 1024 for size in repair_reads)


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


def test_worker_lost_before_a_start_event_retires_pending_job():
    status = BatchStatus(1)
    status.apply(ProgressEvent(run_id='r', event='worker_lost', phase='failed', sequence=0,
                              job_id='lost', outcome='failed'))
    assert status.pending == 0
    assert status.active == 0
    assert status.failed == 1


def test_worker_exit_after_finished_event_is_an_unconfirmed_failure():
    status = BatchStatus(1)
    for number, name in enumerate(['job_started', 'job_finished', 'worker_lost']):
        status.apply(ProgressEvent(run_id='r', event=name, phase='failed', sequence=number,
                                  job_id='lost', outcome='failed' if name == 'worker_lost' else None))
    assert status.succeeded == 0
    assert status.failed == 1
    assert status.pending == 0


def test_worker_lost_reclassifies_an_interrupted_terminal_as_failed():
    status = BatchStatus(1)
    status.apply(ProgressEvent(run_id='r', event='job_started', phase='starting', sequence=0,
                               job_id='lost'))
    status.apply(ProgressEvent(run_id='r', event='job_failed', phase='interrupted', sequence=1,
                               job_id='lost', outcome='failed', reason_code='interrupted'))
    assert status.interrupted == 1
    assert status.failed == 0
    status.apply(ProgressEvent(run_id='r', event='worker_lost', phase='failed', sequence=2,
                               job_id='lost', outcome='failed', reason_code='worker-process-exited'))
    assert status.interrupted == 0
    assert status.failed == 1


def test_progress_write_error_still_drains_transport_and_closes_sinks(tmp_path):
    from framecleave.progress import ProgressCoordinator

    class RefusingSink:
        closed = False

        def emit(self, event):
            raise OSError('injected disk write error')

        def close(self, result=None):
            self.closed = True

    transport = queue.Queue()
    sink = RefusingSink()
    coordinator = ProgressCoordinator(transport, [sink], total=1, root=tmp_path, status_path=tmp_path / 'status')
    coordinator.start()
    transport.put(_event('job_started').to_dict())
    transport.put(_event('job_finished').to_dict())
    with pytest.raises(RuntimeError):
        coordinator.close()
    assert transport.empty()
    assert sink.closed


def test_scene_events_do_not_rescan_the_growing_batch_tree(tmp_path, monkeypatch):
    import os
    from framecleave.progress import ProgressCoordinator

    root = tmp_path / 'tree'
    root.mkdir()
    scans = []
    original_walk = os.walk

    def counted_walk(*args, **kwargs):
        count = 0
        for base, directories, files in original_walk(*args, **kwargs):
            count += len(files)
            yield base, directories, files
        scans.append(count)

    monkeypatch.setattr('framecleave.progress.os.walk', counted_walk)
    coordinator = ProgressCoordinator(queue.SimpleQueue(), [NullProgressSink()], total=1,
                                      root=root, status_path=tmp_path / 'status.json')
    for number in range(1, 11):
        (root / f'generated-{number}.json').touch()
        coordinator.emit(ProgressEvent(run_id='run', event='scene_certified', phase='exporting',
                                       sequence=number, job_id='generated', scene_id=str(number)))
    assert scans == []

    coordinator.emit(ProgressEvent(run_id='run', event='job_finished', phase='complete',
                                   sequence=11, job_id='generated', outcome='success'))
    assert scans == [10]


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
