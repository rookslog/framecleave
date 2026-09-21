import json

import pytest

from framecleave.config import Config
from framecleave.media import MediaError, probe, run, sha256_file
from framecleave.workflow import process_video
from test_review_copy import review_source as review_source


def _two_track_source(path, first_language, second_language):
    run(['ffmpeg', '-v', 'error', '-y',
         '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=30:duration=1',
         '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=1',
         '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=44100:duration=1',
         '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac',
         '-metadata:s:a:0', f'language={first_language}',
         '-metadata:s:a:1', f'language={second_language}', str(path)])


def test_assemble_selected_copies_once_without_originals(review_source, tmp_path, monkeypatch):
    import framecleave.assemble as assemble_module
    from test_workflow import CollectingSink

    job = tmp_path / 'review'
    process_video(review_source, job, Config(threads=1), cuts=[7, 47], mode='review-copy')
    index_path = job / 'scene-index.json'
    index = json.loads(index_path.read_text())
    index['source']['path'] = '/missing/original.mkv'
    index_path.write_text(json.dumps(index))
    target = tmp_path / 'selected.mp4'
    progress = CollectingSink()
    commands = []
    real_run_limited = assemble_module.run_limited

    def capture(command, partial, limit, **kwargs):
        if kwargs.get('label') == 'final assembly':
            commands.append(list(command))
        return real_run_limited(command, partial, limit, **kwargs)

    monkeypatch.setattr(assemble_module, 'run_limited', capture)
    result = assemble_module.assemble(
        [index_path], [(1, 1), (1, 3)], target, crf=18, threads=1, progress=progress)
    assert len(commands) == 1
    assert commands[0][commands[0].index('-enc_time_base') + 1] == '1:1000000'
    assert commands[0][commands[0].index('-bsf:v') + 1].startswith('setts=duration=')
    assert 'assembly_progress' in [event.event for event in progress.events]
    assert result['selected_scene_count'] == 2
    assert result['video_encodes'] == 1
    assert result['audio_codec'] == 'aac'
    assert result['requested_frames'] == 50
    assert result['verified_output_frames'] == 50
    from fractions import Fraction
    assert Fraction(result['output_duration_rational']) >= (
        Fraction(result['requested_duration_rational']) - Fraction(result['coverage_tolerance_rational']))
    output = probe(target)
    assert Fraction(result['coverage_tolerance_rational']) >= output.time_base * result['selected_scene_count']
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


def test_assemble_refuses_selected_clips_with_different_chroma_location(tmp_path):
    from framecleave.assemble import assemble

    left = tmp_path / 'left.mp4'
    center = tmp_path / 'center.mp4'
    base = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'testsrc2=size=160x120:rate=30:duration=1', '-c:v', 'libx264', '-threads', '1', '-x264-params']
    run([*base, 'chromaloc=0', str(left)])
    run([*base, 'chromaloc=1', str(center)])
    assert probe(left).video['chroma_location'] == 'left'
    assert probe(center).video['chroma_location'] == 'center'
    jobs = []
    for number, source in enumerate([left, center], 1):
        job = tmp_path / f'job{number}'
        process_video(source, job, Config(threads=1), cuts=[], mode='review-copy')
        jobs.append(job / 'scene-index.json')
    target = tmp_path / 'final.mp4'
    with pytest.raises(ValueError, match='differ'):
        assemble(jobs, [(1, 1), (2, 1)], target, threads=1)
    assert not target.exists()
    assert not (tmp_path / 'final.mp4.assembly.json').exists()


def test_assemble_refuses_truncated_selected_clip_before_publication(source_video, tmp_path):
    from framecleave.assemble import assemble

    job = tmp_path / 'review'
    process_video(source_video, job, Config(threads=1), cuts=[7, 47], mode='review-copy')
    index_path = job / 'scene-index.json'
    index = json.loads(index_path.read_text())
    scene = index['scenes'][1]
    clip = job / scene['output_file']
    truncated = clip.with_name('truncated.mp4')
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(clip), '-frames:v', '5', '-an',
         '-c:v', 'libx264', '-threads', '1', str(truncated)])
    truncated.replace(clip)
    certificate_path = job / scene['export']
    certificate = json.loads(certificate_path.read_text())
    certificate['output_sha256'] = sha256_file(clip)
    certificate_path.write_text(json.dumps(certificate))
    state_path = job / 'state.json'
    state = json.loads(state_path.read_text())
    record = state['completed'][str(scene['number'])]
    record['sha256'] = certificate['output_sha256']
    record['certificate_sha256'] = sha256_file(certificate_path)
    state_path.write_text(json.dumps(state))
    target = tmp_path / 'final.mp4'
    with pytest.raises(ValueError, match='requested interval'):
        assemble([index_path], [(1, 2)], target, threads=1)
    assert not target.exists()
    assert not (tmp_path / 'final.mp4.assembly.json').exists()
    assert not list(tmp_path.glob('*.partial'))


def test_assemble_matches_audio_stream_identity_and_order(tmp_path):
    from framecleave.assemble import assemble

    first = tmp_path / 'first.mp4'
    same = tmp_path / 'same.mp4'
    reversed_ = tmp_path / 'reversed.mp4'
    _two_track_source(first, 'eng', 'fra')
    _two_track_source(same, 'eng', 'fra')
    _two_track_source(reversed_, 'fra', 'eng')
    jobs = []
    for number, source in enumerate([first, same, reversed_], 1):
        job = tmp_path / f'job{number}'
        process_video(source, job, Config(threads=1), cuts=[], mode='review-copy')
        jobs.append(job / 'scene-index.json')
    accepted = tmp_path / 'accepted.mp4'
    result = assemble([jobs[0], jobs[1]], [(1, 1), (2, 1)], accepted, threads=1)
    assert result['selected_scene_count'] == 2
    assert accepted.exists()
    accepted_audio = probe(accepted).audio
    assert [stream.get('tags', {}).get('language') for stream in accepted_audio] == ['eng', 'fra']
    expected_audio = probe(first).audio
    assert [[name for name, enabled in stream.get('disposition', {}).items() if enabled]
            for stream in accepted_audio] == [
                [name for name, enabled in stream.get('disposition', {}).items() if enabled]
                for stream in expected_audio]
    refused = tmp_path / 'refused.mp4'
    with pytest.raises(ValueError, match='identity'):
        assemble([jobs[0], jobs[2]], [(1, 1), (2, 1)], refused, threads=1)
    assert not refused.exists()
    assert not (tmp_path / 'refused.mp4.assembly.json').exists()


def test_assemble_refuses_media_and_certificate_substituted_without_state_update(source_video, tmp_path):
    from framecleave.assemble import assemble

    job = tmp_path / 'review'
    process_video(source_video, job, Config(threads=1), cuts=[7], mode='review-copy')
    index = json.loads((job / 'scene-index.json').read_text())
    scene = index['scenes'][0]
    clip = job / scene['output_file']
    clip.write_bytes(clip.read_bytes() + b'substituted')
    certificate_path = job / scene['export']
    certificate = json.loads(certificate_path.read_text())
    certificate['output_sha256'] = sha256_file(clip)
    certificate_path.write_text(json.dumps(certificate))
    with pytest.raises(ValueError, match='completed state'):
        assemble([job / 'scene-index.json'], [(1, 1)], tmp_path / 'final.mp4', threads=1)


def _colored_source(path):
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=30:duration=1',
         '-vf', 'setparams=color_primaries=bt470bg:color_trc=smpte170m:colorspace=bt470bg:range=pc',
         '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p',
         '-chroma_sample_location', 'center', str(path)])


def test_assemble_preserves_validated_color_metadata(tmp_path):
    from framecleave.assemble import assemble

    source = tmp_path / 'colored.mp4'
    _colored_source(source)
    expected = probe(source).video
    assert expected['color_transfer'] == 'smpte170m'
    assert expected['color_primaries'] == 'bt470bg'
    job = tmp_path / 'review'
    process_video(source, job, Config(threads=1), cuts=[], mode='review-copy')
    target = tmp_path / 'final.mp4'
    assemble([job / 'scene-index.json'], [(1, 1)], target, threads=1)
    output = probe(target).video
    for field in ['color_range', 'color_space', 'color_transfer', 'color_primaries', 'chroma_location']:
        assert output[field] == expected[field]


def test_assemble_refuses_output_color_mismatch(tmp_path, monkeypatch):
    import framecleave.assemble as assemble_module
    from framecleave.media import PreservationError

    source = tmp_path / 'colored.mp4'
    _colored_source(source)
    job = tmp_path / 'review'
    process_video(source, job, Config(threads=1), cuts=[], mode='review-copy')
    real_probe = assemble_module.probe

    def mismatched_probe(path, **kwargs):
        info = real_probe(path, **kwargs)
        if str(path).endswith('.partial'):
            info.video['color_primaries'] = 'bt2020'
        return info

    monkeypatch.setattr(assemble_module, 'probe', mismatched_probe)
    target = tmp_path / 'final.mp4'
    with pytest.raises(PreservationError, match='color_primaries'):
        assemble_module.assemble([job / 'scene-index.json'], [(1, 1)], target, threads=1)
    assert not target.exists()
    assert not (tmp_path / 'final.mp4.assembly.json').exists()


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
