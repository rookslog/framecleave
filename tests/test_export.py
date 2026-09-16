import subprocess

import pytest


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


def test_one_frame_scene_is_not_discarded_by_mov_muxer(source_video, tmp_path):
    from framecleave.export import ExportSession
    info, timeline = timeline_from_source(source_video)
    with ExportSession(info, timeline, tmp_path / "work") as session:
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


def test_vfr_nonzero_pts_are_preserved_exactly(tmp_path):
    from framecleave.export import ExportSession
    path = tmp_path / 'vfr.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=60:duration=2',
                    '-vf',"select='not(mod(n,3))+eq(mod(n,11),1)',setpts=PTS+5.25/TB", '-fps_mode','passthrough',
                    '-c:v','libx264','-threads','1','-g','60','-bf','3','-video_track_timescale','90000', str(path)],check=True)
    info, timeline = timeline_from_source(path)
    assert timeline.pts[0] > 0
    assert len(set(timeline.durations)) > 1
    scene = timeline.scenes([7, 27])[1]
    with ExportSession(info, timeline, tmp_path / 'work') as session:
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


def test_two_audio_streams_keep_distinct_sample_clocks_and_offsets(tmp_path):
    from framecleave.export import ExportSession
    path = tmp_path / 'multi.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=30:duration=2',
                    '-f','lavfi','-i','sine=frequency=500:sample_rate=44100:duration=2',
                    '-f','lavfi','-i','sine=frequency=800:sample_rate=48000:duration=1.5',
                    '-map','0:v','-map','1:a','-map','2:a','-filter:a:1','asetpts=PTS+0.25/TB',
                    '-c:v','libx264','-threads','1','-g','60','-c:a','pcm_s16le',
                    '-metadata:s:a:0','language=eng','-metadata:s:a:1','language=fra',str(path)],check=True)
    info,timeline = timeline_from_source(path)
    with ExportSession(info,timeline,tmp_path/'work') as session:
        result=session.export(timeline.scenes([3,40])[1],tmp_path/'multi-cut.mov')
    assert len(result['audio']) == 2
    assert all(x['all_samples_equal'] for x in result['audio'])


def test_hevc_ten_bit_and_colour_are_preserved(tmp_path):
    from framecleave.export import ExportSession
    path=tmp_path/'ten.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=1',
                    '-vf','format=yuv420p10le','-c:v','libx265','-threads','1',
                    '-x265-params','pools=1:frame-threads=1:log-level=error',
                    '-color_primaries','bt709','-colorspace','bt709','-color_trc','bt709',str(path)],check=True)
    info,timeline=timeline_from_source(path)
    with ExportSession(info,timeline,tmp_path/'work') as session:
        result=session.export(timeline.scenes([3,17])[1],tmp_path/'ten-cut.mov')
    assert result['video']['all_native_pixels_equal']
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
