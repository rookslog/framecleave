#!/usr/bin/env python3
"""Reproduce exact-frame comparisons from SHA-256-keyed annotations.

No private source names, paths, thumbnails or raw frames are written to the result.
Only run on media you are permitted to process. External model scores are not implied.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import time

from framecleave.config import Config
from framecleave.detector import analyze, baseline_cuts, detect
from framecleave.diagnostics import diagnostics
from framecleave.evaluate import match_cuts
from framecleave.media import probe
from framecleave.storage import atomic_json


def benchmark(inputs: list[Path], annotations_dir: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    labels = [json.loads(path.read_text()) for path in sorted(annotations_dir.glob('*.json'))]
    by_hash = {label['source_sha256']: label for label in labels if 'cuts' in label}
    results = []
    seen = set()
    for path in inputs:
        info = probe(path)
        label = by_hash.get(info.sha256)
        if label is None:
            raise ValueError(f'No annotation with matching content SHA-256 for {path.name}')
        if info.sha256 in seen:
            raise ValueError('Duplicate input content in benchmark')
        seen.add(info.sha256)
        start = time.monotonic()
        analysis = analyze(info, Config())
        if analysis.timeline.frame_count != label['frame_count']:
            raise ValueError(f"Annotation frame-count mismatch: {label['id']}")
        boundaries = detect(info, analysis, Config())
        seconds = time.monotonic() - start
        predictions = {name: baseline_cuts(analysis.metrics, name) for name in ['pixel', 'histogram', 'adaptive']}
        predictions['temporal'] = [b['frame'] for b in boundaries if b['decision'] == 'cut']
        predictions['temporal+review'] = [b['frame'] for b in boundaries]
        duration = float((analysis.timeline.end_pts - analysis.timeline.pts[0]) * info.time_base)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_bytes = int(usage.ru_maxrss * (1 if platform.system() == 'Darwin' else 1024))
        results.append({'id': label['id'], 'split': label['split'], 'source_sha256': info.sha256,
                        'label_provenance': label.get('provenance'), 'frame_count': analysis.timeline.frame_count,
                        'analysis_plus_detection_seconds_excluding_probe': seconds,
                        'python_process_lifetime_peak_rss_bytes_excludes_ffmpeg': rss_bytes,
                        'predictions': predictions,
                        'metrics': {name: match_cuts(cuts, label['cuts'], duration_seconds=duration)
                                    for name, cuts in predictions.items()}, 'evidence': boundaries})
    result = {'config': Config().to_dict(), 'environment': diagnostics(), 'results': results,
              'note': 'Zero-frame tolerance; temporal+review is a review workload, NOT automatic-cut recall.'}
    # Sanitize system executable paths while retaining version/build information.
    for name in ['ffmpeg', 'ffprobe']:
        if result['environment'][name]:
            result['environment'][name].pop('path', None)
    atomic_json(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    benchmark(args.inputs, args.annotations, args.output)
