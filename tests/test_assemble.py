import json

import pytest

from framecleave.config import Config
from framecleave.media import MediaError, probe, run
from framecleave.workflow import process_video
from test_review_copy import review_source as review_source


def test_assemble_selected_copies_once_without_originals(review_source, tmp_path):
    from framecleave.assemble import assemble
    from test_workflow import CollectingSink

    job = tmp_path / 'review'
    process_video(review_source, job, Config(threads=1), cuts=[7, 47], mode='review-copy')
    index_path = job / 'scene-index.json'
    index = json.loads(index_path.read_text())
    index['source']['path'] = '/missing/original.mkv'
    index_path.write_text(json.dumps(index))
    target = tmp_path / 'selected.mp4'
    progress = CollectingSink()
    result = assemble([index_path], [(1, 1), (1, 3)], target, crf=18, threads=1, progress=progress)
    assert 'assembly_progress' in [event.event for event in progress.events]
    assert result['selected_scene_count'] == 2
    assert result['video_encodes'] == 1
    assert result['audio_codec'] == 'aac'
    output = probe(target)
    count = json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(target)]))
    assert int(count['streams'][0]['nb_read_frames']) == 50
    assert output.video['codec_name'] in {'h264', 'hevc'}
    assert output.audio[0]['codec_name'] == 'aac'
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'])
    assert not list(tmp_path.glob('*.partial'))
    assert not any(p.suffix in {'.wav', '.f32le', '.s16le'} for p in tmp_path.rglob('*'))


def test_assemble_refuses_publication_when_selected_clip_changes(source_video, tmp_path, monkeypatch):
    import framecleave.assemble as assemble_module

    job = tmp_path / 'review'
    process_video(source_video, job, Config(threads=1), cuts=[7, 47], mode='review-copy')
    index = json.loads((job / 'scene-index.json').read_text())
    clip = job / index['scenes'][0]['output_file']
    target = tmp_path / 'final.mp4'
    real_run_limited = assemble_module.run_limited
    calls = {'count': 0}

    def mutate_after_encode(command, partial, limit, **kwargs):
        result = real_run_limited(command, partial, limit, **kwargs)
        calls['count'] += 1
        if calls['count'] == 1:
            clip.write_bytes(clip.read_bytes() + b'\x00')
        return result

    monkeypatch.setattr(assemble_module, 'run_limited', mutate_after_encode)
    with pytest.raises(ValueError, match='changed during assembly'):
        assemble_module.assemble([job / 'scene-index.json'], [(1, 1)], target, threads=1)
    assert not target.exists()
    assert not (tmp_path / 'final.mp4.assembly.json').exists()
    assert not list(tmp_path.glob('*.partial'))


def test_assemble_refuses_rotated_selected_clip(source_video, tmp_path):
    from framecleave.assemble import assemble
    from framecleave.media import PreservationError

    rotated = tmp_path / 'rotated.mp4'
    run(['ffmpeg', '-v', 'error', '-display_rotation', '90', '-i', str(source_video), '-c', 'copy', str(rotated)])
    job = tmp_path / 'review'
    process_video(rotated, job, Config(threads=1), cuts=[7, 47], mode='review-copy')
    target = tmp_path / 'final.mp4'
    with pytest.raises(PreservationError, match='rotation'):
        assemble([job / 'scene-index.json'], [(1, 1)], target, threads=1)
    assert not target.exists()
    assert not (tmp_path / 'final.mp4.assembly.json').exists()


def test_assemble_manifest_publication_does_not_clobber_concurrent_sidecar(source_video, tmp_path, monkeypatch):
    import framecleave.assemble as assemble_module

    job = tmp_path / 'review'
    process_video(source_video, job, Config(threads=1), cuts=[7, 47], mode='review-copy')
    target = tmp_path / 'final.mp4'
    manifest = tmp_path / 'final.mp4.assembly.json'
    real_run_limited = assemble_module.run_limited
    calls = {'count': 0}

    def create_sidecar(command, partial, limit, **kwargs):
        result = real_run_limited(command, partial, limit, **kwargs)
        calls['count'] += 1
        if calls['count'] == 2:
            manifest.write_text('concurrent owner')
        return result

    monkeypatch.setattr(assemble_module, 'run_limited', create_sidecar)
    with pytest.raises(ValueError, match='published'):
        assemble_module.assemble([job / 'scene-index.json'], [(1, 1)], target, threads=1)
    assert manifest.read_text() == 'concurrent owner'
    assert target.exists()


def test_assemble_normalizes_nonzero_container_start_time(tmp_path):
    from framecleave.assemble import assemble

    source = tmp_path / 'offset.mp4'
    run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
         'testsrc2=size=160x120:rate=30:duration=2', '-c:v', 'libx264',
         '-threads', '1', '-output_ts_offset', '5', str(source)])
    job = tmp_path / 'review'
    process_video(source, job, Config(threads=1), cuts=[], mode='review-copy')
    target = tmp_path / 'assembled.mp4'

    assemble([job / 'scene-index.json'], [(1, 1)], target, threads=1)

    count = json.loads(run(['ffprobe', '-v', 'error', '-count_frames',
        '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames',
        '-of', 'json', str(target)]))
    assert int(count['streams'][0]['nb_read_frames']) == 60


def test_assemble_budget_failure_preserves_copies(source_video, tmp_path):
    from framecleave.assemble import assemble

    job = tmp_path / 'review'
    process_video(source_video, job, Config(), cuts=[7, 47], mode='review-copy')
    target = tmp_path / 'final.mp4'
    with pytest.raises(MediaError, match='budget'):
        assemble([job / 'scene-index.json'], [(1, 2)], target, max_temp_bytes=128)
    assert not target.exists()
    assert not list(tmp_path.glob('*.partial'))
    assert len(list((job / 'scenes').glob('*.mp4'))) == 3


def test_assemble_refuses_overwrite_and_invalid_selection(source_video, tmp_path):
    from framecleave.assemble import assemble

    job = tmp_path / 'review'
    process_video(source_video, job, Config(), cuts=[7, 47], mode='review-copy')
    target = tmp_path / 'final.mp4'
    target.write_bytes(b'unowned')
    with pytest.raises(FileExistsError):
        assemble([job / 'scene-index.json'], [(1, 1)], target)
    assert target.read_bytes() == b'unowned'
    with pytest.raises(ValueError):
        assemble([job / 'scene-index.json'], [(1, 99)], tmp_path / 'bad.mp4')


def test_assemble_refuses_frame_level_hdr_metadata(source_video, tmp_path, monkeypatch):
    import framecleave.assemble as assemble_module
    from framecleave.media import PreservationError

    job = tmp_path / 'review'
    process_video(source_video, job, Config(), cuts=[], mode='review-copy')

    def refuse(*args, **kwargs):
        raise PreservationError('HDR side data at source frame 20 is not supported')

    monkeypatch.setattr(assemble_module, 'audit_frame_metadata', refuse, raising=False)
    with pytest.raises(PreservationError, match='HDR side data'):
        assemble_module.assemble([job / 'scene-index.json'], [(1, 1)], tmp_path / 'final.mp4')
    assert not (tmp_path / 'final.mp4').exists()


def test_assemble_preserves_distinct_delayed_audio_onsets(tmp_path):
    from framecleave.assemble import assemble
    import numpy as np

    source = tmp_path / 'delayed.mp4'
    run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=30:duration=2',
         '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=44100:duration=2',
         '-f', 'lavfi', '-i', 'sine=frequency=800:sample_rate=48000:duration=1.75',
         '-map', '0:v', '-map', '1:a', '-map', '2:a', '-filter:a:1', 'asetpts=PTS+0.25/TB',
         '-c:v', 'libx264', '-threads', '1', '-crf', '19', '-c:a', 'aac', str(source)])
    job = tmp_path / 'review'
    process_video(source, job, Config(threads=1), cuts=[], mode='review-copy')
    output = tmp_path / 'delayed-final.mp4'
    assemble([job / 'scene-index.json'], [(1, 1)], output, threads=1)
    decoded = []
    for track in [0, 1]:
        decoded.append(np.frombuffer(run(['ffmpeg', '-v', 'error', '-i', str(output), '-map', f'0:a:{track}',
            '-af', 'aresample=async=1:first_pts=0', '-f', 'f32le', '-']), dtype=np.float32))
    assert np.max(np.abs(decoded[0][:8820])) > 0.01
    assert np.max(np.abs(decoded[1][:9600])) < 0.002
    assert np.max(np.abs(decoded[1][14400:19200])) > 0.01


def test_failed_assembly_can_retry_without_deleting_diagnostics(source_video, tmp_path):
    from framecleave.assemble import assemble

    job = tmp_path / 'review'
    process_video(source_video, job, Config(), cuts=[7, 47], mode='review-copy')
    target = tmp_path / 'retry.mp4'
    with pytest.raises(MediaError):
        assemble([job / 'scene-index.json'], [(1, 2)], target, max_temp_bytes=128)
    assert len(list(tmp_path.glob('retry.mp4.diagnostics-*.log'))) == 1
    result = assemble([job / 'scene-index.json'], [(1, 2)], target)
    assert result['decode_success'] is True
    assert len(list(tmp_path.glob('retry.mp4.diagnostics-*.log'))) == 2
