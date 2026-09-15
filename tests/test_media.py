from fractions import Fraction
from pathlib import Path

import pytest


def test_probe_reports_actual_streams_and_hash(source_video):
    from framecleave.media import probe
    media = probe(source_video)
    assert media.video["width"] == 160
    assert media.video["pix_fmt"] == "yuv420p"
    assert media.time_base == Fraction(1, 15360)
    assert len(media.audio) == 1
    assert len(media.sha256) == 64


def test_analysis_decode_keeps_all_frames_and_pts(source_video):
    from framecleave.media import probe, iter_video
    info = probe(source_video)
    rows = list(iter_video(info, width=128, height=96))
    assert len(rows) == 90
    assert [r.number for r in rows] == list(range(90))
    assert [r.pts for r in rows] == [i * 512 for i in range(90)]
    assert rows[-1].duration == 512
    assert rows[0].image.shape == (96, 128, 3)
    assert rows[0].keyframe


def test_hash_decode_has_every_source_frame(source_video):
    from framecleave.media import probe, video_hashes
    info = probe(source_video)
    rows = video_hashes(info)
    assert len(rows) == 90
    assert rows[0]["pts"] == 0
    assert rows[-1]["pts"] == 89 * 512
    assert rows[-1]["duration"] == 512
    assert len({x["sha256"] for x in rows}) > 80


def test_probe_rejects_non_file_and_corruption(tmp_path):
    from framecleave.media import probe, MediaError
    with pytest.raises(MediaError):
        probe(tmp_path)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(MediaError):
        probe(bad)


def test_partial_consumer_closes_decoder(source_video):
    from framecleave.media import probe, iter_video
    stream = iter_video(probe(source_video), width=128, height=96)
    assert next(stream).number == 0
    stream.close()


def test_sparse_decode_has_source_ordinals_and_exact_pts(source_video):
    from framecleave.media import probe, iter_video
    frames = list(iter_video(probe(source_video), width=128, height=96, selected=[0, 7, 8, 60, 89]))
    assert [f.number for f in frames] == [0, 7, 8, 60, 89]
    assert [f.pts for f in frames] == [0, 3584, 4096, 30720, 45568]


def test_large_selection_expression_is_balanced():
    from framecleave.media import selection_expression, ffmpeg_base, run
    expression = selection_expression(list(range(0, 6000, 2)))
    depth = peak = 0
    for char in expression:
        if char == "(":
            depth += 1
            peak = max(peak, depth)
        elif char == ")":
            depth -= 1
    assert peak < 30
    out = run(ffmpeg_base() + ["-f", "lavfi", "-i", "color=size=16x16:duration=0.04:rate=25",
                               "-vf", f"select='{expression}'", "-f", "null", "-"])
