"""Versioned export policy identity and strict canonical serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json


@dataclass(frozen=True)
class VideoPolicy:
    strategy: str
    encoder: str | None = None
    crf: int | None = None
    preset: str | None = None
    encoder_threads: int | None = None
    encoder_build: str | None = None

    def __post_init__(self) -> None:
        if self.strategy not in {'copy-then-lossless', 'lossless', 'copy-only', 'compact', 'review-copy'}:
            raise ValueError(f'unknown video strategy: {self.strategy}')
        if self.strategy == 'compact':
            if self.encoder not in {'libx264', 'libx265'}:
                raise ValueError('compact video requires a supported encoder')
            if self.crf not in {16, 18, 20} or self.preset != 'medium':
                raise ValueError('compact video requires CRF 16, 18, or 20 with preset medium')
            if type(self.encoder_threads) is not int or not 1 <= self.encoder_threads <= 64:
                raise ValueError('compact encoder threads must be from 1 to 64')
            if self.encoder_build is not None and (not isinstance(self.encoder_build, str) or len(self.encoder_build) != 64):
                raise ValueError('invalid compact encoder build fingerprint')
        elif any(value is not None for value in (self.encoder, self.crf, self.preset, self.encoder_threads, self.encoder_build)):
            raise ValueError('exact video policies cannot carry compact encoder settings')


@dataclass(frozen=True)
class AudioPolicy:
    codec: str

    def __post_init__(self) -> None:
        if self.codec not in {'source-lossless', 'alac', 'pcm', 'alac-or-pcm', 'copy'}:
            raise ValueError(f'unsupported audio policy: {self.codec}')


@dataclass(frozen=True)
class ExportPolicy:
    mode: str
    video: VideoPolicy
    audio: AudioPolicy
    schema_version: int = 1
    certificate_schema: int = 2

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or type(self.certificate_schema) is not int or self.schema_version != 1 or self.certificate_schema != 2:
            raise ValueError('unsupported export policy schema')
        if self.mode not in {'compact', 'auto', 'lossless', 'copy-only', 'review-copy'}:
            raise ValueError(f'unknown export mode: {self.mode}')
        expected_strategy = {'compact': 'compact', 'auto': 'copy-then-lossless',
                             'lossless': 'lossless', 'copy-only': 'copy-only', 'review-copy': 'review-copy'}[self.mode]
        if not isinstance(self.video, VideoPolicy) or self.video.strategy != expected_strategy:
            raise ValueError('export mode and video strategy differ')
        if not isinstance(self.audio, AudioPolicy):
            raise ValueError('export audio policy must be typed')
        if (self.mode == 'review-copy') != (self.audio.codec == 'copy'):
            raise ValueError('packet-copy audio belongs only to the review-copy policy')

    @classmethod
    def compact(cls, *, crf: int = 18, audio: str = 'alac-or-pcm', source_codec: str = 'h264',
                threads: int = 2) -> 'ExportPolicy':
        encoders = {'h264': 'libx264', 'hevc': 'libx265'}
        if source_codec not in encoders:
            raise ValueError(f'unsupported compact source codec: {source_codec}')
        return cls('compact', VideoPolicy('compact', encoders[source_codec], crf, 'medium', threads), AudioPolicy(audio))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> 'ExportPolicy':
        if not isinstance(value, dict):
            raise ValueError('export policy must be an object')
        expected = {'mode', 'video', 'audio', 'schema_version', 'certificate_schema'}
        unknown = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        if unknown:
            raise ValueError(f"unknown export policy fields: {', '.join(unknown)}")
        if missing:
            raise ValueError(f"missing export policy fields: {', '.join(missing)}")
        video = value['video']
        audio = value['audio']
        if not isinstance(video, dict) or set(video) != {'strategy', 'encoder', 'crf', 'preset', 'encoder_threads', 'encoder_build'}:
            raise ValueError('video policy has unknown or missing fields')
        if not isinstance(audio, dict) or set(audio) != {'codec'}:
            raise ValueError('audio policy has unknown or missing fields')
        return cls(
            mode=value['mode'],
            video=VideoPolicy(**video),
            audio=AudioPolicy(**audio),
            schema_version=value['schema_version'],
            certificate_schema=value['certificate_schema'],
        )


def resolve_policy(mode: str, *, source_codec: str, crf: int = 18, threads: int = 2) -> ExportPolicy:
    if mode == 'review-copy':
        return ExportPolicy(mode, VideoPolicy('review-copy'), AudioPolicy('copy'))
    if mode == 'compact':
        return bind_encoder_build(ExportPolicy.compact(crf=crf, source_codec=source_codec, threads=threads))
    strategies = {'auto': 'copy-then-lossless', 'lossless': 'lossless', 'copy-only': 'copy-only'}
    try:
        strategy = strategies[mode]
    except KeyError as exc:
        raise ValueError(f'unknown export mode: {mode}') from exc
    return ExportPolicy(mode, VideoPolicy(strategy), AudioPolicy('source-lossless'))


def bind_encoder_build(policy: ExportPolicy) -> ExportPolicy:
    if policy.mode != 'compact':
        return policy
    from .media import ffmpeg_build_fingerprint

    current = ffmpeg_build_fingerprint()
    if policy.video.encoder_build is not None and policy.video.encoder_build != current:
        raise ValueError('Compact reference encoder build differs from the certified policy')
    return replace(policy, video=replace(policy.video, encoder_build=current))


def policy_digest(policy: ExportPolicy) -> str:
    payload = json.dumps(policy.to_dict(), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def certificate_policy(certificate: dict, *, source_codec: str) -> ExportPolicy:
    """Schema-1 certificates retain the legacy exact contract; schema 2 binds policy."""
    schema = certificate.get('schema_version', 1)
    if schema == 1:
        return resolve_policy('auto', source_codec=source_codec)
    if schema != 2:
        raise ValueError('unsupported certificate schema')
    policy = ExportPolicy.from_dict(certificate.get('policy'))
    if certificate.get('policy_digest') != policy_digest(policy):
        raise ValueError('certificate policy digest differs')
    if policy.mode in {'compact', 'review-copy'} and certificate.get('video', {}).get('all_native_pixels_equal') is True:
        raise ValueError(f'{policy.mode} certificate cannot claim native pixel equality')
    if policy.mode == 'review-copy' and any(a.get('all_samples_equal') is True or a.get('sample_equality') == 'equal'
                                          for a in certificate.get('audio', [])):
        raise ValueError('review-copy certificate cannot claim decoded audio sample equality')
    return policy
