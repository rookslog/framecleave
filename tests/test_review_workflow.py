import json

import pytest

from framecleave.config import Config
from framecleave.workflow import process_video, verify_job


def test_review_workflow_resume_and_verify_do_not_prepare_exact_caches(source_video, tmp_path, monkeypatch):
    from framecleave.export import ExportSession

    def forbidden(*args, **kwargs):
        pytest.fail('review-copy entered the exact/reference encoding path')

    monkeypatch.setattr(ExportSession, '__init__', forbidden)
    out = tmp_path / 'review'
    first = process_video(source_video, out, Config(), cuts=[7, 47], mode='review-copy')
    assert first['exported'] == 3
    index = json.loads((out / 'scene-index.json').read_text())
    assert [scene['output_file'] for scene in index['scenes']] == [
        'scenes/0001.mp4', 'scenes/0002.mp4', 'scenes/0003.mp4']
    second = process_video(source_video, out, Config(), cuts=[7, 47], mode='review-copy', resume=True)
    assert second['skipped_integrity_checked'] == 3
    assert second['skipped_verified'] == 0
    checked = verify_job(source_video, out / 'scene-index.json')
    assert checked['verification_scope'] == 'file-integrity-and-stream-inventory'
    assert checked['pixel_equality'] == 'not_applicable'
    assert checked['audio_sample_equality'] == 'not_applicable'
    assert not (out / 'scratch').exists()


@pytest.mark.parametrize('mutation', ['output', 'range', 'segmentation'])
def test_review_verification_refuses_changed_media_or_intended_ranges(source_video, tmp_path, mutation):
    out = tmp_path / 'review'
    process_video(source_video, out, Config(), cuts=[7, 47], mode='review-copy')
    if mutation == 'output':
        with (out / 'scenes/0002.mp4').open('ab') as handle:
            handle.write(b'changed')
    else:
        path = out / 'certificates/0002.json'
        certificate = json.loads(path.read_text())
        if mutation == 'range':
            certificate['source_range']['duration_rational'] = '5/3'
        else:
            certificate['segmentation_sha256'] = '0' * 64
        path.write_text(json.dumps(certificate))
    with pytest.raises(ValueError):
        verify_job(source_video, out / 'scene-index.json')


def test_internal_batch_allowance_cannot_raise_owner_budget(source_video, tmp_path):
    from test_workflow import CollectingSink

    sink = CollectingSink()
    with pytest.raises(ValueError, match='reserve'):
        process_video(source_video, tmp_path / 'refused', Config(), cuts=[7], mode='review-copy',
                      batch_temp_reserve=-1, progress=sink)
    assert not (tmp_path / 'refused').exists()
    assert [event.event for event in sink.events].count('job_failed') == 1


def test_job_cleanup_failure_emits_failure_instead_of_success(source_video, tmp_path, monkeypatch):
    from test_workflow import CollectingSink

    sink = CollectingSink()

    def fail_cleanup(*args):
        raise OSError('injected cleanup failure')

    monkeypatch.setattr('framecleave.workflow.JobLog.__exit__', fail_cleanup)
    with pytest.raises(OSError, match='cleanup failure'):
        process_video(source_video, tmp_path / 'cleanup', Config(), cuts=[7], dry_run=True,
                      mode='review-copy', progress=sink)
    names = [event.event for event in sink.events]
    assert names.count('job_failed') == 1
    assert 'job_finished' not in names
