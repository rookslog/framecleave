"""Conservative transition evidence; classification never makes editorial changes."""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from fractions import Fraction
import logging
import math
import re
import subprocess

import cv2
import numpy as np

from .media import MediaError, MediaInfo, ffmpeg_base, iter_video
from .model import Timeline

CLASSIFIER_VERSION = 'neutral-card-evidence-v1'
REVIEWABLE = frozenset({'transition_candidate', 'ambiguous'})
ACTIONS = frozenset({'keep', 'collapse', 'omit'})
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransitionAnnotation:
    classification: str
    evidence: dict
    source_range: tuple[int, int]

    def to_dict(self) -> dict:
        return {'classifier_version': CLASSIFIER_VERSION, 'classification': self.classification,
                'evidence': self.evidence, 'source_range': list(self.source_range)}


def classify_transition(frames: np.ndarray, *, source_range: tuple[int, int],
                        before: np.ndarray | None = None, after: np.ndarray | None = None,
                        audio_activity: float | None = None) -> TransitionAnnotation:
    if (not isinstance(frames, np.ndarray) or frames.dtype != np.uint8 or frames.ndim != 4
            or frames.shape[-1] != 3 or not len(frames)):
        raise ValueError('Transition evidence requires nonempty uint8 RGB frames')
    start, end = source_range
    if type(start) is not int or type(end) is not int or start < 0 or end - start != len(frames):
        raise ValueError('Transition source range must match every examined frame')
    if audio_activity is not None and (not math.isfinite(audio_activity) or audio_activity < 0):
        raise ValueError('Audio activity must be finite and nonnegative')
    evidence = {'frames_examined': len(frames), 'audio_rms_peak': audio_activity,
                'template_scope': 'generic-neutral-card-v1',
                'two_sided_context': before is not None and after is not None}
    if len(frames) >= 30:
        evidence['reason_code'] = 'not-micro-scene'
        return TransitionAnnotation('ordinary', evidence, source_range)
    images = frames.astype(np.float32)
    luma = np.stack([cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY) for frame in frames]).astype(np.float32)
    means = luma.mean(axis=(1, 2))
    neutral = images.max(axis=3) - images.min(axis=3) <= 6
    gray = neutral & (luma >= 40) & (luma <= 215)
    uniform = np.abs(luma - np.median(luma, axis=(1, 2))[:, None, None]) <= 2
    temporal = float(np.abs(np.diff(images, axis=0)).mean(axis=(1, 2, 3)).max()) if len(frames) > 1 else 0.0
    texture = float(luma.std(axis=(1, 2)).max())
    edges = max(float((cv2.Canny(frame, 50, 100) > 0).mean()) for frame in luma.astype(np.uint8))
    evidence.update(
        minimum_neutral_gray_fraction=float(gray.mean(axis=(1, 2)).min()),
        minimum_uniform_fraction=float(uniform.mean(axis=(1, 2)).min()),
        maximum_temporal_rgb_mad=temporal, luminance_mean_min=float(means.min()),
        luminance_mean_max=float(means.max()), maximum_luminance_std=texture,
        maximum_edge_fraction=edges,
    )
    near_card = evidence['minimum_neutral_gray_fraction'] >= .90
    if not near_card:
        evidence['reason_code'] = 'ordinary-visual-content'
        return TransitionAnnotation('ordinary', evidence, source_range)
    clear_card = (evidence['minimum_uniform_fraction'] >= .98 and temporal <= 1.5
                  and float(means.max() - means.min()) <= 2 and texture <= 3 and edges <= .001)
    context_breaks = []
    for context, card in [(before, images[0]), (after, images[-1])]:
        if context is not None:
            if context.shape != frames.shape[1:] or context.dtype != np.uint8:
                raise ValueError('Transition context shape/format differs from examined frames')
            context_breaks.append(float(np.abs(context.astype(np.float32) - card).mean()))
    evidence['neighbor_rgb_mad'] = context_breaks
    if not clear_card:
        reason = 'uniform-scene-with-changing-or-overlay-evidence'
    elif len(frames) == 1:
        reason = 'single-frame-flash-or-shot'
    elif audio_activity is None:
        reason = 'audio-activity-unknown'
    elif audio_activity > .0001:
        reason = 'audio-activity-present'
    elif len(context_breaks) != 2 or min(context_breaks) <= 10:
        reason = 'insufficient-two-sided-content-context'
    else:
        evidence['reason_code'] = 'stable-neutral-card-with-silent-two-sided-context'
        return TransitionAnnotation('transition_candidate', evidence, source_range)
    evidence['reason_code'] = reason
    return TransitionAnnotation('ambiguous', evidence, source_range)


def resolve_transition_decisions(scenes: list[dict], *, default: str = 'keep',
                                 overrides: list[str] | None = None) -> dict[int, str]:
    if default not in ACTIONS:
        raise ValueError('Transition action must be keep, collapse, or omit')
    decisions = {scene['number']: default for scene in scenes
                 if scene.get('transition', {}).get('classification') in REVIEWABLE}
    seen = set()
    for override in overrides or []:
        pieces = override.split('=')
        if len(pieces) != 2 or not pieces[0].isdigit() or pieces[1] not in ACTIONS:
            raise ValueError('Transition overrides must be SCENE=keep|collapse|omit')
        number = int(pieces[0])
        if number in seen:
            raise ValueError('Duplicate transition scene decision')
        if number not in decisions:
            raise ValueError('Unknown or noncandidate transition scene')
        seen.add(number)
        decisions[number] = pieces[1]
    return decisions


def _audio_activity(info: MediaInfo, start: Fraction, end: Fraction, threads: int) -> float | None:
    peak = 0.0
    for stream in info.audio:
        command = ffmpeg_base(level='info') + [
            '-nostats', '-threads', str(threads), '-copyts', '-protocol_whitelist', 'file,pipe,crypto',
            '-i', str(info.path), '-map', f"0:{stream['index']}", '-vn', '-sn', '-dn',
            '-af', f'atrim=start={float(start):.12f}:end={float(end):.12f},astats=reset=0',
            '-f', 'null', '-',
        ]
        LOG.debug('transition audio evidence command: %r', command)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        errors = deque(maxlen=20)
        observed = False
        empty = False
        try:
            assert process.stderr is not None
            for line in process.stderr:
                text = line.decode('utf-8', 'replace').rstrip()
                errors.append(text)
                match = re.search(r'RMS level dB:\s+(-?inf|nan|[-+.\d]+)', text)
                if match:
                    level = float(match[1])
                    if not math.isnan(level):
                        observed = True
                        peak = max(peak, 10 ** (level / 20))
                if re.search(r'Number of samples:\s+0(?:\D|$)', text):
                    empty = True
            if process.wait() or not (observed or empty):
                LOG.debug('Transition audio evidence unavailable: %s', '; '.join(errors))
                return None
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stderr:
                process.stderr.close()
    return peak


def annotate_transitions(info: MediaInfo, index: dict, *, threads: int = 2,
                         analysis_width: int = 128, analysis_height: int = 96) -> None:
    """Examine every micro-scene frame in one sparse decode with a bounded buffer."""
    timeline = Timeline.from_dict(index['timeline'])
    candidates = []
    selected = set()
    for scene in index['scenes']:
        source_range = (scene['start_frame'], scene['end_frame'])
        if scene['frame_count'] >= 30:
            scene['transition'] = TransitionAnnotation(
                'ordinary', {'frames_examined': 0, 'reason_code': 'not-micro-scene'}, source_range).to_dict()
            continue
        candidates.append(scene)
        selected.update(range(max(0, scene['start_frame'] - 1), min(timeline.frame_count, scene['end_frame'] + 1)))
    if not candidates:
        return
    scale = min(analysis_width / info.video['width'], analysis_height / info.video['height'], 1)
    width, height = max(2, round(info.video['width'] * scale)), max(2, round(info.video['height'] * scale))
    buffer = {}
    position = 0
    for frame in iter_video(info, width=width, height=height, threads=threads, selected=sorted(selected)):
        if frame.pts != timeline.pts[frame.number]:
            raise MediaError('Transition source PTS no longer matches the index')
        buffer[frame.number] = frame.image
        while position < len(candidates):
            scene = candidates[position]
            start, end = scene['start_frame'], scene['end_frame']
            if frame.number < min(timeline.frame_count - 1, end):
                break
            if any(number not in buffer for number in range(start, end)):
                raise MediaError('Transition evidence is missing a requested source frame')
            activity = _audio_activity(info, timeline.endpoint(start) * timeline.time_base,
                                       timeline.endpoint(end) * timeline.time_base, threads)
            annotation = classify_transition(np.stack([buffer[number] for number in range(start, end)]),
                                             source_range=(start, end), before=buffer.get(start - 1),
                                             after=buffer.get(end), audio_activity=activity)
            scene['transition'] = annotation.to_dict()
            position += 1
            retain_from = candidates[position]['start_frame'] - 1 if position < len(candidates) else frame.number + 1
            buffer = {number: image for number, image in buffer.items() if number >= retain_from}
    if position != len(candidates):
        raise MediaError('Transition evidence decode ended before all requested scenes')
