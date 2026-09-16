import numpy as np
import cv2


def test_flat_frames_have_zero_structural_change():
    from framecleave.detector import frame_metrics
    a = np.full((96, 128, 3), 100, np.uint8)
    assert frame_metrics(a, a)[3] == 0


def test_spatial_change_survives_equal_colour_histogram():
    from framecleave.detector import frame_metrics
    rng = np.random.default_rng(41)
    a = rng.integers(0, 255, (96, 128, 3), dtype=np.uint8)
    b = a[::-1].copy()
    scores = frame_metrics(a, b)
    assert scores[2] < 1e-5
    assert scores[3] > .9
    assert scores[5] > 20


def test_update_context_is_not_diluted_by_duplicate_frames():
    from framecleave.detector import update_ratios
    values = np.array([0, 10, 0, 0, 10, 0, 0, 10, 0, 0, 60, 0, 0, 10, 0, 0, 10], float)
    ratio, _ = update_ratios(values, context=4)
    assert ratio[7] == 1
    assert ratio[10] == 6


def test_temporal_detects_equal_histogram_hard_cut():
    from framecleave.detector import decide
    rng = np.random.default_rng(321)
    a = cv2.GaussianBlur(rng.integers(0, 255, (96, 128, 3), dtype=np.uint8), (5, 5), 0)
    b = a[::-1, ::-1].copy()
    # A rotation has an actual continuous explanation and must not be our positive fixture.
    b = np.roll(b, 30, axis=1)
    b[:, :64] = np.roll(b[:, :64], 25, axis=0)
    evidence = dict(mad=25., hist=0., ratio=25., block_ratio=25., block_peak=40., corr=.1,
                    within=.99, cross=.1, track=0., inliers=0., warp_residual=1.,
                    sift_inliers=0, sift_cov=0., flash_return=False)
    assert decide(evidence)[0] == "cut"


def test_photometric_change_with_retained_structure_is_not_a_cut():
    from framecleave.detector import decide
    e = dict(mad=40., hist=.8, ratio=12., block_ratio=12., block_peak=50., corr=.999,
             within=.99, cross=.999, track=.9, inliers=.8, warp_residual=.05,
             sift_inliers=15, sift_cov=.2, flash_return=False)
    assert decide(e)[0] == "continuity"


def test_rotational_correspondence_is_not_discarded():
    from framecleave.detector import decide
    e = dict(mad=50., hist=.7, ratio=10., block_ratio=10., block_peak=80., corr=.1,
             within=.9, cross=.1, track=0., inliers=0., warp_residual=1.,
             sift_inliers=25, sift_cov=.2, sift_residual=.2, flash_return=False)
    assert decide(e)[0] == "continuity"


def test_analyze_uses_decoded_pts(source_video):
    from framecleave.config import Config
    from framecleave.media import probe
    from framecleave.detector import analyze
    result = analyze(probe(source_video), Config())
    assert result.timeline.frame_count == 90
    assert result.timeline.end_pts == 46080
    assert result.metrics.shape == (90, 6)


def test_many_to_one_feature_matches_do_not_explain_continuity():
    from framecleave.detector import geometry
    rng = np.random.default_rng(742)
    patch = rng.integers(0, 255, (24, 24), dtype=np.uint8)
    a = np.full((192, 256), 100, np.uint8)
    b = a.copy()
    for y in range(20, 160, 40):
        for x in range(20, 220, 40):
            a[y:y+24, x:x+24] = patch
    b[20:44, 20:44] = patch
    evidence = geometry(cv2.cvtColor(a, cv2.COLOR_GRAY2RGB), cv2.cvtColor(b, cv2.COLOR_GRAY2RGB))
    assert evidence["sift_cov"] < .04


def test_corresponding_overlay_is_not_evidence_of_camera_continuity():
    from framecleave.detector import decide
    evidence = dict(mad=40., hist=.8, ratio=10., block_ratio=10., block_peak=50., corr=.5,
                    within=.9, cross=.2, track=0., inliers=0., warp_residual=1.,
                    sift_inliers=40, sift_cov=.9, sift_residual=1., flash_return=False)
    assert decide(evidence)[0] == "cut"
