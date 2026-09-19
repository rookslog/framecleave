"""Deferred export-plan contract draft; intentionally not an active pytest module.

Preserved from the earlier plan before the owner clarified stream-copy-first
review. Run explicitly only when that optional plan module is implemented.
"""
from copy import deepcopy
from fractions import Fraction

import pytest

from framecleave.model import Timeline


@pytest.fixture
def index():
    timeline = Timeline(list(range(100)), [1] * 100, [0, 20, 30, 70], Fraction(1, 30))
    scenes = timeline.scenes([20, 30, 70])
    scenes[1]['transition'] = {'classification': 'transition_candidate',
                               'classifier_version': 'neutral-card-evidence-v1',
                               'source_range': [20, 30], 'evidence': {}}
    return {'schema_version': 1, 'interval_semantics': 'decoded-frames-half-open',
            'source': {'sha256': 'a' * 64, 'frame_count': 100, 'path': '/private/source.mkv',
                       'streams': [{'codec_type': 'video', 'codec_name': 'h264'}]},
            'timeline': timeline.to_dict(), 'scenes': scenes,
            'boundaries': [{'frame': frame, 'pts': frame, 'decision': 'cut'} for frame in [20, 30, 70]]}


def _plan(index, decisions=None):
    from framecleave.export_plan import make_export_plan
    from framecleave.policy import resolve_policy

    return make_export_plan(index, resolve_policy('auto', source_codec='h264'), decisions=decisions,
                            approved_at='2026-09-16T00:00:00Z').to_dict()


def test_omit_preserves_every_unomitted_frame_once_and_does_not_mutate_index(index):
    from framecleave.export_plan import validate_export_plan

    original = deepcopy(index)
    plan = _plan(index, {2: 'omit'})
    validate_export_plan(plan, index)
    intervals = plan['intervals']
    assert [(interval['start_frame'], interval['end_frame']) for interval in intervals] == [(0, 20), (30, 70), (70, 100)]
    frames = [frame for interval in intervals for frame in range(interval['start_frame'], interval['end_frame'])]
    assert frames == list(range(20)) + list(range(30, 100))
    assert index == original


def test_collapse_retires_two_boundaries_but_keeps_all_frames(index):
    from framecleave.export_plan import validate_export_plan

    plan = _plan(index, {2: 'collapse'})
    validate_export_plan(plan, index)
    assert [(interval['start_frame'], interval['end_frame']) for interval in plan['intervals']] == [(0, 25), (25, 70), (70, 100)]
    assert plan['retired_boundaries'] == [20, 30]
    assert plan['omission_masks'] == []
    assert plan['boundaries'][0]['approved_mask'] == [20, 30]


@pytest.mark.parametrize('mutation', [
    lambda plan: plan.update(scene_index_sha256='0' * 64),
    lambda plan: plan.update(policy_digest='0' * 64),
    lambda plan: plan['intervals'][0].update(output_file='../outside.mov'),
    lambda plan: plan['intervals'][0].update(end_frame=0),
    lambda plan: plan['intervals'][1].update(start_frame=19),
    lambda plan: plan['intervals'][1].update(start_frame=31),
    lambda plan: plan['decisions'][0].update(action='delete'),
])
def test_validator_rejects_stale_policy_index_paths_ranges_and_decisions(index, mutation):
    from framecleave.export_plan import plan_digest, validate_export_plan

    plan = _plan(index, {2: 'omit'})
    mutation(plan)
    plan['plan_digest'] = plan_digest(plan)
    with pytest.raises(ValueError):
        validate_export_plan(plan, index)


def test_plan_digest_rejects_tampering_and_unknown_fields(index):
    from framecleave.export_plan import ExportPlan, plan_digest

    plan = _plan(index)
    plan['intervals'][0]['end_frame'] = 19
    with pytest.raises(ValueError, match='plan digest'):
        ExportPlan.from_dict(plan)
    plan['secret'] = True
    plan['plan_digest'] = plan_digest(plan)
    with pytest.raises(ValueError, match='unknown'):
        ExportPlan.from_dict(plan)


def test_analysis_digest_ignores_only_mutable_location_export_and_thumbnail_metadata(index):
    from framecleave.export_plan import scene_index_digest

    before = scene_index_digest(index)
    index['source']['path'] = '/new/location/source.mkv'
    index['scenes'][0].update(output_file='scenes/0001.mov', export='certificates/0001.json', thumbnails={'start': 'thumbnails/a.jpg'})
    assert scene_index_digest(index) == before
    index['scenes'][1]['transition']['evidence']['audio'] = 'changed'
    assert scene_index_digest(index) != before


def test_export_plan_refuses_overwrite_and_input_symlinks(index, tmp_path):
    import json
    from framecleave.export_plan import read_export_plan, write_export_plan

    target = tmp_path / 'export-plan.json'
    write_export_plan(target, _plan(index))
    with pytest.raises(FileExistsError):
        write_export_plan(target, _plan(index))
    assert json.loads(target.read_text())['schema_version'] == 1
    link = tmp_path / 'link.json'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        read_export_plan(link)
