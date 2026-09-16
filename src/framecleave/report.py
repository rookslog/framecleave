"""Local-only, script-free visual review and exact-frame thumbnails."""
from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path

import cv2

from .media import MediaError, MediaInfo, iter_video
from .model import Timeline
from .storage import atomic_bytes


def make_thumbnails(info: MediaInfo, index: dict, directory: Path, *, threads: int = 2) -> None:
    timeline = Timeline.from_dict(index['timeline'])
    selected = set()
    for scene in index['scenes']:
        selected.update([scene['start_frame'], scene['last_frame']])
        scene['thumbnails'] = {key: f"thumbnails/frame-{number:09d}.jpg" for key, number in
                               [('start', scene['start_frame']), ('end', scene['last_frame'])]}
    for boundary in index['boundaries']:
        n = boundary['frame']
        numbers = [i for i in range(n - 2, n + 2) if 0 <= i < timeline.frame_count]
        selected.update(numbers)
        boundary['thumbnails'] = [{'frame': i, 'path': f'thumbnails/frame-{i:09d}.jpg'} for i in numbers]
    scale = min(320 / info.video['width'], 240 / info.video['height'], 1)
    width, height = max(2, round(info.video['width'] * scale)), max(2, round(info.video['height'] * scale))
    for frame in iter_video(info, width=width, height=height, threads=threads, selected=sorted(selected)):
        if frame.pts != timeline.pts[frame.number]:
            raise MediaError('Thumbnail source PTS no longer matches the index')
        bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise MediaError('JPEG thumbnail encoding failed')
        atomic_bytes(directory / f'thumbnails/frame-{frame.number:09d}.jpg', encoded.tobytes())


def _safe_asset(path: str) -> str:
    p = Path(path)
    if p.is_absolute() or '..' in p.parts or ':' in path or '\\' in path:
        raise ValueError('Report assets must be relative local paths')
    return html.escape(path, quote=True)


def render_report(index: dict, directory: Path) -> None:
    escape = html.escape
    name = escape(index['source']['display_name'])
    reviews = [b for b in index['boundaries'] if b['decision'] == 'review']
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; style-src \'unsafe-inline\'">',
             f'<title>FrameCleave · {name}</title>',
             '''<style>
:root{color-scheme:dark}body{max-width:1200px;margin:40px auto;padding:0 24px;font:16px/1.5 system-ui,sans-serif;background:#141618;color:#e9ecef}
h1{font-size:28px;margin-bottom:4px}h2{margin-top:40px}p,small{color:#b3bbc4}a{color:#9ad9ec}section{background:#202429;padding:20px;border-radius:10px;margin:20px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}figure{margin:0}img{width:100%;object-fit:contain;background:#111;border-radius:4px}figcaption{font-size:13px;color:#bac2cb}
pre{overflow:auto;font-size:12px}.tag{font-size:13px;border:1px solid #6d7884;border-radius:5px;padding:3px 7px}.review{border-left:4px solid #e9b56f}.note{border-left:4px solid #79c4cf;padding-left:16px}
</style>''', '<body>', f'<h1>{name}</h1>',
             f"<p>{len(index['scenes'])} proposed scenes · {len(reviews)} unresolved review candidates · FrameCleave</p>",
             '<p class="note">This is a proposed segmentation, not a guarantee that all edits were found. '
             'Frame numbers are zero-based. Scene intervals are [start, end exclusive). '
             'Review candidates are not automatically included in the split. Thumbnails are downscaled SDR review images, not exported media.</p>',
             '<p><a href="scene-index.json">Scene index JSON</a> · <a href="scenes.csv">Scene index CSV</a></p>', '<h2>Proposed scenes</h2>']
    for scene in index['scenes']:
        parts.append(f"<section><h3>Scene {scene['number']:03d} <span class='tag'>[{scene['start_frame']}, {scene['end_frame']})</span></h3>"
                     f"<p>{escape(scene['start_relative'])} → {escape(scene['end_relative'])} · {scene['frame_count']} frames</p><div class='grid'>")
        for key in ['start', 'end']:
            asset = scene.get('thumbnails', {}).get(key)
            if asset:
                number = scene['start_frame'] if key == 'start' else scene['last_frame']
                parts.append(f'<figure><img loading="lazy" src="{_safe_asset(asset)}" alt="{key} frame {number}"><figcaption>{key.capitalize()} · frame {number}</figcaption></figure>')
        parts.append('</div></section>')
    for decision, title in [('cut', 'Accepted boundaries'), ('review', 'Needs review')]:
        parts.append(f'<h2>{title}</h2>')
        if decision == 'review':
            parts.append('<p>Not included in the proposed split. Inspect these alongside the source before exporting important material.</p>')
        for boundary in index['boundaries']:
            if boundary['decision'] != decision:
                continue
            frame = boundary['frame']
            parts.append(f'<section class="{decision}"><h3>Boundary at frame {frame}</h3><p>{escape(boundary.get("reason", ""))}</p><div class="grid">')
            for image in boundary.get('thumbnails', []):
                i = image['frame']
                label = 'before' if i < frame else 'after'
                parts.append(f'<figure><img loading="lazy" src="{_safe_asset(image["path"])}" alt="frame {i}"><figcaption>{label} · {i}</figcaption></figure>')
            parts.append('</div><details><summary>Uncalibrated detector evidence</summary><pre>')
            parts.append(escape(json.dumps(boundary.get('evidence', {}), indent=2)))
            parts.append('</pre></details></section>')
    parts.append('<footer><p>Generated locally. No scripts, remote fonts, tracking, or external image requests.</p></footer></body></html>')
    atomic_bytes(directory / 'report.html', '\n'.join(parts).encode('utf-8'))
    stream = io.StringIO(newline='')
    fields = ['number', 'start_frame', 'end_frame', 'last_frame', 'frame_count', 'start_pts', 'end_pts',
              'start_time_rational', 'end_time_rational', 'duration_rational', 'output_file']
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(index['scenes'])
    atomic_bytes(directory / 'scenes.csv', stream.getvalue().encode('utf-8'))
