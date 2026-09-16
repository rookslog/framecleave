from fractions import Fraction
import pytest


def make_timeline():
    from framecleave.model import Timeline
    return Timeline([1000, 1033, 1067, 1120], [33, 34, 53, 40], [0], Fraction(1, 1000))


def test_vfr_half_open_partition_uses_actual_pts():
    t = make_timeline()
    scenes = t.scenes([2])
    assert [(s['start_frame'], s['end_frame']) for s in scenes] == [(0, 2), (2, 4)]
    assert scenes[0]['start_pts'] == 1000
    assert scenes[0]['end_pts'] == 1067
    assert scenes[1]['end_pts'] == 1160
    assert sum(s['frame_count'] for s in scenes) == 4
    assert scenes[1]['duration_rational'] == '93/1000'


@pytest.mark.parametrize('cuts', [[0], [4], [2, 2], [3, 1], [-1], [True]])
def test_invalid_cuts_rejected(cuts):
    with pytest.raises(ValueError):
        make_timeline().scenes(cuts)


def test_bad_pts_rejected():
    from framecleave.model import Timeline
    with pytest.raises(ValueError):
        Timeline([0, 0], [1, 1], [0], Fraction(1, 1000))


def test_last_frame_duration_is_not_average_rate():
    t = make_timeline()
    assert t.end_pts == 1160
    assert t.duration == Fraction(4, 25)


def test_timeline_roundtrip():
    from framecleave.model import Timeline
    t = make_timeline()
    assert Timeline.from_dict(t.to_dict()).to_dict() == t.to_dict()


def valid_index():
    t=make_timeline()
    return {'schema_version':1,'interval_semantics':'decoded-frames-half-open','timeline':t.to_dict(),
            'source':{'sha256':'a'*64,'frame_count':t.frame_count},'scenes':t.scenes([2]),
            'boundaries':[{'frame':2,'pts':1067,'decision':'cut'}]}


def test_index_rejects_boundary_partition_disagreement():
    from framecleave.model import validate_index
    index=valid_index()
    index['boundaries'][0]['frame']=1
    with pytest.raises(ValueError,match='boundar'):
        validate_index(index)


def test_index_rejects_fabricated_rational_timestamp():
    from framecleave.model import validate_index
    index=valid_index()
    index['scenes'][0]['start_time_rational']='99/1'
    with pytest.raises(ValueError,match='start_time_rational'):
        validate_index(index)


def test_index_rejects_path_traversal():
    from framecleave.model import validate_index
    index=valid_index()
    index['scenes'][0]['output_file']='../../outside.mov'
    with pytest.raises(ValueError,match='relative'):
        validate_index(index)
