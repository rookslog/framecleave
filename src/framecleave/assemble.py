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
from .media import (MediaError, MediaInfo, PreservationError, audit_frame_metadata, executable,
                    hdr_metadata_present, probe, sha256_file, video_hashes)
from .model import read_index, validate_index
from .progress import ProgressReporter, ProgressSink
from .review_copy import validate_review_certificate
from .storage import JobLog, atomic_json_noclobber
from .tempbudget import reserve_temp, temporary_budget
from .workflow import _assert_contained, _segmentation_digest, _validated_completed_record

_VIDEO_ATTRIBUTES = ('codec_name', 'width', 'height', 'pix_fmt', 'sample_aspect_ratio',
                     'color_range', 'color_space', 'color_transfer', 'color_primaries', 'chroma_location')
_COLOR_OPTIONS = (('color_range', '-color_range'), ('color_space', '-colorspace'),
                  ('color_transfer', '-color_trc'), ('color_primaries', '-color_primaries'),
                  ('chroma_location', '-chroma_sample_location'))
_KNOWN_VALUES = {None, 'unknown', 'unspecified', 'N/A'}


def _display_rotations(payload: dict) -> list:
    """Nonzero display-matrix rotations that make FFmpeg autorotate an input."""
    return [entry.get('rotation') for entry in payload.get('side_data_list', []) if entry.get('rotation')]


def _audio_identity(stream: dict) -> tuple:
    """Stable semantic identity; muxer/vendor-specific fields are intentionally excluded."""
    tags = stream.get('tags') or {}
    disposition = stream.get('disposition') or {}
    return (tags.get('language'), tags.get('title'),
            tuple(sorted(name for name, enabled in disposition.items() if enabled)))


def _audio_layout(stream: dict) -> tuple:
    return (stream.get('sample_rate'), stream.get('channels'), stream.get('channel_layout'),
            _audio_identity(stream))


def _color_options(video: dict) -> list:
    options = []
    for field, option in _COLOR_OPTIONS:
        value = video.get(field)
        if value not in _KNOWN_VALUES:
            options += [option, str(value)]
    return options


def _verify_color(video: dict, expected: dict) -> None:
    for field, _ in _COLOR_OPTIONS:
        value = expected.get(field)
        if value in _KNOWN_VALUES:
            continue
        if video.get(field) != value:
            raise PreservationError(
                f'Final assembly changed {field}: {value!r} -> {video.get(field)!r}')


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
        state_path = path.parent / 'state.json'
        _assert_contained(path.parent, state_path)
        if not state_path.is_file() or state_path.is_symlink():
            raise ValueError('Assembly requires an owned completed state record')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('source_sha256') != source['sha256']:
            raise ValueError('Assembly index source differs from completed state')
        # Recorded source inventory is sufficient; originals are not assembly inputs.
        info = MediaInfo(Path(source['path']), {'streams': source['streams'], 'format': source.get('format', {})}, source['sha256'])
        jobs.append((path.parent, index, timeline, info, state))
    selected = []
    layout = None
    for job_number, scene_number in selections:
        if (type(job_number) is not int or type(scene_number) is not int
                or not 1 <= job_number <= len(jobs)):
            raise ValueError('Invalid job:scene selection')
        root, index, timeline, info, state = jobs[job_number-1]
        scene = next((s for s in index['scenes'] if s['number'] == scene_number), None)
        if scene is None or not scene.get('output_file') or not scene.get('export'):
            raise ValueError('Selected scene is absent or unexported')
        _validated_completed_record(root, state, scene)
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
        rotations = _display_rotations(actual.video)
        if rotations:
            raise PreservationError(
                f'Selected clip has nonzero display rotation {rotations}; assembly would autorotate it')
        if actual.video['codec_name'] not in {'h264', 'hevc'}:
            raise ValueError('Final assembly supports H.264/HEVC')
        if hdr_metadata_present(actual.video):
            raise PreservationError('HDR final assembly is not qualified; no normalization attempted')
        audit = audit_frame_metadata(actual, threads=threads)
        requested_frames = cert['source_range']['end_frame'] - cert['source_range']['start_frame']
        if audit['frames_audited'] < requested_frames:
            raise ValueError(
                f'Selected clip {clip.name} decodes {audit["frames_audited"]} frames, shorter than its '
                f'certified requested interval of {requested_frames} frames')
        current = (tuple(actual.video.get(key) for key in _VIDEO_ATTRIBUTES),
                   tuple(_audio_layout(stream) for stream in actual.audio))
        if layout is not None and current != layout:
            raise ValueError(
                'Selected video geometry/color/codec or audio identity/layout differ; no normalization attempted')
        layout = current
        selected.append({'job': job_number, 'scene': scene_number, 'path': str(clip),
                         'sha256': actual.sha256, 'size_bytes': clip.stat().st_size,
                         'source_sha256': info.sha256, 'source_range': cert['source_range'],
                         'visible_origin_rational': str(Fraction(actual.video.get('start_time', '0'))),
                         'audio_stream_count': len(actual.audio), 'method': cert['method'],
                         'frames_audited': audit['frames_audited'], 'requested_frames': requested_frames,
                         'audio_identities': tuple(_audio_identity(stream) for stream in actual.audio),
                         'last_frame_duration_rational': str(
                             timeline.durations[scene['end_frame'] - 1] * timeline.time_base)})
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
        command += ['-threads', str(threads), '-noautorotate', '-protocol_whitelist', 'file,pipe,crypto',
                    '-i', item['path']]
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
    last_duration = Fraction(selected[-1]['last_frame_duration_rational'])
    last_duration_us = max(
        1, (last_duration.numerator * 10**6 + last_duration.denominator - 1)
        // last_duration.denominator)
    command += ['-c:v', 'libx264' if codec == 'h264' else 'libx265', '-threads', str(threads),
                '-preset', 'medium', '-crf', str(crf), '-fps_mode', 'vfr',
                '-enc_time_base', '1:1000000', '-bsf:v', f'setts=duration={last_duration_us}',
                '-map_chapters', '-1']
    if codec == 'hevc':
        command += ['-x265-params', f'bframes=0:pools={threads}:frame-threads=1:log-level=error',
                    '-tag:v', 'hvc1']
    else:
        command += ['-bf', '0']
    command += _color_options(dict(zip(_VIDEO_ATTRIBUTES, layout[0])))
    if audio_count:
        command += ['-c:a', 'aac', '-b:a', '128k']
        for track, (language, title, dispositions) in enumerate(selected[0]['audio_identities']):
            if language is not None:
                command += [f'-metadata:s:a:{track}', f'language={language}']
            if title is not None:
                command += [f'-metadata:s:a:{track}', f'title={title}']
            command += [f'-disposition:a:{track}', '+'.join(dispositions) or '0']
    command += ['-f', 'mp4', str(partial)]
    reporter = ProgressReporter(progress, job_id=output.name)
    reporter.emit('job_started', 'assembling')
    started = time.monotonic()
    requested_frames = sum(item['requested_frames'] for item in selected)
    requested_duration = sum((Fraction(item['source_range']['duration_rational']) for item in selected), Fraction())
    owned = False
    resources = ExitStack()
    try:
        resources.enter_context(temporary_budget(limit))
        media_reservation = resources.enter_context(reserve_temp(limit))
        fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        owned = True
        with JobLog(output.parent, filename=diagnostics.name):
            run_limited(command, partial, limit, label='final assembly', on_progress=lambda frames:
                        reporter.emit('assembly_progress', 'encoding', completed=min(frames, requested_frames),
                                      total=requested_frames, unit='frames'))
            result_info = probe(partial)
            run_limited([executable('ffmpeg'), '-nostdin', '-v', 'error', '-xerror', '-threads', str(threads),
                         '-i', str(partial), '-f', 'null', '-'], partial, limit, label='final decode check')
            output_frames = video_hashes(result_info, threads=threads)
            if len(output_frames) != requested_frames:
                raise MediaError(
                    f'Final assembly decoded {len(output_frames)} frames, expected the {requested_frames} requested')
            output_span = (output_frames[-1]['pts'] + output_frames[-1]['duration']
                           - output_frames[0]['pts']) * result_info.time_base
            coverage_tolerance = max(
                Fraction(len(selected), 10**6), len(selected) * result_info.time_base)
            if output_span < requested_duration - coverage_tolerance:
                raise MediaError(
                    f'Final assembly covers {output_span} of the certified {requested_duration} requested duration')
            _verify_color(result_info.video, dict(zip(_VIDEO_ATTRIBUTES, layout[0])))
            if tuple(_audio_identity(stream) for stream in result_info.audio) != selected[0]['audio_identities']:
                raise PreservationError('Final assembly changed audio stream identity or dispositions')
        result = {'schema_version': 1, 'output': str(output), 'output_sha256': result_info.sha256,
                  'output_size_bytes': partial.stat().st_size, 'selected_scene_count': len(selected),
                  'selected': selected, 'crf': crf, 'video_encodes': 1, 'audio_codec': 'aac' if audio_count else None,
                  'temp_media_limit_bytes': limit, 'decode_success': True,
                  'requested_frames': requested_frames, 'verified_output_frames': len(output_frames),
                  'requested_duration_rational': str(requested_duration),
                  'output_duration_rational': str(output_span),
                  'coverage_tolerance_rational': str(coverage_tolerance),
                  'output_duration': result_info.document.get('format', {}).get('duration'),
                  'wall_seconds': time.monotonic()-started,
                  'diagnostics': diagnostics.name,
                  'warnings': ['CRF controls quality, not final file size.', 'Packet-copy edges and audio joins are not sample/pixel-exact.']}
        for item in selected:
            if sha256_file(item['path']) != item['sha256']:
                raise ValueError(f"Selected clip changed during assembly: {item['path']}")
        os.link(partial, output)
        partial.unlink()
        media_reservation.close()
        atomic_json_noclobber(manifest, result)
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
