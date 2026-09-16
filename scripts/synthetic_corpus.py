#!/usr/bin/env python3
"""Generate an original, deterministic non-private adversarial detection corpus.

Annotations describe the construction, not a human's inference about an ambiguous
flash/occlusion. Outputs contain no pixels derived from the private workload.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

from framecleave.media import sha256_file


def frames_for(name: str) -> tuple[np.ndarray, list[int], str]:
    rng = np.random.default_rng(6017)
    n, h, w = 120, 120, 160
    noise = rng.integers(15, 240, (h, w, 3), dtype=np.uint8)
    texture = cv2.GaussianBlur(noise, (5, 5), 0)
    # Original geometric features make motion and local continuity observable.
    for _ in range(18):
        x, y = rng.integers(5, w - 15), rng.integers(5, h - 15)
        cv2.rectangle(texture, (x, y), (x + 10, y + 9), tuple(map(int, rng.integers(0, 256, 3))), -1)
    frames = np.repeat(texture[None, ...], n, axis=0)
    cuts: list[int] = []
    note = 'Continuous synthetic capture; zero editorial cuts.'
    if name == 'hard-cut':
        frames[60:] = 255 - texture
        cuts = [60]
    elif name == 'same-histogram-cut':
        # Exact pixel permutation, so the two shots have identical histograms.
        cells = [texture[y:y + 30, x:x + 40].copy() for y in range(0, h, 30) for x in range(0, w, 40)]
        order = rng.permutation(16)
        for j, (y, x) in enumerate((y, x) for y in range(0, h, 30) for x in range(0, w, 40)):
            frames[60:, y:y + 30, x:x + 40] = cells[order[j]]
        cuts = [60]
        note = 'A true cut to a spatial permutation with exactly the same global histogram.'
    elif name == 'local-same-framing-cut':
        frames[60:, 38:65, 60:88] = 255 - texture[38:65, 60:88]
        cuts = [60]
        note = 'A small persistent local edit with an otherwise identical background.'
    elif name == 'short-interstitial':
        frames[58:63] = 210
        frames[63:] = 255 - texture
        cuts = [58, 63]
    elif name == 'whip-pan':
        for i in range(n):
            frames[i] = cv2.warpAffine(texture, np.float32([[1, 0, 5 * i], [0, 1, 0]]), (w, h), borderMode=cv2.BORDER_WRAP)
    elif name == 'camera-shake':
        for i in range(n):
            matrix = cv2.getRotationMatrix2D((w / 2, h / 2), 24 * np.sin(i * .67), 1)
            matrix[:, 2] += [18 * np.cos(i), 12 * np.sin(i * .9)]
            frames[i] = cv2.warpAffine(texture, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
    elif name == 'exposure-step':
        frames[60:] = np.clip(texture.astype(float) * .55 + 35, 0, 255).astype(np.uint8)
    elif name == 'single-flash':
        frames[60] = 255
    elif name == 'single-black-frame':
        frames[60] = 0
    elif name == 'lens-cover':
        for i in range(45, 76):
            frames[i] = np.rint(texture * abs(i - 60) / 15).astype(np.uint8)
    elif name in ('frozen-updates', 'dropped-update'):
        for i in range(n):
            t = (i // 6) * 6 if name == 'frozen-updates' else i + (15 if i >= 60 else 0)
            frames[i] = cv2.warpAffine(texture, np.float32([[1, 0, t], [0, 1, 0]]), (w, h), borderMode=cv2.BORDER_REFLECT)
    elif name == 'webcam-noise':
        frames = np.clip(frames.astype(np.int16) + rng.normal(0, 18, frames.shape), 0, 255).astype(np.uint8)
    elif name == 'blur-step':
        frames[60:] = cv2.GaussianBlur(texture, (31, 31), 12)
    else:
        raise ValueError(name)
    return frames, cuts, note


NAMES = ['hard-cut', 'same-histogram-cut', 'local-same-framing-cut', 'short-interstitial',
         'whip-pan', 'camera-shake', 'exposure-step', 'single-flash', 'single-black-frame',
         'lens-cover', 'frozen-updates', 'dropped-update', 'webcam-noise', 'blur-step']


def generate(output: Path) -> list[dict]:
    output.mkdir(parents=True, exist_ok=False)
    annotations = []
    for name in NAMES:
        frames, cuts, note = frames_for(name)
        path = output / f'{name}.mkv'
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x120', '-r', '30', '-i', 'pipe:0',
                        '-an', '-c:v', 'ffv1', '-level', '3', '-threads', '1', str(path)],
                       input=frames.tobytes(), check=True, capture_output=True)
        annotation = {'annotation_schema': 1, 'id': f'synthetic-{name}', 'source_sha256': sha256_file(path),
                      'split': 'synthetic-post-freeze', 'frame_count': len(frames), 'cuts': cuts,
                      'provenance': 'Known construction from RNG seed 6017, independent original pixels.',
                      'notes': note, 'source_file': path.name}
        (output / f'{name}.json').write_text(json.dumps(annotation, indent=2) + '\n')
        annotations.append(annotation)
    return annotations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    generate(args.output)
