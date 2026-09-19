import subprocess

import pytest


class CollectingSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self, result=None):
        pass


def timeline_from_source(source):
    from framecleave.media import probe
    from framecleave.detector import analyze
    from framecleave.config import Config
    info = probe(source)
    return info, analyze(info, Config()).timeline


def test_non_keyframe_split_is_pixel_and_sample_exact(source_video, tmp_path):
    from framecleave.export import ExportSession
    info, timeline = timeline_from_source(source_video)
    scene = timeline.scenes([7, 47])[1]
    with ExportSession(info, timeline, tmp_path / "work") as session:
        result = session.export(scene, tmp_path / "scene.mov")
    assert result["method"] == "lossless-reencode"
    assert result["video"]["frames_verified"] == 40
    assert result["video"]["all_native_pixels_equal"]
    assert result["video"]["all_pts_equal"]
    assert result["audio"][0]["samples_verified"] == 64000
    assert result["audio"][0]["all_samples_equal"]
    assert result['schema_version'] == 2
    assert result['policy_digest']
    assert result['video']['pixel_equality'] == 'equal'
    assert result['audio'][0]['sample_equality'] == 'equal'
    assert result['attempts'][-1]['outcome'] == 'certified'


def test_rejected_attempt_is_recovered_and_certified(source_video, tmp_path, monkeypatch):
    from framecleave.export import ExportSession
    from framecleave.media import MediaError
    import framecleave.export as export_module

    info, timeline = timeline_from_source(source_video)
    scene = timeline.scenes([7, 47])[1]
    sink = CollectingSink()
    real_run = export_module.run
    calls = 0

    def fail_first(command):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MediaError('simulated bounded failure detail')
        return real_run(command)

    monkeypatch.setattr(export_module, 'run', fail_first)
    with ExportSession(info, timeline, tmp_path / 'work', progress=sink, job_id='job-1') as session:
        result = session.export(scene, tmp_path / 'scene.mov')

    assert result['method'] == 'lossless-reencode'
    assert [event.event for event in sink.events].count('attempt_rejected') == 1
    assert sink.events[-1].event == 'scene_certified'
    assert sink.events[-1].recovered is True
    assert not any(event.event == 'scene_failed' for event in sink.events)


def test_exhausted_attempts_emit_one_terminal_scene_failure(source_video, tmp_path, monkeypatch):
    from framecleave.export import ExportSession
    from framecleave.media import MediaError
    import framecleave.export as export_module

    info, timeline = timeline_from_source(source_video)
    scene = timeline.scenes([7, 47])[1]
    sink = CollectingSink()
    monkeypatch.setattr(export_module, 'run', lambda command: (_ for _ in ()).throw(MediaError('nope')))

    with ExportSession(info, timeline, tmp_path / 'work', progress=sink, job_id='job-1') as session:
        with pytest.raises(MediaError, match='No verified export'):
            session.export(scene, tmp_path / 'scene.mov')

    assert [event.event for event in sink.events].count('scene_failed') == 1
    assert sink.events[-1].event == 'scene_failed'


@pytest.mark.parametrize('mode', ['auto', 'compact'])
def test_one_frame_scene_is_not_discarded_by_mov_muxer(source_video, tmp_path, mode):
    from framecleave.export import ExportSession
    info, timeline = timeline_from_source(source_video)
    with ExportSession(info, timeline, tmp_path / "work", mode=mode) as session:
        result = session.export(timeline.scenes([7, 8])[1], tmp_path / "one.mov")
    assert result["video"]["frames_verified"] == 1
    assert result["video"]["end_time_rational"] == "1/30"


def test_copy_only_does_not_snap_a_non_keyframe(source_video, tmp_path):
    from framecleave.export import ExportSession
    from framecleave.media import PreservationError
    info, timeline = timeline_from_source(source_video)
    with ExportSession(info, timeline, tmp_path / "work", mode="copy-only") as session:
        with pytest.raises(PreservationError, match="keyframe"):
            session.export(timeline.scenes([7, 47])[1], tmp_path / "cut.mov")
    assert not (tmp_path / "cut.mov").exists()


def test_whole_source_is_copied_without_reencoding(source_video, tmp_path):
    from framecleave.export import ExportSession
    from framecleave.media import sha256_file
    info, timeline = timeline_from_source(source_video)
    with ExportSession(info, timeline, tmp_path / "work") as session:
        result = session.export(timeline.scenes([])[0], tmp_path / "whole.mp4")
    assert result["method"] == "whole-file-copy"
    assert sha256_file(tmp_path / "whole.mp4") == info.sha256


def test_export_never_overwrites_an_existing_path(source_video, tmp_path):
    from framecleave.export import ExportSession
    info, timeline = timeline_from_source(source_video)
    target = tmp_path / "keep.mov"
    target.write_bytes(b"keep me")
    with ExportSession(info, timeline, tmp_path / "work") as session:
        with pytest.raises(FileExistsError):
            session.export(timeline.scenes([7])[0], target)
    assert target.read_bytes() == b"keep me"


def test_export_session_cleans_only_its_own_scratch(source_video, tmp_path):
    from framecleave.export import ExportSession
    info, timeline = timeline_from_source(source_video)
    parent = tmp_path / 'work'
    parent.mkdir()
    (parent / 'keep.txt').write_text('not temporary')
    with ExportSession(info, timeline, parent):
        pass
    assert (parent / 'keep.txt').read_text() == 'not temporary'


@pytest.mark.parametrize('mode', ['auto', 'compact'])
def test_vfr_nonzero_pts_are_preserved_exactly(tmp_path, mode):
    from framecleave.export import ExportSession
    path = tmp_path / 'vfr.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=60:duration=2',
                    '-vf',"select='not(mod(n,3))+eq(mod(n,11),1)',setpts=PTS+5.25/TB", '-fps_mode','passthrough',
                    '-c:v','libx264','-threads','1','-g','60','-bf','3','-video_track_timescale','90000', str(path)],check=True)
    info, timeline = timeline_from_source(path)
    assert timeline.pts[0] > 0
    assert len(set(timeline.durations)) > 1
    scene = timeline.scenes([7, 27])[1]
    with ExportSession(info, timeline, tmp_path / 'work', mode=mode) as session:
        result = session.export(scene, tmp_path / 'vfr-cut.mov')
    assert result['video']['all_pts_equal']
    assert result['video']['frames_verified'] == 20
    assert result['audio'] == []


def test_intra_coded_keyframe_aligned_copy_is_verified(tmp_path):
    from framecleave.export import ExportSession
    path = tmp_path / 'intra.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=30:duration=2',
                    '-c:v','libx264','-threads','1','-g','1','-bf','0', str(path)],check=True)
    info, timeline = timeline_from_source(path)
    with ExportSession(info, timeline, tmp_path / 'work', mode='copy-only') as session:
        result = session.export(timeline.scenes([7,27])[1], tmp_path / 'copy.mov')
    assert result['method'] == 'stream-copy-video'
    assert result['video']['frames_verified'] == 20


@pytest.mark.parametrize('mode', ['auto', 'compact'])
def test_two_audio_streams_keep_distinct_sample_clocks_and_offsets(tmp_path, mode):
    from framecleave.export import ExportSession
    path = tmp_path / 'multi.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=30:duration=2',
                    '-f','lavfi','-i','sine=frequency=500:sample_rate=44100:duration=2',
                    '-f','lavfi','-i','sine=frequency=800:sample_rate=48000:duration=1.5',
                    '-map','0:v','-map','1:a','-map','2:a','-filter:a:1','asetpts=PTS+0.25/TB',
                    '-c:v','libx264','-threads','1','-g','60','-c:a','pcm_s16le',
                    '-metadata:s:a:0','language=eng','-metadata:s:a:1','language=fra',str(path)],check=True)
    info,timeline = timeline_from_source(path)
    with ExportSession(info,timeline,tmp_path/'work', mode=mode) as session:
        result=session.export(timeline.scenes([3,40])[1],tmp_path/'multi-cut.mov')
    assert len(result['audio']) == 2
    assert all(x['all_samples_equal'] for x in result['audio'])


@pytest.mark.parametrize('mode', ['auto', 'compact'])
def test_hevc_ten_bit_and_colour_are_preserved(tmp_path, mode):
    from framecleave.export import ExportSession
    path=tmp_path/'ten.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=1',
                    '-vf','format=yuv420p10le','-c:v','libx265','-threads','1',
                    '-x265-params','pools=1:frame-threads=1:log-level=error',
                    '-color_primaries','bt709','-colorspace','bt709','-color_trc','bt709',str(path)],check=True)
    info,timeline=timeline_from_source(path)
    with ExportSession(info,timeline,tmp_path/'work', mode=mode) as session:
        result=session.export(timeline.scenes([3,17])[1],tmp_path/'ten-cut.mov')
    assert result['video']['pixel_equality'] == ('not_applicable' if mode == 'compact' else 'equal')
    assert result['video']['preserved_attributes']['pix_fmt'] == 'yuv420p10le'


def test_hdr_reencoding_is_refused_without_creating_output(tmp_path):
    from framecleave.export import ExportSession
    from framecleave.media import PreservationError
    path=tmp_path/'hdr.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=30:duration=1',
                    '-vf','setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc','-c:v','libx264','-threads','1',str(path)],check=True)
    info,timeline=timeline_from_source(path)
    assert info.video['color_transfer'] == 'smpte2084'
    with ExportSession(info,timeline,tmp_path/'work') as session:
        with pytest.raises(PreservationError,match='HDR'):
            session.export(timeline.scenes([3,17])[1],tmp_path/'out.mov')
    assert not (tmp_path/'out.mov').exists()


def test_rotation_orientation_is_preserved_without_rotating_pixels(source_video,tmp_path):
    from framecleave.export import ExportSession
    path=tmp_path/'rotated.mov'
    subprocess.run(['ffmpeg','-v','error','-display_rotation','90','-i',str(source_video),'-c','copy',str(path)],check=True)
    info,timeline=timeline_from_source(path)
    assert any('rotation' in x for x in info.video.get('side_data_list',[]))
    with ExportSession(info,timeline,tmp_path/'work') as session:
        result=session.export(timeline.scenes([7,47])[1],tmp_path/'rot-cut.mov')
    assert result['video']['all_native_pixels_equal']
    assert result['video']['preserved_attributes']['rotation']


def test_b_frame_key_aligned_copy_does_not_publish_unverified_frames(source_video,tmp_path):
    from framecleave.export import ExportSession
    info,timeline=timeline_from_source(source_video)
    with ExportSession(info,timeline,tmp_path/'work') as session:
        result=session.export(timeline.scenes([30,60])[1],tmp_path/'aligned.mov')
    assert result['video']['frames_verified'] == 30
    assert result['video']['all_native_pixels_equal']


def test_actual_open_gop_boundaries_are_verified_not_assumed(tmp_path):
    from framecleave.export import ExportSession
    path = tmp_path / 'open-gop.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=30:duration=3',
                    '-c:v', 'libx264', '-threads', '1', '-x264-params',
                    'open-gop=1:keyint=24:min-keyint=24:scenecut=0:bframes=3:b-pyramid=normal', str(path)], check=True)
    info, timeline = timeline_from_source(path)
    assert 24 in timeline.keyframes
    with ExportSession(info, timeline, tmp_path / 'work') as session:
        result = session.export(timeline.scenes([24, 48])[1], tmp_path / 'open-gop-cut.mov')
    assert result['video']['all_native_pixels_equal']
    assert result['video']['frames_verified'] == 24
    assert result['video']['first_source_frame'] == 24
    assert result['video']['last_source_frame'] == 47


def test_ffv1_arbitrary_frame_cut_preserves_native_pixels(tmp_path):
    from framecleave.export import ExportSession
    path = tmp_path / 'lossless.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x96:rate=30:duration=1',
                    '-c:v', 'ffv1', '-threads', '1', str(path)], check=True)
    info, timeline = timeline_from_source(path)
    with ExportSession(info, timeline, tmp_path / 'work', mode='lossless') as session:
        result = session.export(timeline.scenes([7, 19])[1], tmp_path / 'cut.mkv')
    assert result['video']['all_native_pixels_equal']
    assert result['video']['all_pts_equal']
    assert result['video']['frames_verified'] == 12


def test_property_verifier_rejects_a_changed_video_codec(source_video):
    from copy import deepcopy
    from dataclasses import replace
    from framecleave.export import compare_properties
    from framecleave.media import PreservationError, probe
    source = probe(source_video)
    output = replace(source, document=deepcopy(source.document))
    output.video['codec_name'] = 'hevc'
    with pytest.raises(PreservationError, match='codec_name'):
        compare_properties(source, output)


def test_compact_encodes_exact_interval_with_sample_equal_alac(integer_audio_video, tmp_path):
    from framecleave.export import ExportSession

    info, timeline = timeline_from_source(integer_audio_video)
    with ExportSession(info, timeline, tmp_path / 'work', mode='compact', threads=1) as session:
        result = session.export(timeline.scenes([7, 47])[1], tmp_path / 'compact.mov')
    assert result['method'] == 'compact-reencode'
    assert result['video']['frames_verified'] == 40
    assert result['video']['pixel_equality'] == 'not_applicable'
    assert 'all_native_pixels_equal' not in result['video']
    assert result['video']['all_pts_equal'] is True
    assert result['video']['quality']['ssim']['minimum'] > 0
    assert result['video']['quality']['psnr']['minimum'] > 0
    assert result['audio'][0]['sample_equality'] == 'equal'
    assert result['audio'][0]['codec'] == 'alac'


def test_compact_preserves_aac_float_samples_using_native_pcm(source_video, tmp_path):
    from framecleave.export import ExportSession

    info, timeline = timeline_from_source(source_video)
    with ExportSession(info, timeline, tmp_path / 'work', mode='compact', threads=1) as session:
        result = session.export(timeline.scenes([7, 47])[1], tmp_path / 'compact.mov')
    assert result['audio'][0]['sample_equality'] == 'equal'
    assert result['audio'][0]['codec'] == 'pcm_f32le'
    assert result['audio'][0]['encoding_reason'] == 'native-float-precision'


@pytest.mark.parametrize('corruption', ['shuffleframes=1 0', 'shuffleframes=0 0',
                                        'drawbox=color=black:t=fill'])
def test_compact_verifier_rejects_corrupted_content_with_unchanged_timing(integer_audio_video, tmp_path, corruption):
    from framecleave.export import ExportSession
    from framecleave.media import MediaError, probe

    info, timeline = timeline_from_source(integer_audio_video)
    scene = timeline.scenes([7, 47])[1]
    clean = tmp_path / 'clean.mov'
    corrupted = tmp_path / 'corrupted.mov'
    with ExportSession(info, timeline, tmp_path / 'work', mode='compact', threads=1) as session:
        session.export(scene, clean)
        encoder = session.policy.video.encoder
        command = ['ffmpeg', '-v', 'error', '-i', str(clean), '-an',
                   '-vf', corruption, '-c:v', encoder, '-threads', '1', '-bf', '0',
                   '-video_track_timescale', str(timeline.time_base.denominator)]
        if encoder == 'libx265':
            command += ['-x265-params', 'pools=1:frame-threads=1:log-level=error']
        subprocess.run(command + [str(corrupted)], check=True, capture_output=True)
        with pytest.raises(MediaError, match='compact frame correspondence'):
            session.verify_compact_video(scene, probe(corrupted))


def test_compact_quality_refuses_missing_ffmpeg_metric(source_video, tmp_path, monkeypatch):
    from framecleave.export import ExportSession
    from framecleave.media import MediaError

    info, timeline = timeline_from_source(source_video)
    monkeypatch.setattr('framecleave.export.run', lambda command, **kwargs: b'')
    with ExportSession(info, timeline, tmp_path / 'work', mode='compact') as session:
        with pytest.raises(MediaError, match='Missing compact ssim'):
            session._compact_quality(timeline.scenes([])[0], info, tmp_path)


def test_compact_quality_handles_output_paths_with_filter_metacharacters(source_video, tmp_path):
    from framecleave.export import ExportSession

    info, timeline = timeline_from_source(source_video)
    output = tmp_path / "private: output's"
    with ExportSession(info, timeline, output / 'work', mode='compact') as session:
        result = session.export(timeline.scenes([7, 47])[1], output / 'scene.mov')
    assert result['video']['quality']['frames_compared'] == 40


def test_invalid_compact_policy_creates_no_orphan_scratch(source_video, tmp_path):
    from framecleave.export import ExportSession
    from framecleave.policy import ExportPolicy

    info, timeline = timeline_from_source(source_video)
    parent = tmp_path / 'work'
    with pytest.raises(ValueError, match='source codec family'):
        ExportSession(info, timeline, parent, mode='compact', policy=ExportPolicy.compact(source_codec='hevc'))
    assert not parent.exists() or not list(parent.iterdir())
