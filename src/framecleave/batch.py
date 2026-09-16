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
from .storage import JobDirectory, atomic_json
from .workflow import process_video

LOG = logging.getLogger(__name__)
EXTENSIONS = {'.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.mts', '.m2ts', '.ts', '.mpeg', '.mpg'}


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


def _initialize_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _stop_worker)


def _process(payload: tuple) -> dict:
    source, output, config, options = payload
    try:
        result = process_video(source, output, config, **options)
        return {'ok': True, **result}
    except Exception as exc:
        return {'ok': False, 'source': str(source), 'output': str(output), 'error_type': type(exc).__name__, 'error': str(exc)}


def process_batch(inputs: list[Path], output: Path, config: Config, *, jobs: int = 1,
                  recursive: bool = False, dry_run: bool = False, thumbnails: bool = False,
                  resume: bool = False, mode: str = 'auto') -> dict:
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
        payloads = [(path, root / _name(path), config, options) for path in paths]
        results = []
        pool = None
        try:
            if jobs == 1:
                iterator = map(_process, payloads)
            else:
                pool = multiprocessing.get_context('spawn').Pool(jobs, initializer=_initialize_worker)
                iterator = pool.imap_unordered(_process, payloads)
            for result in iterator:
                results.append(result)
                LOG.info('Batch %d/%d: %s — %s', len(results), len(paths), 'ok' if result['ok'] else 'failed', Path(result['source']).name)
                atomic_json(root / 'batch-summary.json', _summary(results, len(paths)))
            if pool:
                pool.close()
                pool.join()
        except BaseException:
            if pool:
                pool.terminate()
                pool.join()
            atomic_json(previous_path, {'kind': 'batch', 'status': 'interrupted'})
            raise
        summary = _summary(results, len(paths))
        atomic_json(root / 'batch-summary.json', summary)
        atomic_json(previous_path, {'kind': 'batch', 'status': 'complete' if not summary['failed'] else 'partial-failure'})
        return summary


def _summary(results: list[dict], total: int) -> dict:
    return {'total': total, 'processed': len(results), 'succeeded': sum(r['ok'] for r in results),
            'failed': sum(not r['ok'] for r in results), 'files': sorted(results, key=lambda r: r['source'])}
