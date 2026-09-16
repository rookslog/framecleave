"""Bounded, process-isolated batch work. One malformed source does not abort peers."""
from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import signal

from .config import Config
from .progress import (
    JsonlProgressSink,
    NullProgressSink,
    ProgressCoordinator,
    ProgressReporter,
    ProgressSink,
    QueueProgressSink,
)
from .storage import JobDirectory, atomic_json
from .workflow import process_video

LOG = logging.getLogger(__name__)
EXTENSIONS = {'.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.mts', '.m2ts', '.ts', '.mpeg', '.mpg'}
_WORKER_PROGRESS = None


def discover(inputs: list[Path], output: Path, *, recursive: bool = False) -> list[Path]:
    result = set()
    output = output.resolve()
    for item in inputs:
        item = Path(item).expanduser().resolve()
        if item.is_dir():
            candidates = item.rglob('*') if recursive else item.iterdir()
            result.update(p.resolve() for p in candidates if p.is_file() and p.suffix.lower() in EXTENSIONS
                          and not p.resolve().is_relative_to(output))
        else:
            result.add(item)
    if not result:
        raise ValueError('No input videos found')
    if any(p.is_relative_to(output) for p in result):
        raise ValueError('Batch inputs must not be inside their output directory')
    return sorted(result, key=str)


def _name(path: Path) -> str:
    stem = re.sub(r'[^\w.-]+', '-', path.stem, flags=re.UNICODE).strip('.-')[:70] or 'video'
    return stem + '-' + hashlib.sha256(str(path).encode()).hexdigest()[:12]


def _stop_worker(signum, frame):
    # Unwind Python context managers, including active FFmpeg processes and job locks.
    raise KeyboardInterrupt


def _initialize_worker(progress_queue):
    global _WORKER_PROGRESS
    _WORKER_PROGRESS = QueueProgressSink(progress_queue)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _stop_worker)


def _process(payload: tuple) -> dict:
    source, output, config, options, job_id = payload
    try:
        result = process_video(source, output, config, **options, progress=_WORKER_PROGRESS, job_id=job_id)
        return {'ok': True, 'job_id': job_id, **result}
    except Exception as exc:
        return {'ok': False, 'job_id': job_id, 'source': str(source), 'output': str(output),
                'error_type': type(exc).__name__, 'error': str(exc)}


def process_batch(inputs: list[Path], output: Path, config: Config, *, jobs: int = 1,
                  recursive: bool = False, dry_run: bool = False, thumbnails: bool = False,
                  resume: bool = False, mode: str = 'auto', progress: ProgressSink | None = None) -> dict:
    if type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError('jobs must be an integer from 1 to 8')
    paths = discover(inputs, output, recursive=recursive)
    if jobs * config.threads > (os.cpu_count() or 1):
        LOG.warning('jobs × threads exceeds available logical CPUs; lower --jobs or --threads to reduce pressure')
    options = dict(dry_run=dry_run, thumbnails=thumbnails, resume=resume, mode=mode)
    with JobDirectory(output, resume=resume) as root:
        previous_path = root / 'state.json'
        # Per-file resume validates source/config/mode. A resumed batch may add new sources.
        if previous_path.exists() and json.loads(previous_path.read_text()).get('kind') != 'batch':
            raise ValueError('Output belongs to a single-source job, not a batch')
        atomic_json(previous_path, {'kind': 'batch', 'status': 'running'})
        context = multiprocessing.get_context('spawn')
        progress_queue = context.Queue()
        coordinator = ProgressCoordinator(
            progress_queue,
            [progress or NullProgressSink(), JsonlProgressSink(root / 'batch-events.jsonl')],
            total=len(paths),
            root=root,
            status_path=root / 'batch-summary.json',
        )
        coordinator.start()
        reporter = ProgressReporter(coordinator)
        reporter.emit('batch_started', 'starting', total=len(paths), completed=0, unit='jobs')
        payloads = [(path, root / _name(path), config, options, _name(path)) for path in paths]
        pool = None
        try:
            if jobs == 1:
                global _WORKER_PROGRESS
                _WORKER_PROGRESS = QueueProgressSink(progress_queue)
                iterator = map(_process, payloads)
            else:
                pool = context.Pool(jobs, initializer=_initialize_worker, initargs=(progress_queue,))
                iterator = pool.imap_unordered(_process, payloads)
            for result in iterator:
                coordinator.record_result(result)
                LOG.info('Batch %d/%d: %s — %s', len(coordinator.results), len(paths),
                         'ok' if result['ok'] else 'failed', Path(result['source']).name)
            if pool:
                pool.close()
                pool.join()
            coordinator.drain()
            for _, _, _, _, job_id in payloads:
                if job_id not in coordinator.status._terminal_jobs:
                    reporter.emit('worker_lost', 'failed', job_id=job_id, outcome='failed',
                                  reason_code='missing-terminal-event')
            status = coordinator.summary()
            if status.get('free_bytes', 0) < max(1024**3, status['current_bytes']):
                reporter.emit('low_disk_space', 'finalizing', reason_code='observed-free-space-low',
                              observed_bytes=status['current_bytes'], peak_bytes=status['peak_bytes'],
                              free_bytes=status.get('free_bytes'))
            reporter.emit('batch_finished', 'complete', completed=len(coordinator.results), total=len(paths),
                          unit='jobs', outcome='success' if not coordinator.status.failed else 'partial-failure',
                          observed_bytes=status['current_bytes'], peak_bytes=status['peak_bytes'],
                          free_bytes=status.get('free_bytes'))
        except BaseException:
            if pool:
                pool.terminate()
                pool.join()
            coordinator.drain()
            status = coordinator.summary()
            reporter.emit('batch_interrupted', 'interrupted', completed=len(coordinator.results),
                          total=len(paths), unit='jobs', outcome='failed', reason_code='interrupted',
                          observed_bytes=status['current_bytes'], peak_bytes=status['peak_bytes'],
                          free_bytes=status.get('free_bytes'))
            atomic_json(previous_path, {'kind': 'batch', 'status': 'interrupted'})
            coordinator.close()
            progress_queue.close()
            raise
        summary = coordinator.summary()
        atomic_json(root / 'batch-summary.json', summary)
        atomic_json(previous_path, {'kind': 'batch', 'status': 'complete' if not summary['failed'] else 'partial-failure'})
        coordinator.close(summary)
        progress_queue.close()
        return summary
