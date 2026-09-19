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
from .tempbudget import TemporaryBudget, temporary_budget
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
    limits = {p: p.stat().st_size * 3 // 2 if p.is_file() else 0 for p in paths}
    reserves = {p: min(1024**2, limit // 8) for p, limit in limits.items()} if mode == 'review-copy' else {}
    parent_budget = TemporaryBudget(sum(reserves.values())) if mode == 'review-copy' else None
    with temporary_budget(parent_budget), JobDirectory(output, resume=resume) as root:
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
            temp_budget=parent_budget,
            input_temp_limit=sum(limits.values()) if parent_budget else None,
        )
        coordinator.start()
        reporter = ProgressReporter(coordinator)
        payloads = [(path, root / _name(path), config,
                     {**options, 'batch_temp_reserve': reserves.get(path, 0)}, _name(path)) for path in paths]
        pool = None
        lost_workers = False
        results_seen = set()
        summary = None
        try:
            reporter.emit('batch_started', 'starting', total=len(paths), completed=0, unit='jobs')
            if jobs == 1:
                global _WORKER_PROGRESS
                # In-process producers fail synchronously with parent persistence;
                # spawned workers still use the transport and sole parent writer.
                _WORKER_PROGRESS = coordinator
                iterator = map(_process, payloads)
            else:
                pool = context.Pool(jobs, initializer=_initialize_worker, initargs=(progress_queue,))
                iterator = pool.imap_unordered(_process, payloads)
                # Retain original handles: Pool silently replaces a dead worker but
                # never resolves that worker's in-flight result. No elapsed-time
                # timeout is imposed while all actual workers remain alive.
                workers = tuple(pool._pool)
            while len(results_seen) < len(payloads):
                coordinator.check_health()
                if pool:
                    try:
                        result = iterator.next(timeout=0.2)
                    except multiprocessing.TimeoutError:
                        if not any(worker.exitcode is not None for worker in workers):
                            continue
                        lost_workers = True
                        pool.terminate()
                        pool.join()
                        pool = None
                        for path, directory, _, _, job_id in payloads:
                            if job_id in results_seen:
                                continue
                            failed = {'ok': False, 'job_id': job_id, 'source': str(path), 'output': str(directory),
                                      'error_type': 'WorkerLost', 'error': 'Worker exited before returning; outcome is unconfirmed'}
                            coordinator.record_result(failed)
                            reporter.emit('worker_lost', 'failed', job_id=job_id, outcome='failed',
                                          reason_code='worker-process-exited')
                            results_seen.add(job_id)
                        break
                else:
                    result = next(iterator)
                coordinator.record_result(result)
                results_seen.add(result['job_id'])
                LOG.info('Batch %d/%d: %s — %s', len(coordinator.results), len(paths),
                         'ok' if result['ok'] else 'failed', Path(result['source']).name)
            if pool and not lost_workers:
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
            summary = coordinator.summary()
            atomic_json(root / 'batch-summary.json', summary)
            atomic_json(previous_path, {'kind': 'batch', 'status': 'complete' if not summary['failed'] else 'partial-failure'})
            coordinator.check_health()
            return summary
        except BaseException as exc:
            if pool:
                pool.terminate()
                pool.join()
            try:
                coordinator.drain()
            except Exception:
                LOG.debug('Progress drain also failed during shutdown', exc_info=True)
            status = coordinator.summary()
            try:
                reporter.emit('batch_interrupted', 'interrupted', completed=len(coordinator.results),
                              total=len(paths), unit='jobs', outcome='failed', reason_code='interrupted',
                              observed_bytes=status['current_bytes'], peak_bytes=status['peak_bytes'],
                              free_bytes=status.get('free_bytes'))
            except Exception:
                LOG.debug('Terminal event persistence failed during shutdown', exc_info=True)
            try:
                atomic_json(previous_path, {'kind': 'batch',
                            'status': 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                            'error_type': type(exc).__name__})
            except Exception:
                LOG.debug('Terminal state could not be persisted; preserve original storage error', exc_info=True)
            raise
        finally:
            try:
                coordinator.close(summary)
            except Exception:
                if coordinator.error is None:
                    raise
                LOG.debug('Progress cleanup preserved the original error', exc_info=True)
            finally:
                progress_queue.close()
