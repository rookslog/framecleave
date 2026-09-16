"""Single-source orchestration; detection, review, and export have separate contracts."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import tempfile
import time

import numpy as np

from . import __version__
from .audio import slice_track
from .config import Config
from .detector import DETECTOR_VERSION, analyze, detect
from .diagnostics import diagnostics
from .export import ExportSession, output_suffix, whole_scene
from .media import MediaError, probe, sha256_file
from .model import SCHEMA_VERSION, read_index, validate_index
from .report import make_thumbnails, render_report
from .storage import JobDirectory, JobLog, atomic_json

LOG = logging.getLogger(__name__)


def _request(config: Config, mode: str, cuts: list[int] | None, index_path: Path | None) -> dict:
    return {'tool_version': __version__, 'detector_version': DETECTOR_VERSION, 'config': config.to_dict(),
            'mode': mode, 'cuts': cuts, 'imported_index_sha256': sha256_file(index_path) if index_path else None}


def _segmentation_digest(index: dict) -> str:
    """Bind resume to the immutable timeline and partition, not mutable report paths."""
    value = {
        'source_sha256': index['source']['sha256'],
        'timeline': index['timeline'],
        'scenes': [[s['number'], s['start_frame'], s['end_frame']] for s in index['scenes']],
        'boundaries': [[b['frame'], b['pts'], b['decision']] for b in index['boundaries']],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _assert_contained(root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Job asset escapes the output directory: {path}')


def process_video(source: Path, directory: Path, config: Config, *, dry_run: bool = False,
                  thumbnails: bool = False, resume: bool = False, mode: str = 'auto',
                  cuts: list[int] | None = None, index_path: Path | None = None) -> dict:
    if cuts is not None and index_path is not None:
        raise ValueError('Use either explicit frame cuts or an imported index, not both')
    start = time.monotonic()
    info = probe(source)
    request = _request(config, mode, cuts, index_path)
    with JobDirectory(directory, resume=resume) as root, JobLog(root):
        for asset in ['thumbnails', 'scenes', 'scratch', 'certificates', 'scene-index.json', 'state.json']:
            _assert_contained(root, root / asset)
            if (root / asset).is_symlink():
                raise ValueError(f'Job asset must not be a symlink: {asset}')
        state_path = root / 'state.json'
        index_file = root / 'scene-index.json'
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if state.get('source_sha256') != info.sha256:
                raise ValueError('Cannot resume: source digest differs from the original job')
            if state.get('request') != request:
                raise ValueError('Cannot resume: tool version, configuration, cuts, index, or export mode changed')
        else:
            state = {'schema_version': 1, 'source_sha256': info.sha256, 'request': request,
                     'status': 'started', 'completed': {}, 'run_count': 0}
        state['run_count'] += 1
        state['status'] = 'running'
        state.pop('error', None)
        atomic_json(state_path, state)
        try:
            if resume and index_file.exists():
                index = read_index(index_file)
                timeline = validate_index(index)
                if index['source']['sha256'] != info.sha256:
                    raise ValueError('Scene index source digest differs')
                if state.get('segmentation_sha256') != _segmentation_digest(index):
                    raise ValueError('Cannot resume: segmentation changed or its integrity record is missing')
            elif index_path is not None:
                index = read_index(index_path)
                if index['source']['sha256'] != info.sha256:
                    raise ValueError('Imported scene index belongs to another source')
                timeline = validate_index(index)
                if timeline.time_base != info.time_base:
                    raise ValueError('Imported scene index time base differs from source')
                index['source'] = info.source_dict(timeline.frame_count)
                for scene in index['scenes']:
                    scene['output_file'] = None
                    scene['thumbnails'] = {}
                    scene.pop('export', None)
                for boundary in index['boundaries']:
                    boundary.pop('thumbnails', None)
            else:
                LOG.info('Analyzing %s', info.path.name)
                analysis = analyze(info, config, lambda n: LOG.info('%s: decoded %d frames', info.path.name, n))
                timeline = analysis.timeline
                if cuts is None:
                    boundaries = detect(info, analysis, config)
                    accepted = [b['frame'] for b in boundaries if b['decision'] == 'cut']
                    detector = {'name': config.detector, 'version': DETECTOR_VERSION,
                                'confidence': 'uncalibrated evidence; not probabilities'}
                else:
                    timeline.scenes(cuts)  # Validate before writing anything.
                    accepted = cuts
                    boundaries = [{'frame': n, 'pts': timeline.pts[n], 'decision': 'cut',
                                   'reason': 'explicit user frame boundary', 'evidence': {}} for n in cuts]
                    detector = {'name': 'explicit-frame-cuts', 'version': '1'}
                index = {'schema_version': SCHEMA_VERSION, 'tool_version': __version__,
                         'interval_semantics': 'decoded-frames-half-open',
                         'source': info.source_dict(timeline.frame_count), 'timeline': timeline.to_dict(),
                         'scenes': timeline.scenes(accepted), 'boundaries': boundaries,
                         'detector': detector, 'configuration': config.to_dict(),
                         'provenance': diagnostics(), 'analysis_seconds': analysis.wall_seconds,
                         'timing_class': analysis.timing_class,
                         'warnings': ['Automatic detection may miss edits or split continuous motion; inspect the report.',
                                      'HDR/auxiliary/interlaced export support is deliberately restricted.']}
                # Compact, private per-frame diagnostics support reproducible error investigation.
                with tempfile.NamedTemporaryFile(prefix='.metrics-', dir=root, delete=False) as handle:
                    temporary = Path(handle.name)
                    np.savez_compressed(handle, metrics=analysis.metrics)
                temporary.replace(root / 'analysis-metrics.npz')
            validate_index(index)
            state['segmentation_sha256'] = _segmentation_digest(index)
            atomic_json(state_path, state)
            atomic_json(index_file, index)
            exported = skipped = 0
            if not dry_run:
                LOG.info('Exporting %d scenes from %s', len(index['scenes']), info.path.name)
                # Refuse symlinked child directories before opening private scratch or clips.
                for name in ['scenes', 'scratch', 'certificates', 'thumbnails']:
                    _assert_contained(root, root / name)
                    if (root / name).is_symlink():
                        raise ValueError(f'Job subdirectory must not be a symlink: {name}')
                with ExportSession(info, timeline, root / 'scratch', threads=config.threads, mode=mode) as session:
                    for scene in index['scenes']:
                        key = str(scene['number'])
                        relative = f"scenes/{scene['number']:04d}{output_suffix(info, timeline, scene, mode)}"
                        target = root / relative
                        _assert_contained(root, target)
                        old = state['completed'].get(key)
                        if old:
                            if old['path'] != relative or not target.is_file() or target.is_symlink() or sha256_file(target) != old['sha256']:
                                raise ValueError(f'Previously verified scene {key} has a missing file or changed digest')
                            cert_relative = f'certificates/{scene["number"]:04d}.json'
                            cert_path = root / cert_relative
                            if (old.get('certificate') != cert_relative or cert_path.is_symlink()
                                    or not cert_path.is_file()
                                    or old.get('certificate_sha256') != sha256_file(cert_path)):
                                raise ValueError(f'Previously verified scene {key} has a missing or changed certificate')
                            certificate = json.loads(cert_path.read_text(encoding='utf-8'))
                            video = certificate.get('video', {})
                            if (certificate.get('output_sha256') != old['sha256']
                                    or video.get('first_source_frame') != scene['start_frame']
                                    or video.get('last_source_frame') != scene['end_frame'] - 1
                                    or video.get('frames_verified') != scene['frame_count']):
                                raise ValueError(f'Previously verified scene {key} has an inconsistent certificate')
                            scene['output_file'] = relative
                            scene['export'] = old['certificate']
                            skipped += 1
                            continue
                        if target.exists():
                            raise FileExistsError(f'Uncertified output exists; it will not be overwritten: {target}')
                        LOG.info('%s: scene %s [%d, %d)', info.path.name, key, scene['start_frame'], scene['end_frame'])
                        certificate = session.export(scene, target)
                        cert_relative = f'certificates/{scene["number"]:04d}.json'
                        atomic_json(root / cert_relative, certificate)
                        scene['output_file'] = relative
                        scene['export'] = cert_relative
                        state['completed'][key] = {'path': relative, 'sha256': certificate['output_sha256'],
                                                   'certificate': cert_relative,
                                                   'certificate_sha256': sha256_file(root / cert_relative)}
                        atomic_json(state_path, state)
                        atomic_json(index_file, index)
                        exported += 1
            if dry_run or thumbnails:
                make_thumbnails(info, index, root, threads=config.threads)
            render_report(index, root)
            if sha256_file(info.path) != info.sha256:
                raise MediaError('Source content changed during processing; job is not certified complete')
            atomic_json(index_file, index)
            status = 'inspected' if dry_run and not state['completed'] else 'complete'
            state.update(status=status, wall_seconds=time.monotonic() - start)
            atomic_json(state_path, state)
            result = {'source': str(info.path), 'output': str(root), 'status': status,
                      'scene_count': len(index['scenes']), 'review_candidates': sum(b['decision'] == 'review' for b in index['boundaries']),
                      'frame_count': timeline.frame_count, 'exported': exported, 'skipped_verified': skipped,
                      'wall_seconds': state['wall_seconds']}
            atomic_json(root / 'run-summary.json', result)
            return result
        except BaseException as exc:
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc))
            atomic_json(state_path, state)
            raise


def verify_job(source: Path, index_path: Path, *, threads: int = 2) -> dict:
    """Re-decode every exported frame and PCM slice; do not trust the old certificate."""
    index = read_index(index_path)
    timeline = validate_index(index)
    info = probe(source)
    if info.sha256 != index['source']['sha256']:
        raise ValueError('Verification source digest differs from the indexed source')
    root = Path(index_path).resolve().parent
    results = []
    with tempfile.TemporaryDirectory(prefix='framecleave-verify-') as temporary:
        with ExportSession(info, timeline, Path(temporary), threads=threads) as session:
            for scene in index['scenes']:
                if not scene.get('output_file'):
                    raise ValueError('Cannot verify an unexported scene')
                path = root / scene['output_file']
                _assert_contained(root, path)
                output = probe(path)
                whole = whole_scene(scene, timeline) and output.sha256 == info.sha256
                video = session.verify_video(scene, output, whole=whole)
                audio = []
                if not whole:
                    session.prepare()
                    start = timeline.endpoint(scene['start_frame']) * timeline.time_base
                    end = timeline.endpoint(scene['end_frame']) * timeline.time_base
                    work = session.work / f'verify-{scene["number"]}'
                    parts = [part for track in session.audio for part in [slice_track(track, start, end, work / 'slices')] if part]
                    audio = session.verify_audio(output, parts, work / 'decoded')
                results.append({'scene': scene['number'], 'video': video, 'audio': audio,
                                'all_streams_byte_identical': whole})
    return {'verified': True, 'scene_count': len(results), 'scenes': results}
