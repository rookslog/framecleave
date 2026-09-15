import pytest

def test_exact_matching_exposes_one_frame_error():
    from framecleave.evaluate import match_cuts
    r = match_cuts([10, 20, 21], [10, 22], tolerance=0, duration_seconds=3600)
    assert (r['tp'], r['fp'], r['fn']) == (1, 2, 1)
    assert r['false_positive_frames'] == [20, 21]
    assert r['false_negative_frames'] == [22]

def test_matching_is_one_to_one():
    from framecleave.evaluate import match_cuts
    r = match_cuts([10, 11], [11], tolerance=1, duration_seconds=60)
    assert (r['tp'], r['fp'], r['fn']) == (1, 1, 0)
    assert r['offsets_frames'] == [0]

def test_empty_reference_does_not_hide_false_positives():
    from framecleave.evaluate import match_cuts
    r = match_cuts([7], [], tolerance=0, duration_seconds=10)
    assert r['fp'] == 1
    assert r['precision'] == 0
    assert r['recall'] is None
