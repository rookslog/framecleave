from pathlib import Path
from fractions import Fraction
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
