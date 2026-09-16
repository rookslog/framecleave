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


def parse_cuts(text: str) -> list[int]:
    try:
        cuts = [] if not text.strip() else [int(n.strip()) for n in text.split(',')]
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Cuts must be comma-separated integer frame ordinals') from exc
    if cuts != sorted(set(cuts)) or any(n <= 0 for n in cuts):
        raise argparse.ArgumentTypeError('Cuts must be positive, sorted, unique frame ordinals')
    return cuts


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog='framecleave', description='Local hard-cut detection and decode-verified frame-exact splitting.')
    root.add_argument('--version', action='version', version=f'framecleave {__version__}')
    subs = root.add_subparsers(dest='command', required=True)
    for name, help_text in [('inspect', 'Detect and create a local visual dry-run report; do not write clips.'),
                            ('split', 'Detect or use an index, then export and decode-verify each scene.'),
                            ('batch', 'Process multiple videos with bounded concurrency and failure isolation.')]:
        p = subs.add_parser(name, help=help_text, description=help_text)
        p.add_argument('inputs' if name == 'batch' else 'source', type=Path, nargs='+' if name == 'batch' else None)
        p.add_argument('-o', '--output', type=Path, required=True, help='New job directory; nonempty output requires --resume.')
        p.add_argument('--config', type=Path, help='Explicit TOML config containing a [framecleave] table.')
        p.add_argument('--threads', type=int, help='FFmpeg threads per file (default 2).')
        p.add_argument('--detector', choices=['temporal', 'pixel', 'histogram', 'adaptive'], help='temporal is default; other choices are benchmark baselines.')
        p.add_argument('--resume', action='store_true', help='Reuse a matching job; reject changed source/config/verified output.')
        p.add_argument('--mode', choices=['auto', 'lossless', 'copy-only'], default='auto', help='auto tries verified copy, then same-codec lossless encoding.')
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
    p = subs.add_parser('verify', help='Re-decode exported clips and compare all source frames and PCM samples.')
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
    group.add_argument('-v', '--verbose', action='store_true', help='Include diagnostic command logging on stderr.')


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG if args.verbose else logging.ERROR if args.quiet else logging.INFO)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger = logging.getLogger('framecleave')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    code = 0
    try:
        if args.command == 'doctor':
            result = diagnostics()
            code = 0 if result['ok'] else 3
        elif args.command == 'verify':
            from .workflow import verify_job
            if not 1 <= args.threads <= 64:
                raise ValueError('threads must be between 1 and 64')
            result = verify_job(args.source, args.index, threads=args.threads)
        else:
            config = load_config(args.config, threads=args.threads, detector=args.detector)
            if args.command == 'batch':
                from .batch import process_batch
                result = process_batch(args.inputs, args.output, config, jobs=args.jobs, recursive=args.recursive,
                                       dry_run=args.dry_run, thumbnails=args.thumbnails, resume=args.resume, mode=args.mode)
                code = 1 if result['failed'] else 0
            else:
                from .workflow import process_video
                result = process_video(args.source, args.output, config, dry_run=args.command == 'inspect' or args.dry_run,
                                       thumbnails=getattr(args, 'thumbnails', False), resume=args.resume,
                                       mode=args.mode, cuts=args.cuts, index_path=args.index)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        elif not args.quiet:
            if args.command == 'doctor':
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.command == 'batch':
                print(f"{result['succeeded']}/{result['total']} files succeeded; {result['failed']} failed. {args.output / 'batch-summary.json'}")
            elif args.command == 'verify':
                print(f"Verified {result['scene_count']} scenes: all decoded source frames and overlapping audio samples match.")
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
        if args.verbose:
            logger.exception('Diagnostic traceback')
        return 2
    except Exception as exc:
        if args.json:
            print(json.dumps({'error': str(exc), 'error_type': type(exc).__name__}))
        print(f'framecleave: {exc}', file=sys.stderr)
        if args.verbose:
            logger.exception('Diagnostic traceback')
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()
