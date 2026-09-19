"""Decode selected review copies independently and encode their assembly once."""
from __future__ import annotations

from fractions import Fraction
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time
import uuid

from .limited_process import run_limited
from .media import MediaInfo, executable, probe
from .model import read_index, validate_index
from .progress import ProgressReporter, ProgressSink
from .review_copy import validate_review_certificate
from .storage import JobLog, atomic_json
from .tempbudget import reserve_temp, temporary_budget
from .workflow import _assert_contained, _segmentation_digest


def assemble(index_paths: list[Path], selections: list[tuple[int, int]], output: Path, *,
             crf: int = 18, threads: int = 2, max_temp_bytes: int | None = None,
             progress: ProgressSink | None = None) -> dict:
    if type(crf) is not int or crf not in {16, 18}:
        raise ValueError('Final assembly CRF must be 16 or 18')
    if type(threads) is not int or not 1 <= threads <= 64:
        raise ValueError('threads must be between 1 and 64')
    if not index_paths or not selections:
        raise ValueError('Provide indexes and at least one selected scene')
    output = Path(output).expanduser().absolute()
    partial = output.with_name(output.name + '.partial')
    manifest = output.with_name(output.name + '.assembly.json')
    diagnostics = output.with_name(output.name + f'.diagnostics-{uuid.uuid4().hex}.log')
    if output.suffix.lower() != '.mp4':
        raise ValueError('Final assembly output must be .mp4')
    if any(p.exists() or p.is_symlink() for p in [output, partial, manifest]):
        raise FileExistsError('Assembly target or sidecar exists; refusing overwrite')
    jobs = []
    for path in index_paths:
        path = Path(path).expanduser().absolute()
        if path.is_symlink():
            raise ValueError('Assembly index must not be a symlink')
        index = read_index(path)
        timeline = validate_index(index)
        source = index['source']
        # Recorded source inventory is sufficient; originals are not assembly inputs.
        info = MediaInfo(Path(source['path']), {'streams': source['streams'], 'format': source.get('format', {})}, source['sha256'])
        jobs.append((path.parent, index, timeline, info))
    selected = []
    layout = None
    for job_number, scene_number in selections:
        if (type(job_number) is not int or type(scene_number) is not int
                or not 1 <= job_number <= len(jobs)):
            raise ValueError('Invalid job:scene selection')
        root, index, timeline, info = jobs[job_number-1]
        scene = next((s for s in index['scenes'] if s['number'] == scene_number), None)
        if scene is None or not scene.get('output_file') or not scene.get('export'):
            raise ValueError('Selected scene is absent or unexported')
        clip, cert_path = root / scene['output_file'], root / scene['export']
        for asset in [clip, cert_path]:
            _assert_contained(root, asset)
            if asset.is_symlink():
                raise ValueError('Assembly assets must not be symlinks')
        cert = json.loads(cert_path.read_text())
        validate_review_certificate(cert, info, timeline, scene, _segmentation_digest(index))
        actual = probe(clip)
        if actual.sha256 != cert.get('output_sha256'):
            raise ValueError('Selected clip digest differs')
        attributes = ['codec_name', 'width', 'height', 'pix_fmt', 'sample_aspect_ratio',
                      'color_range', 'color_space', 'color_transfer', 'color_primaries']
        current = ([actual.video.get(k) for k in attributes],
                   [[a.get(k) for k in ['sample_rate', 'channels', 'channel_layout']] for a in actual.audio])
        if actual.video['codec_name'] not in {'h264', 'hevc'}:
            raise ValueError('Final assembly supports H.264/HEVC')
        if actual.video.get('color_transfer') in {'smpte2084', 'arib-std-b67'}:
            raise ValueError('HDR final assembly is not qualified; no normalization attempted')
        if layout is not None and current != layout:
            raise ValueError('Selected video geometry/color/codec or audio layouts differ; no normalization attempted')
        layout = current
        selected.append({'job': job_number, 'scene': scene_number, 'path': str(clip),
                         'sha256': actual.sha256, 'size_bytes': clip.stat().st_size,
                         'source_sha256': info.sha256, 'source_range': cert['source_range'],
                         'visible_origin_rational': str(Fraction(actual.video.get('start_time', '0'))),
                         'audio_stream_count': len(actual.audio), 'method': cert['method']})
    ceiling = sum({s['path']: s['size_bytes'] for s in selected}.values()) * 3 // 2
    if max_temp_bytes is not None and (type(max_temp_bytes) is not int or not 0 < max_temp_bytes <= ceiling):
        raise ValueError('Temporary budget must be positive and at most 1.5× selected input bytes')
    limit = ceiling if max_temp_bytes is None else max_temp_bytes
    if output.parent.is_symlink():
        raise ValueError('Assembly output directory must not be a symlink')
    output.parent.mkdir(parents=True, exist_ok=True)
    audio_count = selected[0]['audio_stream_count']
    graph = []
    labels = []
    command = [executable('ffmpeg'), '-nostdin', '-hide_banner', '-v', 'warning', '-xerror', '-y',
               '-nostats', '-progress', 'pipe:2', '-stats_period', '1']
    for number, item in enumerate(selected):
        command += ['-threads', str(threads), '-protocol_whitelist', 'file,pipe,crypto', '-i', item['path']]
        duration = f"{float(Fraction(item['source_range']['duration_rational'])):.12f}"
        graph.append(f'[{number}:v:0]trim=start=0:duration={duration},setpts=PTS-STARTPTS[v{number}]')
        labels.append(f'[v{number}]')
        for track in range(audio_count):
            graph.append(f'[{number}:a:{track}]atrim=start=0:duration={duration},asetpts=PTS,'
                         f'aresample=async=1:first_pts=0,apad=whole_dur={duration},atrim=duration={duration}[a{number}_{track}]')
            labels.append(f'[a{number}_{track}]')
    destinations = '[v]' + ''.join(f'[a{i}]' for i in range(audio_count))
    graph.append(''.join(labels) + f'concat=n={len(selected)}:v=1:a={audio_count}' + destinations)
    command += ['-filter_complex_threads', str(threads), '-filter_complex', ';'.join(graph), '-map', '[v]']
    for track in range(audio_count):
        command += ['-map', f'[a{track}]']
    codec = layout[0][0]
    command += ['-c:v', 'libx264' if codec == 'h264' else 'libx265', '-threads', str(threads),
                '-preset', 'medium', '-crf', str(crf), '-fps_mode', 'vfr', '-map_chapters', '-1']
    if codec == 'hevc':
        command += ['-x265-params', f'pools={threads}:frame-threads=1:log-level=error', '-tag:v', 'hvc1']
    if audio_count:
        command += ['-c:a', 'aac', '-b:a', '128k']
    command += ['-f', 'mp4', str(partial)]
    reporter = ProgressReporter(progress, job_id=output.name)
    reporter.emit('job_started', 'assembling')
    started = time.monotonic()
    owned = False
    resources = ExitStack()
    try:
        resources.enter_context(temporary_budget(limit))
        media_reservation = resources.enter_context(reserve_temp(limit))
        fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        owned = True
        requested_frames = sum(s['source_range']['end_frame']-s['source_range']['start_frame'] for s in selected)
        with JobLog(output.parent, filename=diagnostics.name):
            run_limited(command, partial, limit, label='final assembly', on_progress=lambda frames:
                        reporter.emit('assembly_progress', 'encoding', completed=min(frames, requested_frames),
                                      total=requested_frames, unit='frames'))
            result_info = probe(partial)
            run_limited([executable('ffmpeg'), '-nostdin', '-v', 'error', '-xerror', '-threads', str(threads),
                         '-i', str(partial), '-f', 'null', '-'], partial, limit, label='final decode check')
        result = {'schema_version': 1, 'output': str(output), 'output_sha256': result_info.sha256,
                  'output_size_bytes': partial.stat().st_size, 'selected_scene_count': len(selected),
                  'selected': selected, 'crf': crf, 'video_encodes': 1, 'audio_codec': 'aac' if audio_count else None,
                  'temp_media_limit_bytes': limit, 'decode_success': True,
                  'requested_duration_rational': str(sum((Fraction(s['source_range']['duration_rational']) for s in selected), Fraction())),
                  'output_duration': result_info.document.get('format', {}).get('duration'),
                  'wall_seconds': time.monotonic()-started,
                  'diagnostics': diagnostics.name,
                  'warnings': ['CRF controls quality, not final file size.', 'Packet-copy edges and audio joins are not sample/pixel-exact.']}
        os.link(partial, output)
        partial.unlink()
        media_reservation.close()
        atomic_json(manifest, result)
        reporter.emit('job_finished', 'complete', outcome='success')
        return result
    except BaseException as exc:
        reporter.emit('job_failed', 'assembling', outcome='failed', reason_code='assembly-failed')
        if output.exists():
            raise ValueError(f'Assembly media was published at {output}, but finalization failed; retained without overwrite. Diagnostics: {diagnostics.name}') from exc
        raise
    finally:
        if owned:
            partial.unlink(missing_ok=True)
        resources.close()
