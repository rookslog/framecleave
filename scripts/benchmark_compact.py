"""Qualify compact profiles with local raw results and privacy-safe aggregates."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

from framecleave.batch import discover
from framecleave.config import Config
from framecleave.detector import analyze
from framecleave.export import ExportSession
from framecleave.media import executable, probe, run, sha256_file
from framecleave.policy import ExportPolicy
from framecleave.storage import atomic_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _weighted_quality(rows: list[dict], weight_key: str) -> dict | None:
    rows = [row for row in rows if row.get('quality') and row.get(weight_key, 0) > 0]
    if not rows:
        return None
    total = sum(row[weight_key] for row in rows)
    quality = {}
    for metric in ('ssim', 'psnr'):
        means = [float('inf') if row['quality'][metric]['mean'] == 'infinity'
                 else row['quality'][metric]['mean'] for row in rows]
        minima = [float('inf') if row['quality'][metric]['minimum'] == 'infinity'
                  else row['quality'][metric]['minimum'] for row in rows]
        mean = sum(value * row[weight_key] for value, row in zip(means, rows, strict=True)) / total
        minimum = min(minima)
        quality[metric] = {'mean': mean if math.isfinite(mean) else 'infinity',
                           'minimum': minimum if math.isfinite(minimum) else 'infinity'}
    return quality


def summarize_runs(runs: list[dict]) -> dict:
    """Whitelist numeric/profile observations; never copy raw identity or exceptions."""
    groups = {}
    for row in runs:
        if (row['codec'] not in {'h264', 'hevc', 'unknown'} or row['corpus'] not in {'private', 'generated'}
                or type(row['crf']) is not int or row['crf'] not in {16, 18, 20}):
            raise ValueError('Invalid compact calibration profile identity')
        key = f"{row['codec']}-crf{row['crf']}"
        groups.setdefault(key, []).append(row)
    profiles = {}
    for key, rows in sorted(groups.items()):
        passed = [row for row in rows if row['structural'] == 'passed']
        source_bytes = sum(row['source_bytes'] for row in passed)
        output_bytes = sum(row['output_bytes'] for row in passed)
        seconds = sum(row['wall_seconds'] for row in passed)
        audio = Counter()
        methods = Counter()
        for row in passed:
            audio.update(row.get('audio_codecs', {}))
            methods.update(row.get('methods', {}))
        quality_rows = [{**row, 'quality_frames': row.get('quality_frames', row.get('frames', 0))}
                        for row in passed]
        profiles[key] = {
            'runs': len(rows), 'structural_passes': len(passed),
            'structural_failures': len(rows) - len(passed),
            'source_bytes': source_bytes, 'output_bytes': output_bytes,
            'output_source_ratio': output_bytes / source_bytes if source_bytes else None,
            'wall_seconds': seconds,
            'processing_speed_realtime': sum(row['duration_seconds'] for row in passed) / seconds if seconds else None,
            'quality': _weighted_quality(quality_rows, 'quality_frames'),
            'audio_codecs': dict(sorted(audio.items())),
            'audio_packet_bytes': sum(row.get('audio_packet_bytes', 0) for row in passed),
            'methods': dict(sorted(methods.items())),
            'visual_review': 'not-reviewed', 'consumer_playback': 'not-reviewed',
        }
    return {
        'schema_version': 1, 'benchmark_version': 'compact-full-coverage-v1',
        'candidates': [16, 18, 20], 'preset': 'medium', 'audio_policy': 'alac-or-pcm',
        'verification': 'independent-frame-ordinal-reference-encode-v1; rational timing; native audio equality',
        'timing_scope': 'probe, analysis, export, independent reference encoding, metrics, audio verification',
        'size_scope': 'all exported contiguous scenes / complete original source bytes',
        'audio_size_scope': 'encoded audio packet payload bytes; excludes container overhead',
        'corpora': dict(sorted(Counter(row['corpus'] for row in runs).items())),
        'profiles': profiles,
        'owner_decision': {'status': 'pending', 'selected_crf': None, 'reason': None},
        'limitations': ['Generated coverage does not replace private holdout visual review.',
                       'Runtime includes a second encode for content correspondence.',
                       'Reference replay requires certified encoder settings/build.',
                       'Native PCM fallback can exceed original compressed audio size.'],
    }


def write_result(path: Path, value: dict, *, force: bool = False) -> None:
    path = Path(path)
    if path.is_symlink():
        raise FileExistsError(f'Result must not be a symlink: {path}')
    if path.exists() and not force:
        raise FileExistsError(f'Refusing to overwrite result: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        atomic_json(path, value)
        return
    payload = (json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2) + '\n').encode()
    descriptor, temporary = tempfile.mkstemp(prefix='.compact-result-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _audio_packet_bytes(path: Path) -> int:
    command = [executable('ffprobe'), '-v', 'error', '-protocol_whitelist', 'file,pipe,crypto',
               '-select_streams', 'a', '-show_entries', 'packet=size', '-of', 'json', str(path)]
    document = json.loads(run(command))
    return sum(int(packet['size']) for packet in document.get('packets', []))


def benchmark_source(source: Path, directory: Path, *, crf: int, corpus: str, threads: int = 2) -> dict:
    start = time.monotonic()
    row = {'source_path': str(Path(source).resolve()), 'codec': 'unknown', 'crf': crf,
           'corpus': corpus, 'structural': 'failed'}
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        info = probe(source)
        row.update(codec=info.video['codec_name'] if info.video['codec_name'] in {'h264', 'hevc'} else 'unknown',
                   source_sha256=info.sha256,
                   source_bytes=info.path.stat().st_size)
        config = Config(threads=threads)
        timeline = analyze(info, config).timeline
        if timeline.frame_count < 3:
            raise ValueError('Calibration requires at least three source frames')
        cuts = [7, timeline.frame_count - 13] if timeline.frame_count > 21 else [1, timeline.frame_count - 1]
        scenes = timeline.scenes(cuts)
        policy = ExportPolicy.compact(crf=crf, source_codec=info.video['codec_name'], threads=threads)
        certificates = []
        outputs = []
        with ExportSession(info, timeline, directory / 'scratch', mode='compact', threads=threads,
                           policy=policy) as session:
            for scene in scenes:
                target = directory / 'scenes' / f"{scene['number']:04d}.mov"
                certificate = session.export(scene, target)
                atomic_json(directory / 'certificates' / f"{scene['number']:04d}.json", certificate)
                certificates.append(certificate)
                outputs.append(target)
        if sha256_file(info.path) != info.sha256:
            raise ValueError('Source changed during calibration')
        audio_codecs = Counter(track['codec'] for certificate in certificates for track in certificate['audio'])
        quality_rows = [{'quality': certificate['video'].get('quality'),
                         'frames': certificate['video']['frames_verified']}
                        for certificate in certificates if certificate['video'].get('quality')]
        row.update(
            structural='passed', frames=timeline.frame_count,
            quality_frames=sum(value['frames'] for value in quality_rows),
            duration_seconds=float((timeline.endpoint(timeline.frame_count) - timeline.endpoint(0)) * timeline.time_base),
            output_bytes=sum(path.stat().st_size for path in outputs),
            audio_codecs=dict(audio_codecs), audio_packet_bytes=sum(_audio_packet_bytes(path) for path in outputs),
            methods=dict(Counter(certificate['method'] for certificate in certificates)),
            quality=_weighted_quality(quality_rows, 'frames'),
            output_paths=[str(path) for path in outputs],
            resolved_policy=certificates[0]['policy'],
        )
    except Exception as exc:
        row.update(structural='failed', reason_code='calibration-export-failed',
                   error_type=type(exc).__name__, error=str(exc))
    row['wall_seconds'] = time.monotonic() - start
    return row


def generate_sources(directory: Path) -> list[Path]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    shapes = [('h264', 's16', False, False), ('h264', 'aac', False, False),
              ('hevc', 's16', False, False), ('hevc', 'aac', False, False),
              ('hevc', None, True, False), ('h264', None, False, True)]
    sources = []
    for number, (codec, audio, ten_bit, vfr) in enumerate(shapes, 1):
        target = directory / f'generated-{number:02d}.mov'
        encoder = 'libx264' if codec == 'h264' else 'libx265'
        command = [executable('ffmpeg'), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                   f"testsrc2=size=320x240:rate={60 if vfr else 30}:duration=2"]
        if audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=48000:duration=2']
        if ten_bit:
            command += ['-vf', 'format=yuv420p10le']
        if vfr:
            command += ['-vf', "select='not(mod(n,3))+eq(mod(n,11),1)',setpts=PTS+5.25/TB",
                        '-fps_mode', 'passthrough']
        command += ['-c:v', encoder, '-threads', '2', '-g', '60', '-crf', '19',
                    '-color_primaries', 'bt709', '-colorspace', 'bt709', '-color_trc', 'bt709',
                    '-video_track_timescale', '90000']
        if codec == 'hevc':
            command += ['-x265-params', 'pools=2:frame-threads=1:log-level=error', '-tag:v', 'hvc1']
        if audio:
            command += ['-c:a', 'pcm_s16le' if audio == 's16' else 'aac']
        run(command + [str(target)])
        sources.append(target)
    return sources


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--generated', action='store_true', help='Generate the deterministic corpus (default).')
    inputs.add_argument('--private-directory', type=Path, help='Explicit permitted local originals; raw results stay private.')
    parser.add_argument('-o', '--output', type=Path, required=True, help='Privacy-safe aggregate JSON.')
    parser.add_argument('--raw-output', type=Path, help='Separate local raw JSON, outside this repository for private runs.')
    parser.add_argument('--work-directory', type=Path, help='New directory retaining clips/certificates for visual review.')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--force', action='store_true', help='Replace existing result JSON only; never replace media/work directories.')
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.threads <= 64:
            raise ValueError('threads must be between 1 and 64')
        if args.output.is_symlink() or (args.output.exists() and not args.force):
            raise FileExistsError('Aggregate already exists or is a symlink')
        private = args.private_directory is not None
        if private and (args.raw_output is None or args.work_directory is None):
            raise ValueError('Private calibration requires --raw-output and --work-directory outside the repository')
        if private and any(path.resolve().is_relative_to(PROJECT_ROOT)
                           for path in [args.raw_output, args.work_directory]):
            raise ValueError('Private raw results and media must stay outside the repository')
        if args.raw_output and (args.raw_output.is_symlink() or (args.raw_output.exists() and not args.force)):
            raise FileExistsError('Raw result already exists or is a symlink')
        with ExitStack() as stack:
            if args.work_directory:
                root = args.work_directory.expanduser().absolute()
                root.mkdir(mode=0o700, parents=True, exist_ok=False)
            else:
                root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='framecleave-compact-')))
            corpus = 'private' if private else 'generated'
            sources = (discover([args.private_directory], root) if private
                       else generate_sources(root / 'inputs'))
            rows = []
            for number, source in enumerate(sources, 1):
                for crf in [16, 18, 20]:
                    row = benchmark_source(source, root / f'run-{number:03d}-crf{crf}',
                                           crf=crf, corpus=corpus, threads=args.threads)
                    rows.append(row)
                    print(f"{number}/{len(sources)} {row['codec']} CRF {crf}: {row['structural']}", file=sys.stderr)
            raw_output = args.raw_output or Path(tempfile.mkdtemp(prefix='framecleave-compact-results-')) / 'raw-results.json'
            write_result(raw_output, {'schema_version': 1, 'runs': rows}, force=args.force)
            aggregate = summarize_runs(rows)
            aggregate['hardware'] = {'system': platform.system(), 'machine': platform.machine(),
                                     'logical_cpus': os.cpu_count(), 'threads_per_encode': args.threads}
            write_result(args.output, aggregate, force=args.force)
            print(f'Raw results: {raw_output}', file=sys.stderr)
            print(f'Aggregate: {args.output}', file=sys.stderr)
            return 1 if any(row['structural'] != 'passed' for row in rows) else 0
    except (ValueError, OSError) as exc:
        print(f'benchmark_compact: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
