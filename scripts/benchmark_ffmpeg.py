#!/usr/bin/env python3
"""Run the actual system FFmpeg scdet baseline, not a reimplementation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from framecleave.evaluate import match_cuts
from framecleave.media import probe
from framecleave.storage import atomic_json


def evaluate(inputs: list[Path], annotations: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    labels = {a['source_sha256']: a for p in annotations.glob('*.json') if 'cuts' in (a := json.loads(p.read_text()))}
    rows = []
    for path in inputs:
        info = probe(path)
        label = labels[info.sha256]
        started = time.monotonic()
        # Analyze every frame; sc_pass=0 retains ordinal numbering. Explicit 10 percent.
        result = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                                 '-xerror', '-threads', '2', '-noautorotate', '-protocol_whitelist', 'file,pipe,crypto', '-i', str(path),
                                 '-map', '0:v:0', '-an', '-sn', '-dn', '-vf',
                                 'scale=127:96,format=yuv420p,scdet=threshold=10:sc_pass=0,metadata=print:file=-',
                                 '-fps_mode', 'passthrough', '-f', 'null', '-'],
                                capture_output=True, text=True, check=True)
        n = None
        cuts = []
        frames = 0
        for line in result.stdout.splitlines():
            m = re.match(r'frame:(\d+)', line)
            if m:
                n = int(m[1])
                frames = n + 1
            elif line.startswith('lavfi.scd.time=') and n:
                cuts.append(n)
        if frames != label['frame_count']:
            raise ValueError(f"scdet frame count disagrees for {label['id']}: {frames}")
        rows.append({'id': label['id'], 'split': label['split'], 'approach': 'ffmpeg-scdet-10',
                     'wall_seconds': time.monotonic() - started, 'predictions': cuts,
                     **match_cuts(cuts, label['cuts'], duration_seconds=label['duration_seconds'])})
    atomic_json(output, rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs', nargs='+', type=Path)
    p.add_argument('--annotations', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    evaluate(a.inputs, a.annotations, a.output)
