"""Duplicate-aware temporal candidates with explicit photometric/geometric evidence.

There is no identity/face analysis, model download, telemetry, or confidence percentage.
The deterministic rules are an evaluated baseline, not a guarantee of editorial intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import logging
import time
from typing import Callable

import cv2
import numpy as np

from .config import Config
from .media import MediaError, MediaInfo, iter_video
from .model import Timeline

DETECTOR_VERSION = "temporal-geometry-1"
LOG = logging.getLogger(__name__)
METRIC_NAMES = ["rgb_mad", "hsv_mad", "histogram_distance", "structural_change", "luma_mad", "block_peak"]


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    aa = a - a.mean()
    bb = b - b.mean()
    norm = float(np.sqrt(np.mean(aa * aa) * np.mean(bb * bb)))
    if norm < 1e-6:
        return 1.0 if np.array_equal(a, b) else 0.0
    return float(np.clip(np.mean(aa * bb) / norm, -1, 1))


def frame_metrics(previous: np.ndarray, current: np.ndarray) -> np.ndarray:
    diff = cv2.absdiff(previous, current).astype(np.float32)
    hsv0 = cv2.cvtColor(previous, cv2.COLOR_RGB2HSV)
    hsv1 = cv2.cvtColor(current, cv2.COLOR_RGB2HSV)
    h0 = cv2.calcHist([hsv0], [0, 1], None, [24, 8], [0, 180, 0, 256])
    h1 = cv2.calcHist([hsv1], [0, 1], None, [24, 8], [0, 180, 0, 256])
    gray0 = cv2.cvtColor(previous, cv2.COLOR_RGB2GRAY)
    gray1 = cv2.cvtColor(current, cv2.COLOR_RGB2GRAY)
    return np.array([
        float(diff.mean()), float(cv2.absdiff(hsv0, hsv1).mean()),
        cv2.compareHist(h0, h1, cv2.HISTCMP_BHATTACHARYYA),
        1.0 - correlation(gray0, gray1), float(cv2.absdiff(gray0, gray1).mean()),
        float(cv2.resize(diff.mean(axis=2), (8, 6), interpolation=cv2.INTER_AREA).max()),
    ], dtype=np.float32)


def update_ratios(values: np.ndarray, *, context: int, active: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Use *visual updates*, not frame count, so held webcam frames do not dilute motion.

    Exclude one immediately neighboring update on each side from the context baseline.
    This accommodates two boundaries around a short interstitial without merging them.
    """
    if active is None:
        active = np.flatnonzero(values > .5)
    baseline = np.ones(len(values), dtype=np.float32)
    for j, number in enumerate(active):
        neighbors = np.concatenate((
            active[max(0, j - context):max(0, j - 1)],
            active[j + 2:j + context + 1],
        ))
        if len(neighbors):
            baseline[number] = max(1.0, float(np.quantile(values[neighbors], .75)))
    return values / baseline, baseline


@dataclass
class Analysis:
    timeline: Timeline
    metrics: np.ndarray
    width: int
    height: int
    wall_seconds: float
    timing_class: str


def analyze(info: MediaInfo, config: Config, progress: Callable[[int], None] | None = None) -> Analysis:
    cv2.setNumThreads(1)
    scale = min(config.analysis_width / info.video["width"], config.analysis_height / info.video["height"])
    width = max(2, round(info.video["width"] * scale))
    height = max(2, round(info.video["height"] * scale))
    pts, durations, keys, metrics = [], [], [], []
    previous = None
    start = time.monotonic()
    for frame in iter_video(info, width=width, height=height, threads=config.threads):
        pts.append(frame.pts)
        durations.append(frame.duration)
        if frame.keyframe:
            keys.append(frame.number)
        metrics.append(np.zeros(6, np.float32) if previous is None else frame_metrics(previous, frame.image))
        previous = frame.image
        if progress and frame.number % 1000 == 0:
            progress(frame.number)
    if durations[-1] <= 0:
        # Only an exact stream endpoint is admissible; do not guess from nominal FPS.
        duration_ts = info.video.get("duration_ts")
        start_pts = info.video.get("start_pts")
        if type(duration_ts) is int and type(start_pts) is int and start_pts + duration_ts > pts[-1]:
            durations[-1] = start_pts + duration_ts - pts[-1]
        else:
            raise MediaError("Last frame has no usable duration or exact stream endpoint")
    # The displayed interval for a frame runs until the next decoded presentation time.
    durations[:-1] = [b - a for a, b in zip(pts, pts[1:])]
    timeline = Timeline(pts, durations, keys, info.time_base)
    timing = "variable-or-irregular"
    rate_text = info.video.get("avg_frame_rate", "0/1")
    try:
        rate = Fraction(rate_text)
        if rate > 0 and all(abs((p - pts[0]) * info.time_base - Fraction(i, 1) / rate) <= info.time_base for i, p in enumerate(pts)):
            timing = "constant-rate-with-container-quantization"
    except (ValueError, ZeroDivisionError):
        pass
    return Analysis(timeline, np.asarray(metrics, np.float32), width, height, time.monotonic() - start, timing)


def geometry(a: np.ndarray, b: np.ndarray) -> dict:
    """Independent local tracking and rotation-tolerant feature correspondences."""
    cv2.setRNGSeed(0)
    a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
    result = dict(corr=correlation(a, b), track=0.0, inliers=0.0, warp_residual=1.0,
                  sift_inliers=0, sift_cov=0.0, sift_residual=1.0)
    points = cv2.goodFeaturesToTrack(a, 160, .015, 5)
    if points is not None and len(points) >= 5:
        forward, status, _ = cv2.calcOpticalFlowPyrLK(a, b, points, None, winSize=(21, 21), maxLevel=3)
        backward, status_back, _ = cv2.calcOpticalFlowPyrLK(b, a, forward, None, winSize=(21, 21), maxLevel=3)
        valid = (status.ravel() == 1) & (status_back.ravel() == 1)
        valid &= np.linalg.norm((points - backward).reshape(-1, 2), axis=1) < 1.5
        valid &= (forward[:, 0, 0] >= 0) & (forward[:, 0, 0] < a.shape[1])
        valid &= (forward[:, 0, 1] >= 0) & (forward[:, 0, 1] < a.shape[0])
        result["track"] = float(valid.mean())
        if int(valid.sum()) >= 5:
            matrix, mask = cv2.estimateAffinePartial2D(points[valid], forward[valid], method=cv2.RANSAC,
                                                     ransacReprojThreshold=2, maxIters=1000)
            if matrix is not None and .2 <= float(np.linalg.norm(matrix[:, 0])) <= 5:
                result["inliers"] = float(mask.sum() / len(points))
                warped = cv2.warpAffine(a.astype(np.float32), matrix, (a.shape[1], a.shape[0]))
                overlap = cv2.warpAffine(np.ones(a.shape, np.uint8), matrix, (a.shape[1], a.shape[0])) > 0
                if float(overlap.mean()) > .25:
                    result["warp_residual"] = float(np.sqrt(max(0, 2 * (1 - correlation(warped[overlap], b[overlap])))))
    # Pyramidal flow cannot explain arbitrarily large rotations; SIFT is a separate cue.
    sift = cv2.SIFT_create(nfeatures=400, contrastThreshold=.02, edgeThreshold=15)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is not None and db is not None and min(len(da), len(db)) >= 2:
        matcher = cv2.BFMatcher()
        reverse = {m.queryIdx: m.trainIdx for m, n in matcher.knnMatch(db, da, k=2)
                   if m.distance < .72 * n.distance}
        matches = [m for m, n in matcher.knnMatch(da, db, k=2)
                   if m.distance < .72 * n.distance and reverse.get(m.trainIdx) == m.queryIdx]
        if len(matches) >= 3:
            x = np.array([ka[m.queryIdx].pt for m in matches], np.float32)
            y = np.array([kb[m.trainIdx].pt for m in matches], np.float32)
            matrix, mask = cv2.estimateAffinePartial2D(x, y, method=cv2.RANSAC, ransacReprojThreshold=2, maxIters=2000)
            if mask is not None and matrix is not None and .2 <= float(np.linalg.norm(matrix[:, 0])) <= 5:
                count = int(mask.sum())
                result["sift_inliers"] = count
                if count >= 3:
                    source_area = cv2.contourArea(cv2.convexHull(x[mask.ravel() > 0]))
                    target_area = cv2.contourArea(cv2.convexHull(y[mask.ravel() > 0]))
                    result["sift_cov"] = float(min(source_area, target_area) / a.size)
                    warped = cv2.warpAffine(a.astype(np.float32), matrix, (a.shape[1], a.shape[0]))
                    valid = cv2.warpAffine(np.ones(a.shape, np.uint8), matrix, (a.shape[1], a.shape[0])) > 0
                    if float(valid.mean()) > .25:
                        result["sift_residual"] = float(np.sqrt(max(0, 2 * (1 - correlation(warped[valid], b[valid])))))
    return result


def decide(e: dict) -> tuple[str, str]:
    """Uncalibrated evidence rules; return decision and an auditable reason."""
    if e["flash_return"]:
        return "review", "transient-return: flash, corruption, or a very short shot is ambiguous"
    if e["corr"] > .985:
        return "continuity", "spatial structure retained despite photometric change"
    geometric = ((e["inliers"] >= .4 and e["warp_residual"] < .55) or
                 (e["sift_inliers"] >= 8 and e["sift_cov"] >= .04 and e.get("sift_residual", 1.0) < .6))
    # A persistent local rearrangement can coexist with a trackable background.
    local_break = e["block_ratio"] > 16 and e["block_peak"] > 12 and e["within"] > .98 and e["corr"] < .96
    if geometric and not local_break:
        return "continuity", "change explained by geometric correspondence"
    broken = e["track"] < .2 or local_break
    if broken and e["hist"] >= .5 and e["ratio"] >= 2:
        return "cut", "temporal discontinuity, changed distribution, weak correspondence"
    if broken and e["ratio"] >= 8 and e["corr"] < .3 and e["within"] > .85:
        return "cut", "persistent structural break, including similar-histogram changes"
    if local_break:
        return "review", "localized discontinuity: an edit and a dropped-update motion event remain ambiguous"
    if broken and ((e["hist"] >= .35 and e["ratio"] >= 2) or (e["ratio"] >= 5 and e["corr"] < .7)):
        return "review", "insufficient continuity evidence; not automatically accepted"
    return "continuity", "change not supported as a persistent discontinuity"


def baseline_cuts(metrics: np.ndarray, name: str) -> list[int]:
    """Transparent internal comparison baselines, not branded upstream implementations."""
    mad = metrics[:, 0]
    if name == "pixel":
        hit = mad >= 27
    elif name == "histogram":
        hit = metrics[:, 2] >= .5
    elif name == "adaptive":
        padded = np.pad(mad, (5, 5), mode="edge")
        mean = (np.convolve(padded, np.ones(11), mode="valid") - mad) / 10
        hit = (mad >= 8) & (mad / np.maximum(mean, 1) >= 3)
    else:
        raise ValueError(f"Unknown baseline: {name}")
    # Keep adjacent cuts; no minimum shot length is silently imposed.
    return np.flatnonzero(hit & (np.arange(len(mad)) > 0)).tolist()


def detect(info: MediaInfo, analysis: Analysis, config: Config) -> list[dict]:
    scores = analysis.metrics
    if config.detector != "temporal":
        return [{"frame": n, "pts": analysis.timeline.pts[n], "decision": "cut",
                 "reason": f"{config.detector} comparison baseline", "evidence": dict(zip(METRIC_NAMES, map(float, scores[n])))}
                for n in baseline_cuts(scores, config.detector)]
    ratio, _ = update_ratios(scores[:, 0], context=config.context_updates)
    active = np.flatnonzero((scores[:, 0] > .5) | (scores[:, 5] > 2))
    block_ratio, _ = update_ratios(scores[:, 5], context=config.context_updates, active=active)
    candidates = np.flatnonzero(
        ((scores[:, 0] >= config.min_change) | (scores[:, 5] >= 4)) &
        ((ratio >= 2) | (block_ratio >= 4) | (scores[:, 2] >= .35))
    )
    candidates = candidates[candidates > 0]
    requests: dict[int, list[tuple[int, int]]] = {}
    windows: dict[int, list[np.ndarray | None]] = {}
    end_at: dict[int, list[int]] = {}
    for number in candidates:
        n = int(number)
        j = int(np.searchsorted(active, n))
        pre = max(0, int(active[max(0, j - 3)]) - 1)
        post = int(active[min(len(active) - 1, j + 3)])
        wanted = [pre, n - 1, n, max(n, post), max(0, n - 2), min(len(scores) - 1, n + 1)]
        windows[n] = [None] * len(wanted)
        for slot, f in enumerate(wanted):
            requests.setdefault(f, []).append((n, slot))
        end_at.setdefault(max(wanted), []).append(n)
    if not requests:
        return []
    results = []
    # One bounded second pass at twice the analysis resolution. Only requested frames persist.
    last_requested = max(end_at)
    stream = iter_video(info, width=analysis.width * 2, height=analysis.height * 2,
                        threads=config.threads, selected=sorted(requests))
    try:
        for frame in stream:
            if frame.number in requests:
                for n, slot in requests[frame.number]:
                    windows[n][slot] = frame.image
            for n in end_at.get(frame.number, []):
                old, before, after, new, prev2, next1 = windows.pop(n)
                assert all(x is not None for x in (old, before, after, new, prev2, next1))
                def gray(x):
                    return cv2.cvtColor(x, cv2.COLOR_RGB2GRAY)
                e = geometry(before, after)
                e.update(mad=float(scores[n, 0]), hist=float(scores[n, 2]), ratio=float(ratio[n]),
                         block_ratio=float(block_ratio[n]), block_peak=float(scores[n, 5]),
                         within=(correlation(gray(old), gray(before)) + correlation(gray(after), gray(new))) / 2,
                         cross=correlation(gray(old), gray(new)))
                return_before = float(cv2.absdiff(before, next1).mean()) < max(2.0, e["mad"] * .1)
                return_after = float(cv2.absdiff(prev2, after).mean()) < max(2.0, e["mad"] * .1)
                e["flash_return"] = bool((return_before or return_after) and e["mad"] > 8)
                decision, reason = decide(e)
                if decision != "continuity":
                    results.append({"frame": n, "pts": analysis.timeline.pts[n], "decision": decision,
                                    "reason": reason, "evidence": e})
            if frame.number >= last_requested:
                break
    finally:
        stream.close()
    return sorted(results, key=lambda x: x["frame"])
