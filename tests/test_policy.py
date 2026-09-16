from dataclasses import replace

import pytest


def test_policy_digest_changes_with_quality_or_audio():
    from framecleave.policy import AudioPolicy, ExportPolicy, policy_digest

    base = ExportPolicy.compact(crf=18, audio='alac')
    assert policy_digest(base) != policy_digest(replace(base, video=replace(base.video, crf=20)))
    assert policy_digest(base) != policy_digest(replace(base, audio=AudioPolicy('pcm')))


def test_policy_deserialization_is_strict_and_canonical():
    from framecleave.policy import ExportPolicy, policy_digest

    policy = ExportPolicy.compact(crf=18)
    assert ExportPolicy.from_dict(policy.to_dict()) == policy
    assert len(policy_digest(policy)) == 64
    with pytest.raises(ValueError, match='unknown'):
        ExportPolicy.from_dict({**policy.to_dict(), 'surprise': True})
    with pytest.raises(ValueError, match='strategy'):
        ExportPolicy.from_dict({**policy.to_dict(), 'mode': 'auto'})


@pytest.mark.parametrize(('source_codec', 'encoder'), [('h264', 'libx264'), ('hevc', 'libx265')])
def test_compact_policy_maps_only_supported_source_codec_families(source_codec, encoder):
    from framecleave.policy import resolve_policy

    assert resolve_policy('compact', source_codec=source_codec).video.encoder == encoder
    with pytest.raises(ValueError, match='unsupported'):
        resolve_policy('compact', source_codec='vp9')


def test_explicit_auto_remains_the_legacy_copy_then_lossless_policy():
    from framecleave.policy import resolve_policy

    policy = resolve_policy('auto', source_codec='h264')
    assert policy.mode == 'auto'
    assert policy.video.strategy == 'copy-then-lossless'
    assert policy.audio.codec == 'source-lossless'


def test_old_certificates_are_read_as_exact_and_compact_cannot_claim_pixel_equality():
    from framecleave.policy import ExportPolicy, certificate_policy, policy_digest

    assert certificate_policy({'video': {'all_native_pixels_equal': True}}, source_codec='h264').mode == 'auto'
    compact = ExportPolicy.compact()
    certificate = {'schema_version': 2, 'policy': compact.to_dict(),
                   'policy_digest': policy_digest(compact), 'video': {'all_native_pixels_equal': True}}
    with pytest.raises(ValueError, match='cannot claim'):
        certificate_policy(certificate, source_codec='h264')
