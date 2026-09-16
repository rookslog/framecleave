import json
import pytest


def test_job_directory_refuses_unowned_data(tmp_path):
    from framecleave.storage import JobDirectory
    (tmp_path / 'precious.txt').write_text('keep')
    with pytest.raises(FileExistsError):
        with JobDirectory(tmp_path):
            pass
    assert (tmp_path / 'precious.txt').read_text() == 'keep'


def test_live_lock_is_not_stolen_by_resume(tmp_path):
    from framecleave.storage import JobDirectory, atomic_json
    root = tmp_path / 'out'
    with JobDirectory(root):
        atomic_json(root / 'state.json', {'status': 'running'})
        with pytest.raises(FileExistsError):
            with JobDirectory(root, resume=True):
                pass
    assert not (root / '.lock').exists()
    with JobDirectory(root, resume=True):
        assert (root / '.lock').exists()


def test_atomic_json_handles_unicode_and_refuses_nan(tmp_path):
    from framecleave.storage import atomic_json
    path = tmp_path / 'é.json'
    atomic_json(path, {'name': 'résumé'})
    assert json.loads(path.read_text()) == {'name': 'résumé'}
    with pytest.raises(ValueError):
        atomic_json(path, {'n': float('nan')})
    assert json.loads(path.read_text()) == {'name': 'résumé'}


def test_job_log_refuses_a_symlink(tmp_path):
    from framecleave.storage import JobLog
    outside = tmp_path / 'outside.txt'
    outside.write_text('private unrelated data')
    job = tmp_path / 'job'
    job.mkdir()
    (job / 'diagnostics.log').symlink_to(outside)
    with pytest.raises(FileExistsError, match='symlink'):
        with JobLog(job):
            pass
    assert outside.read_text() == 'private unrelated data'


def test_disk_full_finalization_preserves_existing_json(tmp_path, monkeypatch):
    import errno
    from framecleave.storage import atomic_json
    path = tmp_path / 'state.json'
    atomic_json(path, {'status': 'verified'})
    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'No space left on device')
    monkeypatch.setattr('framecleave.storage.os.replace', no_space)
    with pytest.raises(OSError) as error:
        atomic_json(path, {'status': 'new'})
    assert error.value.errno == errno.ENOSPC
    assert json.loads(path.read_text()) == {'status': 'verified'}
    assert list(tmp_path.iterdir()) == [path]


def test_new_job_directory_is_owner_only_even_with_permissive_umask(tmp_path):
    import os
    import stat
    from framecleave.storage import JobDirectory
    old = os.umask(0)
    try:
        with JobDirectory(tmp_path / 'sensitive-job') as root:
            assert stat.S_IMODE(root.stat().st_mode) == 0o700
    finally:
        os.umask(old)


def test_existing_empty_directory_permissions_are_not_changed(tmp_path):
    import stat
    from framecleave.storage import JobDirectory
    root = tmp_path / 'user-chosen'
    root.mkdir(mode=0o750)
    with JobDirectory(root):
        assert stat.S_IMODE(root.stat().st_mode) == 0o750


def test_batch_records_observed_bytes_and_low_space_event(tmp_path, monkeypatch):
    from collections import namedtuple
    from framecleave.batch import process_batch
    from framecleave.config import Config
    from framecleave.progress import ProgressReporter

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'fixture placeholder')

    def fake_process(source, output, config, *, progress, job_id, **options):
        reporter = ProgressReporter(progress, run_id='worker', job_id=job_id)
        reporter.emit('job_started', 'starting')
        output.mkdir()
        (output / 'artifact').write_bytes(b'x' * 32)
        reporter.emit('job_finished', 'complete', outcome='success')
        return {'source': str(source), 'output': str(output), 'status': 'complete'}

    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr('framecleave.batch.process_video', fake_process)
    monkeypatch.setattr('framecleave.progress.shutil.disk_usage', lambda path: usage(100, 99, 1))
    result = process_batch([source], tmp_path / 'out', Config(), jobs=1, dry_run=True)
    events = [json.loads(line) for line in (tmp_path / 'out/batch-events.jsonl').read_text().splitlines()]
    assert result['current_bytes'] > 0
    assert result['peak_bytes'] >= result['current_bytes']
    assert result['free_bytes'] == 1
    assert 'low_disk_space' in {event['event'] for event in events}
    terminal = next(event for event in events if event['event'] == 'job_finished')
    assert terminal['observed_bytes'] > 0
