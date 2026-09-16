import json
import pytest


def test_dry_run_has_index_report_and_no_clips(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    from framecleave.model import read_index
    out = tmp_path / 'review'
    result = process_video(source_video, out, Config(), dry_run=True, cuts=[7, 47])
    assert result['status'] == 'inspected'
    index = read_index(out / 'scene-index.json')
    assert [s['start_frame'] for s in index['scenes']] == [0, 7, 47]
    assert (out / 'report.html').is_file()
    assert len(list((out / 'thumbnails').glob('*.jpg'))) > 3
    assert not (out / 'scenes').exists()
    assert not (out / '.lock').exists()


def test_split_resume_and_tamper_detection(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'résumé job'
    first = process_video(source_video, out, Config(), cuts=[7,47])
    assert first['status'] == 'complete'
    assert first['exported'] == 3
    second = process_video(source_video, out, Config(), cuts=[7,47], resume=True)
    assert second['skipped_verified'] == 3
    index = json.loads((out / 'scene-index.json').read_text())
    target = out / index['scenes'][1]['output_file']
    with target.open('ab') as handle:
        handle.write(b'corruption')
    with pytest.raises(ValueError, match='digest'):
        process_video(source_video, out, Config(), cuts=[7,47], resume=True)


def test_resume_rejects_changed_config(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'out'
    process_video(source_video, out, Config(), dry_run=True, cuts=[7])
    with pytest.raises(ValueError, match='configuration'):
        process_video(source_video, out, Config(threads=1), dry_run=True, cuts=[7], resume=True)


def test_inspection_can_be_promoted_to_export(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'out'
    process_video(source_video, out, Config(), dry_run=True, cuts=[7])
    result = process_video(source_video, out, Config(), resume=True, cuts=[7])
    assert result['exported'] == 2
