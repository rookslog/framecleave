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
from .media import MediaError, ffmpeg_build_fingerprint, probe, sha256_file
from .model import SCHEMA_VERSION, read_index, validate_index
from .policy import ExportPolicy, bind_encoder_build, certificate_policy, policy_digest, resolve_policy
from .progress import NullProgressSink, ProgressEvent, ProgressReporter, ProgressSink
from .report import make_thumbnails, render_report
from .review_copy import ReviewCopySession, validate_review_certificate
from .storage import JobDirectory, JobLog, atomic_json, atomic_write
from .tempbudget import temporary_budget
from .transitions import CLASSIFIER_VERSION, annotate_transitions

LOG = logging.getLogger(__name__)


def _request(config: Config, mode: str, cuts: list[int] | None, index_path: Path | None,
             policy: ExportPolicy) -> dict:
    return {'tool_version': __version__, 'detector_version': DETECTOR_VERSION, 'config': config.to_dict(),
            'transition_classifier_version': CLASSIFIER_VERSION,
            'mode': mode, 'policy': policy.to_dict(), 'policy_digest': policy_digest(policy),
            'cuts': cuts, 'imported_index_sha256': sha256_file(index_path) if index_path else None}


def _segmentation_digest(index: dict) -> str:
    """Bind resume to the immutable timeline and partition, not mutable report paths."""
    value = {
        'source_sha256': index['source']['sha256'],
        'timeline': index['timeline'],
        'scenes': [[s['number'], s['start_frame'], s['end_frame']] for s in index['scenes']],
        'boundaries': [[b['frame'], b['pts'], b['decision']] for b in index['boundaries']],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _transition_digest(index: dict) -> str:
    value = [scene.get('transition') for scene in index['scenes']]
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _assert_contained(root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Job asset escapes the output directory: {path}')


def _validated_completed_record(root: Path, state: dict, scene: dict) -> dict:
    """Anchor an indexed output/certificate pair to the job's completed-state hashes."""
    completed = state.get('completed')
    record = completed.get(str(scene['number'])) if isinstance(completed, dict) else None
    if not isinstance(record, dict):
        raise ValueError(f"Scene {scene['number']} is not anchored in completed state")
    if (record.get('path') != scene.get('output_file')
            or record.get('certificate') != scene.get('export')):
        raise ValueError(f"Scene {scene['number']} paths differ from completed state")
    output = root / record['path']
    certificate = root / record['certificate']
    for asset in [output, certificate]:
        _assert_contained(root, asset)
        if not asset.is_file() or asset.is_symlink():
            raise ValueError(f"Scene {scene['number']} asset differs from completed state")
    if (sha256_file(output) != record.get('sha256')
            or sha256_file(certificate) != record.get('certificate_sha256')):
        raise ValueError(f"Scene {scene['number']} digest differs from completed state")
    return record


def _without_encoder_build(request: dict) -> dict:
    value = json.loads(json.dumps(request))
    value.pop('policy_digest', None)
    value.get('policy', {}).get('video', {})['encoder_build'] = None
    return value


def _copy_only_resume_policy(root: Path, state: dict, index_file: Path, request: dict,
                             source: Path, threads: int) -> ExportPolicy | None:
    recorded = state.get('request')
    if not isinstance(recorded, dict) or _without_encoder_build(recorded) != _without_encoder_build(request):
        return None
    if not index_file.is_file() or index_file.is_symlink():
        return None
    index = read_index(index_file)
    validate_index(index)
    completed = state.get('completed')
    expected = {str(scene['number']) for scene in index['scenes']}
    if not isinstance(completed, dict) or set(completed) != expected:
        return None
    for scene in index['scenes']:
        old = completed[str(scene['number'])]
        output = root / old.get('path', '')
        certificate_path = root / old.get('certificate', '')
        for asset in [output, certificate_path]:
            _assert_contained(root, asset)
            if not asset.is_file() or asset.is_symlink():
                return None
        if sha256_file(output) != old.get('sha256') or sha256_file(certificate_path) != old.get('certificate_sha256'):
            return None
        certificate = json.loads(certificate_path.read_text(encoding='utf-8'))
        if certificate.get('method') not in {'whole-file-copy', 'stream-copy-video'}:
            return None
        if certificate.get('output_sha256') != old.get('sha256'):
            return None
    verify_job(source, index_file, threads=threads)
    return ExportPolicy.from_dict(recorded['policy'])


class _JobLifecycleSink:
    """Publish exactly one terminal job event, after successful cleanup."""

    def __init__(self, sink: ProgressSink | None) -> None:
        self.sink = sink or NullProgressSink()
        self.last: ProgressEvent | None = None
        self.pending_success: ProgressEvent | None = None
        self.terminal = False

    def emit(self, event: ProgressEvent) -> None:
        self.last = event
        if event.event == 'job_finished':
            self.pending_success = event
            return
        if event.event == 'job_failed':
            self.terminal = True
        self.sink.emit(event)

    def publish_success(self) -> None:
        if self.pending_success is not None and not self.terminal:
            self.sink.emit(self.pending_success)
            self.terminal = True

    def publish_failure(self, exc: BaseException) -> None:
        self.pending_success = None
        if self.terminal or self.last is None:
            return
        failure = ProgressEvent(
            run_id=self.last.run_id,
            event='job_failed',
            phase='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
            sequence=self.last.sequence + 1,
            job_id=self.last.job_id,
            elapsed_seconds=self.last.elapsed_seconds,
            outcome='failed',
            reason_code='interrupted' if isinstance(exc, KeyboardInterrupt) else 'job-failed',
        )
        self.terminal = True
        try:
            self.sink.emit(failure)
        except BaseException:
            LOG.debug('Terminal job failure could not be emitted; preserving original error', exc_info=True)


def process_video(source: Path, directory: Path, config: Config, *, dry_run: bool = False,
                  thumbnails: bool = False, resume: bool = False, mode: str = 'auto',
                  cuts: list[int] | None = None, index_path: Path | None = None,
                  progress: ProgressSink | None = None, job_id: str | None = None,
                  policy: ExportPolicy | None = None, batch_temp_reserve: int = 0) -> dict:
    lifecycle = _JobLifecycleSink(progress)
    try:
        result = _process_video(source, directory, config, dry_run=dry_run, thumbnails=thumbnails,
                                resume=resume, mode=mode, cuts=cuts, index_path=index_path,
                                progress=lifecycle, job_id=job_id, policy=policy,
                                batch_temp_reserve=batch_temp_reserve)
    except BaseException as exc:
        lifecycle.publish_failure(exc)
        raise
    lifecycle.publish_success()
    return result


def _process_video(source: Path, directory: Path, config: Config, *, dry_run: bool = False,
                  thumbnails: bool = False, resume: bool = False, mode: str = 'auto',
                  cuts: list[int] | None = None, index_path: Path | None = None,
                  progress: ProgressSink | None = None, job_id: str | None = None,
                  policy: ExportPolicy | None = None, batch_temp_reserve: int = 0) -> dict:
    if cuts is not None and index_path is not None:
        raise ValueError('Use either explicit frame cuts or an imported index, not both')
    start = time.monotonic()
    reporter = ProgressReporter(progress, job_id=job_id or Path(directory).name)
    reporter.emit('job_started', 'starting')
    reporter.emit('probing_started', 'probing')
    try:
        info = probe(source)
    except BaseException as exc:
        reporter.emit('job_failed', 'probing', outcome='failed',
                      reason_code='interrupted' if isinstance(exc, KeyboardInterrupt) else 'probe-failed')
        raise
    resolved_policy = (bind_encoder_build(policy) if policy else
                       resolve_policy(mode, source_codec=info.video['codec_name'], threads=config.threads))
    if resolved_policy.mode != mode:
        raise ValueError('Export policy mode differs from the requested mode')
    if type(batch_temp_reserve) is not int or batch_temp_reserve < 0:
        raise ValueError('Batch temporary reserve must be a nonnegative integer')
    request = _request(config, mode, cuts, index_path, resolved_policy)
    copy_only_resume = False
    temp_limit = info.path.stat().st_size * 3 // 2 - batch_temp_reserve if mode == 'review-copy' else None
    with temporary_budget(temp_limit) as temp_budget, JobDirectory(directory, resume=resume) as root, JobLog(root):
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
                recorded_policy = (_copy_only_resume_policy(root, state, index_file, request, info.path,
                                                            config.threads)
                                   if resume and mode == 'compact' else None)
                if recorded_policy is None:
                    raise ValueError('Cannot resume: tool version, configuration, cuts, index, or export mode changed')
                resolved_policy = recorded_policy
                request = state['request']
                copy_only_resume = True
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
                if state.get('transitions_sha256') != _transition_digest(index):
                    raise ValueError('Cannot resume: transition annotations changed or their integrity record is missing')
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
                reporter.emit('analyzing_started', 'analyzing')

                def analysis_progress(number: int) -> None:
                    LOG.info('%s: decoded %d frames', info.path.name, number)
                    reporter.emit('analysis_progress', 'analyzing', completed=number, unit='frames')

                analysis = analyze(info, config, analysis_progress)
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
                reporter.emit('boundaries_detected', 'analyzing', completed=len(accepted),
                              total=len(accepted), unit='boundaries')
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
                atomic_write(root / 'analysis-metrics.npz', lambda handle: np.savez_compressed(handle, metrics=analysis.metrics))
            validate_index(index)
            if not (resume and index_file.exists()):
                reporter.emit('transitions_started', 'classifying')
                annotate_transitions(info, index, threads=config.threads, analysis_width=config.analysis_width,
                                     analysis_height=config.analysis_height)
                reporter.emit('transitions_finished', 'classifying', outcome='success')
            state['segmentation_sha256'] = _segmentation_digest(index)
            state['transitions_sha256'] = _transition_digest(index)
            atomic_json(state_path, state)
            atomic_json(index_file, index)
            exported = skipped = 0
            if not dry_run:
                LOG.info('Exporting %d scenes from %s', len(index['scenes']), info.path.name)
                reporter.emit('export_started', 'exporting', completed=0,
                              total=len(index['scenes']), unit='scenes')
                # Refuse symlinked child directories before opening private scratch or clips.
                for name in ['scenes', 'scratch', 'certificates', 'thumbnails']:
                    _assert_contained(root, root / name)
                    if (root / name).is_symlink():
                        raise ValueError(f'Job subdirectory must not be a symlink: {name}')
                exporter = (ReviewCopySession(info, timeline, reporter=reporter, policy=resolved_policy,
                                              defer_certified=True)
                            if mode == 'review-copy' else
                            ExportSession(info, timeline, root / 'scratch', threads=config.threads, mode=mode,
                                          reporter=reporter, diagnostics='diagnostics.log', policy=resolved_policy,
                                          bind_reference_encoder=not copy_only_resume, defer_certified=True))
                with exporter as session:
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
                            if (certificate.get('schema_version') != resolved_policy.certificate_schema
                                    or certificate.get('policy_digest') != policy_digest(resolved_policy)):
                                raise ValueError(f'Previously verified scene {key} has a changed certificate policy')
                            video = certificate.get('video', {})
                            if mode == 'review-copy':
                                validate_review_certificate(certificate, info, timeline, scene, state['segmentation_sha256'])
                            if (certificate.get('output_sha256') != old['sha256']
                                    or video.get('first_source_frame') != scene['start_frame']
                                    or video.get('last_source_frame') != scene['end_frame'] - 1
                                    or (mode != 'review-copy' and video.get('frames_verified') != scene['frame_count'])):
                                raise ValueError(f'Previously verified scene {key} has an inconsistent certificate')
                            scene['output_file'] = relative
                            scene['export'] = old['certificate']
                            skipped += 1
                            continue
                        if target.exists():
                            raise FileExistsError(f'Uncertified output exists; it will not be overwritten: {target}')
                        LOG.info('%s: scene %s [%d, %d)', info.path.name, key, scene['start_frame'], scene['end_frame'])
                        certificate = session.export(scene, target)
                        if mode == 'review-copy':
                            certificate['segmentation_sha256'] = state['segmentation_sha256']
                        cert_relative = f'certificates/{scene["number"]:04d}.json'
                        atomic_json(root / cert_relative, certificate)
                        scene['output_file'] = relative
                        scene['export'] = cert_relative
                        state['completed'][key] = {'path': relative, 'sha256': certificate['output_sha256'],
                                                   'certificate': cert_relative,
                                                   'certificate_sha256': sha256_file(root / cert_relative)}
                        atomic_json(state_path, state)
                        atomic_json(index_file, index)
                        session.publish_certified()
                        exported += 1
            if dry_run or thumbnails:
                make_thumbnails(info, index, root, threads=config.threads)
            reporter.emit('report_started', 'reporting')
            render_report(index, root)
            reporter.emit('report_finished', 'reporting', outcome='success')
            if sha256_file(info.path) != info.sha256:
                raise MediaError('Source content changed during processing; job is not certified complete')
            atomic_json(index_file, index)
            status = 'inspected' if dry_run and not state['completed'] else 'complete'
            state.update(status=status, wall_seconds=time.monotonic() - start)
            atomic_json(state_path, state)
            result = {'source': str(info.path), 'output': str(root), 'status': status,
                      'scene_count': len(index['scenes']), 'review_candidates': sum(b['decision'] == 'review' for b in index['boundaries']),
                      'frame_count': timeline.frame_count, 'exported': exported,
                      'skipped_verified': skipped if mode != 'review-copy' else 0,
                      'skipped_integrity_checked': skipped if mode == 'review-copy' else 0,
                      'wall_seconds': state['wall_seconds'], 'policy': resolved_policy.to_dict(),
                      'policy_digest': policy_digest(resolved_policy)}
            if temp_budget:
                result['temporary_storage'] = {'limit_bytes': temp_budget.limit,
                                               'peak_reserved_bytes': temp_budget.peak_bytes,
                                               'batch_parent_reserve_bytes': batch_temp_reserve,
                                               'scope': 'owned-logical-temporary-bytes; published assets/logs excluded'}
            atomic_json(root / 'run-summary.json', result)
            reporter.emit('job_finished', 'complete', completed=len(index['scenes']),
                          total=len(index['scenes']), unit='scenes', outcome='success')
            return result
        except BaseException as exc:
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc))
            try:
                atomic_json(state_path, state)
            except BaseException:
                LOG.debug('Failure state could not be persisted; preserving original error', exc_info=True)
            try:
                reporter.emit('job_failed', 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                              outcome='failed',
                              reason_code='interrupted' if isinstance(exc, KeyboardInterrupt) else 'job-failed',
                              diagnostics='diagnostics.log')
            except BaseException:
                LOG.debug('Terminal job failure could not be emitted; preserving original error', exc_info=True)
            raise


def verify_job(source: Path, index_path: Path, *, threads: int = 2) -> dict:
    """Check the recorded policy: review integrity/inventory or explicit exact decode."""
    index = read_index(index_path)
    timeline = validate_index(index)
    info = probe(source)
    if info.sha256 != index['source']['sha256']:
        raise ValueError('Verification source digest differs from the indexed source')
    root = Path(index_path).resolve().parent
    state_path = root / 'state.json'
    _assert_contained(root, state_path)
    if not state_path.is_file() or state_path.is_symlink():
        raise ValueError('Verification requires an owned completed state record')
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if state.get('source_sha256') != info.sha256:
        raise ValueError('Verification source differs from completed state')
    results = []
    policies = []
    methods = {}
    certificates = {}
    current_encoder_build = None
    for scene in index['scenes']:
        _validated_completed_record(root, state, scene)
        if not scene.get('export'):
            raise ValueError('Cannot verify a scene without an export certificate')
        certificate_path = root / scene['export']
        _assert_contained(root, certificate_path)
        if certificate_path.is_symlink():
            raise ValueError('Certificate must not be a symlink')
        certificate = json.loads(certificate_path.read_text(encoding='utf-8'))
        certificates[scene['number']] = certificate
        methods[scene['number']] = certificate.get('method')
        policy = certificate_policy(certificate, source_codec=info.video['codec_name'])
        policies.append(policy)
        if certificate.get('method') == 'compact-reencode':
            current_encoder_build = current_encoder_build or ffmpeg_build_fingerprint(policy.video.encoder)
            if certificate.get('video', {}).get('reference_encoder_build') != current_encoder_build:
                raise ValueError('Compact reference encoder build differs from the certified output')
    if len({policy_digest(policy) for policy in policies}) != 1:
        raise ValueError('Job certificates carry inconsistent export policies')
    policy = policies[0]
    if policy.mode == 'review-copy':
        with ReviewCopySession(info, timeline, policy=policy) as session:
            for scene in index['scenes']:
                certificate = certificates[scene['number']]
                validate_review_certificate(certificate, info, timeline, scene, _segmentation_digest(index))
                if not scene.get('output_file'):
                    raise ValueError('Cannot verify an unexported scene')
                path = root / scene['output_file']
                _assert_contained(root, path)
                if path.is_symlink():
                    raise ValueError('Review clip must not be a symlink')
                output = probe(path)
                if output.sha256 != certificate.get('output_sha256'):
                    raise ValueError('Review output digest differs')
                video, audio = session.inspect_output(output)
                results.append({'scene': scene['number'], 'video': video, 'audio': audio})
        return {'verified': True, 'scene_count': len(results), 'scenes': results,
                'policy': policy.to_dict(), 'policy_digest': policy_digest(policy),
                'verification_scope': 'file-integrity-and-stream-inventory',
                'pixel_equality': 'not_applicable', 'audio_sample_equality': 'not_applicable'}
    with tempfile.TemporaryDirectory(prefix='framecleave-verify-') as temporary:
        with ExportSession(info, timeline, Path(temporary), threads=threads, mode=policy.mode, policy=policy,
                           bind_reference_encoder=any(method == 'compact-reencode'
                                                      for method in methods.values())) as session:
            for scene in index['scenes']:
                if not scene.get('output_file'):
                    raise ValueError('Cannot verify an unexported scene')
                path = root / scene['output_file']
                _assert_contained(root, path)
                output = probe(path)
                whole = whole_scene(scene, timeline) and output.sha256 == info.sha256
                video = (session.verify_compact_video(scene, output)
                         if policy.mode == 'compact' and methods[scene['number']] == 'compact-reencode'
                         else session.verify_exact_video(scene, output, whole=whole))
                if policy.mode == 'compact':
                    video.pop('all_native_pixels_equal', None)
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
    return {'verified': True, 'scene_count': len(results), 'scenes': results,
            'policy': policy.to_dict(), 'policy_digest': policy_digest(policy),
            'pixel_equality': 'not_applicable' if policy.mode == 'compact' else 'equal'}
