"""Small Unix CLI; stdout is reserved for results, progress and failures use stderr."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from . import __version__
from .config import load_config
from .diagnostics import diagnostics
from .presentation import OutputMode, TerminalProgressSink


def parse_cuts(text: str) -> list[int]:
    try:
        cuts = [] if not text.strip() else [int(n.strip()) for n in text.split(',')]
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Cuts must be comma-separated integer frame ordinals') from exc
    if cuts != sorted(set(cuts)) or any(n <= 0 for n in cuts):
        raise argparse.ArgumentTypeError('Cuts must be positive, sorted, unique frame ordinals')
    return cuts


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog='framecleave', description='Local scene detection, fast stream-copy review slices, and one final encode.')
    root.add_argument('--version', action='version', version=f'framecleave {__version__}')
    subs = root.add_subparsers(dest='command', required=True)
    for name, help_text in [('inspect', 'Detect and create a local visual dry-run report; do not write clips.'),
                            ('split', 'Detect or use an index, then copy compressed review scenes without re-encoding.'),
                            ('batch', 'Process multiple videos with bounded concurrency and failure isolation.')]:
        p = subs.add_parser(name, help=help_text, description=help_text)
        p.add_argument('inputs' if name == 'batch' else 'source', type=Path, nargs='+' if name == 'batch' else None)
        p.add_argument('-o', '--output', type=Path, required=True, help='New job directory; nonempty output requires --resume.')
        p.add_argument('--config', type=Path, help='Explicit TOML config containing a [framecleave] table.')
        p.add_argument('--threads', type=int, help='FFmpeg threads per file (default 2).')
        p.add_argument('--detector', choices=['temporal', 'pixel', 'histogram', 'adaptive'], help='temporal is default; other choices are benchmark baselines.')
        p.add_argument('--resume', action='store_true', help='Reuse a matching job; reject changed source/config/verified output.')
        p.add_argument('--mode', choices=['review-copy', 'compact', 'auto', 'lossless', 'copy-only'], default='review-copy', help='review-copy (default) copies video/audio packets with approximate playable edges, no encoding fallback. auto/lossless/copy-only retain exact verification; compact encodes each scene.')
        if name != 'inspect':
            p.add_argument('--dry-run', action='store_true', help='Generate index/report/thumbnails without exporting clips.')
            p.add_argument('--thumbnails', action='store_true', help='Write scene endpoint and boundary thumbnails during export.')
        if name != 'batch':
            group = p.add_mutually_exclusive_group()
            group.add_argument('--cuts', type=parse_cuts, help='Replace detection with exact zero-based cut ordinals, e.g. 123,456.')
            group.add_argument('--index', type=Path, help='Use a source-fingerprinted scene index instead of rerunning detection.')
        else:
            p.add_argument('--recursive', action='store_true', help='Recurse through input directories, excluding output.')
            p.add_argument('--jobs', type=int, default=1, help='Concurrent files, 1–8; default 1 minimizes memory/disk pressure.')
        _presentation(p)
    p = subs.add_parser('assemble', help='Trim selected review copies and encode their assembly once (CRF 16/18).')
    p.add_argument('indexes', type=Path, nargs='+', help='scene-index.json files, in job-number order.')
    p.add_argument('--scenes', required=True, help='Playback order: 1,3 for one index; 1:3,2:5 for multiple indexes (job:scene).')
    p.add_argument('-o', '--output', type=Path, required=True, help='New final .mp4; existing outputs/sidecars are never overwritten.')
    p.add_argument('--crf', type=int, choices=[16, 18], default=18, help='Lower is higher quality, not a fixed size guarantee.')
    p.add_argument('--threads', type=int, default=2)
    _presentation(p)
    p = subs.add_parser('verify', help='Check the recorded policy: review integrity/inventory or exact decoded frames/audio.')
    p.add_argument('source', type=Path)
    p.add_argument('index', type=Path)
    p.add_argument('--threads', type=int, default=2)
    _presentation(p)
    p = subs.add_parser('doctor', help='Report dependencies, versions, architecture, and actual backend capabilities.')
    _presentation(p)
    return root


def _presentation(p):
    p.add_argument('--json', action='store_true', help='Write one machine-readable JSON result to stdout.')
    group = p.add_mutually_exclusive_group()
    group.add_argument('-q', '--quiet', action='store_true', help='Suppress progress and non-JSON success output.')
    group.add_argument('-v', '--verbose', action='store_true', help='Write lifecycle and attempt milestones to stderr.')
    group.add_argument('--debug', action='store_true', help='Include diagnostic command logging and tracebacks on stderr; output may contain private paths.')


def _output_mode(args) -> OutputMode:
    if args.quiet:
        return OutputMode.QUIET
    if args.verbose:
        return OutputMode.VERBOSE
    if args.debug:
        return OutputMode.DEBUG
    return OutputMode.DEFAULT


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    mode = _output_mode(args)
    sink = TerminalProgressSink(sys.stderr, mode)
    logger = logging.getLogger('framecleave')
    previous_level = logger.level
    handler = None
    if mode is OutputMode.DEBUG:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    code = 0
    result = None
    try:
        if args.command == 'doctor':
            result = diagnostics()
            code = 0 if result['ok'] else 3
        elif args.command == 'verify':
            from .workflow import verify_job
            if not 1 <= args.threads <= 64:
                raise ValueError('threads must be between 1 and 64')
            result = verify_job(args.source, args.index, threads=args.threads)
        elif args.command == 'assemble':
            from .assemble import assemble
            selections = []
            for item in args.scenes.split(','):
                fields = item.strip().split(':')
                if len(fields) == 1 and len(args.indexes) == 1:
                    fields = ['1', *fields]
                if len(fields) != 2 or any(not n.isdecimal() or int(n) <= 0 for n in fields):
                    raise ValueError('Scenes must be positive scene numbers, or job:scene with multiple indexes')
                selections.append(tuple(map(int, fields)))
            result = assemble(args.indexes, selections, args.output, crf=args.crf, threads=args.threads, progress=sink)
        else:
            config = load_config(args.config, threads=args.threads, detector=args.detector)
            if args.command == 'batch':
                from .batch import process_batch
                result = process_batch(args.inputs, args.output, config, jobs=args.jobs, recursive=args.recursive,
                                       dry_run=args.dry_run, thumbnails=args.thumbnails, resume=args.resume,
                                       mode=args.mode, progress=sink)
                code = 1 if result['failed'] else 0
            else:
                from .workflow import process_video
                result = process_video(args.source, args.output, config, dry_run=args.command == 'inspect' or args.dry_run,
                                       thumbnails=getattr(args, 'thumbnails', False), resume=args.resume,
                                       mode=args.mode, cuts=args.cuts, index_path=args.index, progress=sink)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        elif not args.quiet:
            if args.command == 'doctor':
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.command == 'batch':
                print(f"{result['succeeded']}/{result['total']} files succeeded; {result['failed']} failed. {args.output / 'batch-summary.json'}")
            elif args.command == 'verify':
                if result['policy']['mode'] == 'review-copy':
                    print(f"Checked {result['scene_count']} review scenes: file integrity and stream inventory; decoded pixel/sample equality is not applicable.")
                elif result['pixel_equality'] == 'equal':
                    print(f"Verified {result['scene_count']} scenes under {result['policy']['mode']}: all decoded source frames and overlapping audio samples match.")
                else:
                    print(f"Verified {result['scene_count']} scenes under compact: exact frame timing and lossless audio; video quality evidence recorded.")
            elif args.command == 'assemble':
                print(f"Assembled {result['selected_scene_count']} scenes once at CRF {result['crf']}. {result['output']}")
            else:
                print(f"{result['status']}: {result['scene_count']} scenes, {result['review_candidates']} review candidates. {result['output']}")
        return code
    except KeyboardInterrupt:
        print('framecleave: interrupted; completed verified clips are retained for --resume', file=sys.stderr)
        return 130
    except (ValueError, KeyError, TypeError, OSError) as exc:
        if args.json:
            print(json.dumps({'error': str(exc), 'error_type': type(exc).__name__}))
        print(f'framecleave: {exc}', file=sys.stderr)
        if mode is OutputMode.DEBUG:
            logger.exception('Diagnostic traceback')
        return 2
    except Exception as exc:
        if args.json:
            print(json.dumps({'error': str(exc), 'error_type': type(exc).__name__}))
        print(f'framecleave: {exc}', file=sys.stderr)
        if mode is OutputMode.DEBUG:
            logger.exception('Diagnostic traceback')
        return 1
    finally:
        sink.close(result)
        if handler is not None:
            logger.removeHandler(handler)
            handler.close()
            logger.setLevel(previous_level)
