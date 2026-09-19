"""Fast audiovisual packet-copy previews, not frame/sample-exact certificates.

One unfinished media file is allowed per session. No raw audio/video caches,
reference encodes, or automatic encoding fallback are used. Intended source
ranges survive independently of physical packet boundaries and MP4 edit lists.
"""
from __future__ import annotations

from fractions import Fraction
import logging
import os
from pathlib import Path
import threading
import time

from .limited_process import run_limited
from .media import MediaError, MediaInfo, executable, probe, sha256_file
from .model import Timeline, rational
from .policy import ExportPolicy, certificate_policy, policy_digest, resolve_policy
from .progress import ProgressReporter, ProgressSink
from .tempbudget import Reservation, available_temp

LOG = logging.getLogger(__name__)


def intended_range(info: MediaInfo, timeline: Timeline, scene: dict) -> dict:
    a, b = scene['start_frame'], scene['end_frame']
    start, end = (timeline.endpoint(n) * timeline.time_base for n in (a, b))
    raw_origin = info.document.get('format', {}).get('start_time')
    origin = (timeline.pts[0] * timeline.time_base if raw_origin in {None, 'N/A'}
              else Fraction(raw_origin))
    return {'start_frame': a, 'end_frame': b, 'start_time_rational': rational(start),
            'end_time_rational': rational(end), 'duration_rational': rational(end-start),
            'input_seek_rational': rational(start-origin)}


def validate_review_certificate(certificate: dict, info: MediaInfo, timeline: Timeline,
                               scene: dict, segmentation_digest: str) -> None:
    policy = certificate_policy(certificate, source_codec=info.video['codec_name'])
    video = certificate.get('video', {})
    if (policy.mode != 'review-copy' or certificate.get('source_sha256') != info.sha256
            or certificate.get('segmentation_sha256') != segmentation_digest
            or certificate.get('source_range') != intended_range(info, timeline, scene)
            or video.get('first_source_frame') != scene['start_frame']
            or video.get('last_source_frame') != scene['end_frame'] - 1
            or video.get('requested_frame_count') != scene['frame_count']
            or video.get('pixel_equality') != 'not_applicable'
            or 'frames_verified' in video):
        raise ValueError('Review certificate source, segmentation, intended range or verification scope differs')


class ReviewCopySession:
    def __init__(self, info: MediaInfo, timeline: Timeline, *, max_temp_bytes: int | None = None,
                 progress: ProgressSink | None = None, reporter: ProgressReporter | None = None,
                 policy: ExportPolicy | None = None):
        self.info = info
        self.timeline = timeline
        self.policy = policy or resolve_policy('review-copy', source_codec=info.video['codec_name'])
        if self.policy.mode != 'review-copy':
            raise ValueError('Review exporter requires a review-copy policy')
        ceiling = info.path.stat().st_size * 3 // 2
        if max_temp_bytes is not None and (type(max_temp_bytes) is not int or not 0 < max_temp_bytes <= ceiling):
            raise ValueError('Temporary media budget must be positive and no larger than 1.5× input bytes')
        self.max_temp_bytes = available_temp(ceiling if max_temp_bytes is None else max_temp_bytes)
        self.progress = reporter or ProgressReporter(progress)
        self._export_lock = threading.Lock()

    def __enter__(self) -> 'ReviewCopySession':
        return self

    def __exit__(self, *_):
        pass  # Each export owns and releases its partial file, including on interruption.

    def _run_copy(self, command: list[str], partial: Path) -> int:
        return run_limited(command, partial, self.max_temp_bytes, label='stream-copy')

    def inspect_output(self, output: MediaInfo) -> tuple[dict, list[dict]]:
        """Compare stream inventory, not decoded pixels, samples, or exact boundaries."""
        if output.video['codec_name'] != self.info.video['codec_name']:
            raise MediaError('Packet-copy output changed video codec')
        for field in ['width', 'height']:
            if output.video[field] != self.info.video[field]:
                raise MediaError(f'Packet-copy output changed video {field}')
        if len(output.audio) != len(self.info.audio):
            raise MediaError('Packet-copy output changed audio stream count')
        audio = []
        for source, actual in zip(self.info.audio, output.audio, strict=True):
            for field in ['codec_name', 'sample_rate', 'channels']:
                if source.get(field) != actual.get(field):
                    raise MediaError(f'Packet-copy output changed audio {field}')
            audio.append({'source_stream_index': source['index'], 'codec': actual['codec_name'],
                          'sample_equality': 'not_applicable'})
        return {'pixel_equality': 'not_applicable', 'stream_inventory': 'equal',
                'codec': output.video['codec_name'],
                'decode_success': 'not_checked', 'boundary_accuracy': 'packet-copy-preview'}, audio

    def export(self, scene: dict, target: Path) -> dict:
        if not self._export_lock.acquire(blocking=False):
            raise ValueError('Review session already has an active export')
        try:
            return self._export(scene, target)
        finally:
            self._export_lock.release()

    def _export(self, scene: dict, target: Path) -> dict:
        a, b = scene['start_frame'], scene['end_frame']
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= self.timeline.frame_count:
            raise ValueError('Review interval must be a nonempty source frame range')
        target = Path(target)
        partial = target.with_name(target.name + '.partial')
        if target.exists() or target.is_symlink() or partial.exists() or partial.is_symlink():
            raise FileExistsError('Review output or unowned partial exists; refusing overwrite')
        if target.parent.is_symlink():
            raise ValueError('Review output directory must not be a symlink')
        target.parent.mkdir(parents=True, exist_ok=True)
        start = self.timeline.endpoint(a) * self.timeline.time_base
        end = self.timeline.endpoint(b) * self.timeline.time_base
        source_range = intended_range(self.info, self.timeline, scene)
        seek = Fraction(source_range['input_seek_rational'])
        scene_id = str(scene['number'])
        started = time.monotonic()
        self.progress.emit('scene_started', 'remuxing', scene_id=scene_id)
        self.progress.emit('attempt_started', 'remuxing', scene_id=scene_id, attempt_id='audiovisual-copy')
        owned = False
        reservation = Reservation(self.max_temp_bytes)
        try:
            # Exclusive creation establishes ownership before the writer may use -y.
            descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            owned = True
            whole = a == 0 and b == self.timeline.frame_count
            diagnostics_bytes = 0
            if whole:
                with self.info.path.open('rb') as source, partial.open('wb') as dest:
                    written = 0
                    while block := source.read(1024 * 1024):
                        if written + len(block) > self.max_temp_bytes:
                            raise MediaError('Temporary media budget exceeded; no re-encoding attempted')
                        dest.write(block)
                        written += len(block)
                if sha256_file(partial) != self.info.sha256:
                    raise MediaError('Whole-file copy source digest mismatch')
                method = 'whole-file-copy'
            else:
                if self.info.video['codec_name'] not in {'h264', 'hevc'}:
                    raise MediaError('Review MP4 copying supports H.264/HEVC; no re-encoding attempted')
                command = [executable('ffmpeg'), '-nostdin', '-hide_banner', '-v', 'warning', '-y',
                           '-ss', f'{float(seek):.12f}', '-protocol_whitelist', 'file,pipe,crypto',
                           '-i', str(self.info.path), '-t', f'{float(end-start):.12f}',
                           '-map', f"0:{self.info.video['index']}", '-map', '0:a?', '-c', 'copy',
                           '-map_chapters', '-1', '-f', 'mp4']
                if self.info.video['codec_name'] == 'hevc':
                    command += ['-tag:v', 'hvc1']
                diagnostics_bytes = self._run_copy(command + [str(partial)], partial)
                method = 'audiovisual-stream-copy'
            video, audio = self.inspect_output(probe(partial, fingerprint=False))
            video.update(first_source_frame=a, last_source_frame=b-1, requested_frame_count=b-a)
            result = {'schema_version': 2, 'method': method, 'source_sha256': self.info.sha256,
                      'policy': self.policy.to_dict(), 'policy_digest': policy_digest(self.policy),
                      'source_range': source_range,
                      'video': video, 'audio': audio, 'output_sha256': sha256_file(partial),
                      'output_size_bytes': partial.stat().st_size, 'wall_seconds': time.monotonic()-started,
                      'temp_media_limit_bytes': self.max_temp_bytes,
                      'diagnostics_bytes': diagnostics_bytes,
                      'verification': {'video': 'not_applicable', 'audio': 'not_applicable'},
                      'warnings': ['Packet-copy preview edges may include extra frames; trim recorded ranges during final assembly.']}
            os.link(partial, target)  # Atomic, no-clobber publication; no second media copy.
            self.progress.emit('scene_certified', 'remuxing', scene_id=scene_id, outcome='success')
            return result
        except BaseException as exc:
            self.progress.emit('scene_failed', 'remuxing', scene_id=scene_id, outcome='failed',
                               reason_code='interrupted' if isinstance(exc, KeyboardInterrupt) else 'review-copy-failed')
            raise
        finally:
            if owned:
                partial.unlink(missing_ok=True)
            reservation.close()
