"""Packet-copy behavior: generated media only; no preservation fallback."""
import json
import subprocess

import pytest


@pytest.fixture(params=['h264', 'hevc'])
def review_source(request, source_video, tmp_path):
    if request.param == 'h264':
        return source_video
    target = tmp_path / 'hevc.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=160x120:rate=30:duration=3', '-f', 'lavfi', '-i',
        'sine=sample_rate=48000:duration=3', '-c:v', 'libx265', '-threads', '1',
        '-x265-params', 'pools=1:frame-threads=1:log-level=error',
        '-c:a', 'aac', str(target)], check=True, capture_output=True)
    return target


def test_review_copy_policy_binds_packet_audio_and_rejects_false_equality_claims():
    from framecleave.policy import ExportPolicy, certificate_policy, policy_digest, resolve_policy

    policy = resolve_policy('review-copy', source_codec='h264')
    assert policy.audio.codec == 'copy'
    assert policy.video.encoder is None
    assert ExportPolicy.from_dict(policy.to_dict()) == policy
    cert = {'schema_version': 2, 'policy': policy.to_dict(), 'policy_digest': policy_digest(policy),
            'video': {'all_native_pixels_equal': True}}
    with pytest.raises(ValueError, match='cannot claim'):
        certificate_policy(cert, source_codec='h264')
    cert['video'] = {'pixel_equality': 'equal'}
    with pytest.raises(ValueError, match='cannot claim'):
        certificate_policy(cert, source_codec='h264')


def packet_hashes(path):
    data = subprocess.check_output(['ffprobe', '-v', 'error', '-show_packets',
        '-show_data_hash', 'sha256', '-show_entries', 'packet=stream_index,data_hash',
        '-of', 'json', str(path)])
    return {p['data_hash'] for p in json.loads(data)['packets']}


def test_arbitrary_review_cut_copies_compressed_video_and_audio_without_encoders(review_source, tmp_path, monkeypatch):
    from framecleave.review_copy import ReviewCopySession
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(review_source)
    original_packets = packet_hashes(review_source)
    original_popen = subprocess.Popen

    def copy_only_process(command, *args, **kwargs):
        if 'ffmpeg' in ' '.join(map(str, command)):
            assert command[command.index('-c') + 1] == 'copy'
            assert not set(command) & {'-vf', '-af', '-filter_complex', '-c:v', '-c:a'}
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', copy_only_process)
    scene = timeline.scenes([7, 47])[1]
    target = tmp_path / 'review.mp4'
    with ReviewCopySession(info, timeline) as session:
        certificate = session.export(scene, target)

    assert packet_hashes(target) <= original_packets
    assert certificate['method'] == 'audiovisual-stream-copy'
    assert certificate['source_range']['start_frame'] == 7
    assert certificate['source_range']['end_frame'] == 47
    # MOV/MP4 uses exact frame ticks; this HEVC Matroska fixture uses millisecond
    # PTS (233 through 1567), so FPS arithmetic would give the wrong interval.
    assert certificate['source_range']['duration_rational'] == {
        'h264': '4/3', 'hevc': '667/500'}[info.video['codec_name']]
    assert certificate['video']['pixel_equality'] == 'not_applicable'
    assert certificate['audio'][0]['codec'] == 'aac'
    assert certificate['audio'][0]['sample_equality'] == 'not_applicable'
    assert 'frames_verified' not in certificate['video']
    assert not list(tmp_path.rglob('*.partial'))
    assert not any(p.suffix in {'.f32le', '.s16le', '.wav', '.rgb'} for p in tmp_path.rglob('*'))


def test_review_copy_has_no_encoding_fallback_on_export_failure(source_video, tmp_path, monkeypatch):
    from framecleave.review_copy import ReviewCopySession
    from framecleave.media import MediaError
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(source_video)
    # An unavailable dependency fails instead of choosing an encoding exporter.
    monkeypatch.setenv('PATH', str(tmp_path))
    with ReviewCopySession(info, timeline) as session:
        with pytest.raises((MediaError, FileNotFoundError)):
            session.export(timeline.scenes([7])[0], tmp_path / 'review.mp4')
    assert not (tmp_path / 'review.mp4').exists()
    assert not list(tmp_path.rglob('*.partial'))


def test_review_copy_budget_refuses_oversized_partial_and_preserves_original(source_video, tmp_path):
    from framecleave.review_copy import ReviewCopySession
    from framecleave.media import MediaError, sha256_file
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(source_video)
    target = tmp_path / 'review.mp4'
    with ReviewCopySession(info, timeline, max_temp_bytes=128) as session:
        with pytest.raises(MediaError):
            session.export(timeline.scenes([7, 47])[1], target)
    assert not target.exists()
    assert not list(tmp_path.glob('*.partial'))
    assert sha256_file(source_video) == info.sha256


def test_review_copy_never_clobbers_output_or_unowned_partial(source_video, tmp_path):
    from framecleave.review_copy import ReviewCopySession
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(source_video)
    target = tmp_path / 'review.mp4'
    partial = target.with_name(target.name + '.partial')
    partial.write_bytes(b'unowned')
    with ReviewCopySession(info, timeline) as session:
        with pytest.raises(FileExistsError):
            session.export(timeline.scenes([7])[0], target)
    assert partial.read_bytes() == b'unowned'


def test_review_copy_refuses_budget_above_owner_ceiling(source_video):
    from framecleave.review_copy import ReviewCopySession
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(source_video)
    with pytest.raises(ValueError, match='budget'):
        ReviewCopySession(info, timeline, max_temp_bytes=source_video.stat().st_size * 2)


def test_review_copy_preserves_exact_source_for_an_unsplit_job(source_video, tmp_path):
    from framecleave.review_copy import ReviewCopySession
    from framecleave.media import sha256_file
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(source_video)
    with ReviewCopySession(info, timeline) as session:
        result = session.export(timeline.scenes([])[0], tmp_path / 'whole.mp4')
    assert result['method'] == 'whole-file-copy'
    assert sha256_file(tmp_path / 'whole.mp4') == info.sha256
