import json
import os
from pathlib import Path
import subprocess
import signal
import sys


def hard_exit_worker(payload):
    from framecleave.batch import _process
    if payload[0].name == 'crash.mp4':
        os._exit(7)
    return _process(payload)


def noisy_worker(payload):
    from framecleave.batch import _WORKER_PROGRESS
    from framecleave.progress import ProgressReporter
    import time
    reporter = ProgressReporter(_WORKER_PROGRESS, job_id=payload[-1])
    reporter.emit('job_started', 'analyzing')
    for number in range(10000):
        reporter.emit('analysis_progress', 'analyzing', completed=number)
        time.sleep(0.005)
    return {'ok': True, 'source': str(payload[0]), 'job_id': payload[-1]}


def test_hard_worker_exit_returns_a_failed_summary_instead_of_waiting_forever(source_video, tmp_path):
    import shutil
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    shutil.copy(source_video, inputs / 'crash.mp4')
    shutil.copy(source_video, inputs / 'other.mp4')
    bootstrap = (
        f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); '
        'import framecleave.batch as batch; from test_batch_liveness import hard_exit_worker; '
        'from framecleave.config import Config; batch._process=hard_exit_worker; '
        f'result=batch.process_batch([__import__("pathlib").Path({str(inputs)!r})], '
        f'__import__("pathlib").Path({str(tmp_path / "out")!r}), Config(), jobs=2, mode="review-copy"); '
        'print(__import__("json").dumps(result))'
    )
    process = subprocess.Popen([sys.executable, '-c', bootstrap], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        raise AssertionError('Controlled worker exit did not produce a terminal batch result') from None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
    assert process.returncode == 0, stderr
    value = __import__('json').loads(stdout)
    assert value['failed'] >= 1
    assert value['pending'] == 0
    assert value['active'] == 0


def test_zero_reserve_review_batch_records_per_file_failures(tmp_path):
    from framecleave.batch import process_batch
    from framecleave.config import Config

    empty = tmp_path / 'empty.mp4'
    empty.write_bytes(b'')
    inputs = [tmp_path / 'missing-a.mp4', tmp_path / 'missing-b.mp4', empty]
    result = process_batch(inputs, tmp_path / 'out', Config(threads=1), jobs=1, mode='review-copy')
    assert result['failed'] == 3
    assert result['pending'] == 0
    assert result['active'] == 0
    assert (tmp_path / 'out' / 'batch-summary.json').is_file()
    assert json.loads((tmp_path / 'out' / 'state.json').read_text())['status'] == 'partial-failure'


def test_input_disappearing_during_reserve_sizing_isolated_to_file(tmp_path, monkeypatch):
    from framecleave.batch import process_batch
    from framecleave.config import Config

    source = (tmp_path / 'vanishing.mp4').resolve()
    source.write_bytes(b'not media')
    real_stat = Path.stat
    calls = {'source': 0}

    def disappearing_stat(self, *args, **kwargs):
        if self == source:
            calls['source'] += 1
            if calls['source'] == 3:
                source.unlink()
                raise FileNotFoundError(source)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', disappearing_stat)
    result = process_batch([source], tmp_path / 'out', Config(threads=1), jobs=1, mode='review-copy')
    assert result['failed'] == 1
    assert result['pending'] == 0
    assert json.loads((tmp_path / 'out' / 'state.json').read_text())['status'] == 'partial-failure'


def test_spawned_progress_storage_failure_cancels_workers_and_records_failure(source_video, tmp_path):
    bootstrap = f'''
import sys, threading, json, multiprocessing
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).parent)!r})
import framecleave.batch as batch
from framecleave.progress import ProgressCoordinator
from framecleave.config import Config
from test_batch_liveness import noisy_worker
batch._process = noisy_worker
original = ProgressCoordinator._persist
counter = 0
def refusing(self):
    global counter
    counter += 1
    if counter > 5 and threading.current_thread() is not threading.main_thread():
        raise OSError('injected storage exhaustion')
    return original(self)
ProgressCoordinator._persist = refusing
output = Path({str(tmp_path / 'out')!r})
try:
    batch.process_batch([Path({str(source_video)!r})], output, Config(), jobs=2, mode='review-copy')
except RuntimeError as error:
    print(json.dumps({{'state': json.loads((output/'state.json').read_text()), 'workers': len(multiprocessing.active_children()), 'cause': str(error.__cause__)}}))
else:
    raise AssertionError('Storage failure was swallowed')
'''
    process = subprocess.Popen([sys.executable, '-c', bootstrap], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        raise AssertionError('Progress storage failure did not stop owned workers') from None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
    assert process.returncode == 0, stderr
    value = __import__('json').loads(stdout)
    assert value['state']['status'] == 'failed'
    assert value['workers'] == 0
    assert 'injected storage exhaustion' in value['cause']
