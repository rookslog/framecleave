#!/usr/bin/env python3
"""Run the deferred macOS 27 ARM64 gate, without enabling unverified hardware paths.

Run locally on the target Mac. No private video is uploaded. The optional input compares
software and VideoToolbox native decoded pixels/timing. Results are measurements, not
an automatic change to production defaults.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import platform
import subprocess
import sys
import time

from framecleave.diagnostics import diagnostics
from framecleave.media import ffmpeg_base, probe, run, video_hashes
from framecleave.storage import atomic_json


def require_target() -> None:
    version = platform.mac_ver()[0]
    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or not version or int(version.split('.')[0]) < 27:
        raise RuntimeError('This gate requires native arm64 Python on macOS 27 or newer; no emulated results accepted')


def compare_videotoolbox(path: Path) -> dict:
    info = probe(path)
    started = time.monotonic()
    reference = video_hashes(info)
    software_seconds = time.monotonic() - started
    tb = info.time_base
    command = ffmpeg_base() + ['-hwaccel', 'videotoolbox', '-copyts', '-noautorotate',
                              '-protocol_whitelist', 'file,pipe,crypto', '-i', str(info.path),
                              '-map', f'0:{info.video["index"]}', '-an', '-sn', '-dn',
                              '-fps_mode', 'passthrough', '-enc_time_base', f'{tb.numerator}:{tb.denominator}',
                              '-c:v', 'rawvideo', '-pix_fmt', info.video['pix_fmt'], '-threads', '1',
                              '-f', 'framehash', '-hash', 'sha256', 'pipe:1']
    result = {'source_sha256': info.sha256, 'software_seconds': software_seconds,
              'source_frames': len(reference), 'videotoolbox_validated_for_this_input': False}
    started = time.monotonic()
    try:
        text = run(command).decode('ascii')
        rows = []
        for line in text.splitlines():
            if line and not line.startswith('#'):
                f = [part.strip() for part in line.split(',')]
                rows.append({'pts': int(f[2]), 'duration': int(f[3]), 'size': int(f[4]), 'sha256': f[5]})
        base_line = next(line for line in text.splitlines() if line.startswith('#tb 0:'))
        from fractions import Fraction
        result['videotoolbox_validated_for_this_input'] = rows == reference and Fraction(base_line.split(':', 1)[1].strip()) == tb
        result['videotoolbox_frames'] = len(rows)
        result['note'] = 'Matching one input does not establish general HDR/codec support or enable the production backend.'
    except Exception as exc:
        # Do not put a command/error containing private filenames into public benchmark output.
        result['error_type'] = type(exc).__name__
        result['note'] = 'Hardware decode failed; inspect local FFmpeg diagnostics privately.'
    result['videotoolbox_seconds'] = time.monotonic() - started
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input', type=Path, help='Optional permitted local media for native VideoToolbox comparison')
    args = parser.parse_args()
    require_target()
    args.output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    test = subprocess.run([sys.executable, '-m', 'pytest', str(repo / 'tests'), '-q'], capture_output=True, text=True)
    (args.output / 'tests.log').write_text(test.stdout + test.stderr)
    environment = diagnostics()
    environment['macos_version'] = platform.mac_ver()[0]
    for name in ['ffmpeg', 'ffprobe']:
        if environment.get(name):
            environment[name].pop('path', None)
    result = {'environment': environment, 'tests_exit_code': test.returncode, 'videotoolbox': None}
    if args.input:
        result['videotoolbox'] = compare_videotoolbox(args.input)
    atomic_json(args.output / 'macos-validation.json', result)
    return 0 if test.returncode == 0 and environment['ok'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
