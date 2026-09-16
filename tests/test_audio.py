from fractions import Fraction
import hashlib

import pytest



def test_audio_cache_and_exact_sample_slice(source_video, tmp_path):
    from framecleave.audio import extract_audio, slice_track
    from framecleave.media import probe
    tracks = extract_audio(probe(source_video), tmp_path / "audio")
    assert len(tracks) == 1
    t = tracks[0]
    assert t.rate == 48000
    assert t.codec == "pcm_f32le"
    cut = slice_track(t, Fraction(7, 30), Fraction(47, 30), tmp_path / "slice")
    assert cut.first_sample == 11200
    assert cut.end_sample == 75200
    assert cut.delay == 0
    with t.path.open("rb") as f:
        f.seek(11200 * 4)
        expected = f.read(64000 * 4)
    assert cut.path.read_bytes() == expected
    assert cut.sha256 == hashlib.sha256(expected).hexdigest()


def test_sample_rounding_uses_ceiling_not_nearest(tmp_path):
    from framecleave.audio import AudioTrack, slice_track
    raw = tmp_path / "a.raw"
    raw.write_bytes(bytes(range(40)))
    t = AudioTrack(0, raw, 10, 1, "mono", "s16le", "pcm_s16le", 2, 20, 0, 0, {})
    cut = slice_track(t, Fraction(1, 25), Fraction(14, 25), tmp_path / "clip")
    assert (cut.first_sample, cut.end_sample) == (1, 6)
    assert cut.delay == Fraction(3, 50)
    assert cut.path.read_bytes() == bytes(range(2, 12))


def test_audio_outside_scene_returns_no_track(tmp_path):
    from framecleave.audio import AudioTrack, slice_track
    raw = tmp_path / "a.raw"
    raw.write_bytes(bytes(40))
    t = AudioTrack(0, raw, 10, 1, "mono", "s16le", "pcm_s16le", 2, 20, 100, 0, {})
    assert slice_track(t, Fraction(0), Fraction(1), tmp_path / "clip") is None


@pytest.mark.parametrize(('raw_format', 'codec', 'sample_bytes', 'expected'), [
    ('s16le', 'pcm_s16le', 2, ('alac', 'verified-16-bit-integer')),
    ('s32le', 'pcm_s32le', 4, ('pcm_s32le', 'native-integer-precision')),
    ('f32le', 'pcm_f32le', 4, ('pcm_f32le', 'native-float-precision')),
])
def test_compact_audio_selection_never_quantizes_native_samples(tmp_path, raw_format, codec,
                                                               sample_bytes, expected):
    from framecleave.audio import AudioTrack, audio_encoding

    track = AudioTrack(0, tmp_path / 'raw', 48000, 1, 'mono', raw_format, codec,
                       sample_bytes, 1, 0, 0, {})
    assert audio_encoding(track, 'alac-or-pcm') == expected
