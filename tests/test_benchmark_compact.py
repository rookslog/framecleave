import json

import pytest


def _private_run(**changes):
    value = {
        'source_path': '/private/person/name.mkv', 'source_sha256': 'f' * 64,
        'codec': 'hevc', 'crf': 18, 'corpus': 'private', 'structural': 'passed',
        'source_bytes': 100, 'output_bytes': 40, 'duration_seconds': 2,
        'wall_seconds': 4, 'frames': 60,
        'quality': {'ssim': {'mean': .99, 'minimum': .98},
                    'psnr': {'mean': 42, 'minimum': 40}},
        'audio_codecs': {'pcm_f32le': 3}, 'audio_packet_bytes': 15,
    }
    value.update(changes)
    return value


def test_compact_benchmark_whitelists_aggregate_evidence_and_redacts_private_inputs():
    from scripts.benchmark_compact import summarize_runs

    result = summarize_runs([_private_run()])
    text = json.dumps(result)
    assert '/private/' not in text
    assert 'name.mkv' not in text
    assert 'f' * 64 not in text
    profile = result['profiles']['hevc-crf18']
    assert profile['runs'] == 1
    assert profile['output_source_ratio'] == .4
    assert profile['processing_speed_realtime'] == .5
    assert profile['quality']['ssim']['minimum'] == .98
    assert profile['audio_packet_bytes'] == 15
    assert result['owner_decision']['status'] == 'pending'


def test_compact_benchmark_counts_failures_without_copying_private_exceptions():
    from scripts.benchmark_compact import summarize_runs

    failed = _private_run(structural='failed', error='/private/secret: FFmpeg stderr')
    result = summarize_runs([failed])
    assert result['profiles']['hevc-crf18']['structural_failures'] == 1
    assert '/private/' not in json.dumps(result)
    assert result['profiles']['hevc-crf18']['output_source_ratio'] is None


def test_compact_benchmark_rejects_untrusted_profile_identity_fields():
    from scripts.benchmark_compact import summarize_runs

    with pytest.raises(ValueError, match='profile identity'):
        summarize_runs([_private_run(codec='/private/name.mkv')])


def test_compact_benchmark_aggregates_quality_by_compared_frames():
    from scripts.benchmark_compact import summarize_runs

    first = _private_run(frames=10)
    second = _private_run(frames=30, quality={'ssim': {'mean': .95, 'minimum': .9},
                                              'psnr': {'mean': 38, 'minimum': 35}})
    profile = summarize_runs([first, second])['profiles']['hevc-crf18']
    assert profile['quality']['ssim']['mean'] == pytest.approx(.96)
    assert profile['quality']['ssim']['minimum'] == .9


def test_compact_benchmark_results_refuse_overwrite_and_symlinks(tmp_path):
    from scripts.benchmark_compact import write_result

    result = tmp_path / 'result.json'
    result.write_text('keep')
    with pytest.raises(FileExistsError):
        write_result(result, {'new': True})
    assert result.read_text() == 'keep'
    link = tmp_path / 'link.json'
    link.symlink_to(result)
    with pytest.raises(FileExistsError):
        write_result(link, {'new': True}, force=True)
    write_result(result, {'new': True}, force=True)
    assert json.loads(result.read_text()) == {'new': True}


def test_private_benchmark_rejects_aggregate_output_inside_repository(tmp_path, monkeypatch):
    from scripts import benchmark_compact

    repository = tmp_path / 'repository'
    repository.mkdir()
    private = tmp_path / 'private'
    private.mkdir()
    monkeypatch.setattr(benchmark_compact, 'PROJECT_ROOT', repository)

    result = benchmark_compact.main([
        '--private-directory', str(private),
        '--raw-output', str(tmp_path / 'raw.json'),
        '--work-directory', str(tmp_path / 'work'),
        '--output', str(repository / 'aggregate.json'),
    ])

    assert result == 2
    assert not (repository / 'aggregate.json').exists()
    assert not (tmp_path / 'work').exists()


def test_compact_benchmark_runs_real_full_coverage_with_native_float_audio(source_video, tmp_path):
    from scripts.benchmark_compact import benchmark_source

    result = benchmark_source(source_video, tmp_path / 'work', crf=18, corpus='generated', threads=1)
    assert result['structural'] == 'passed'
    assert result['frames'] == 90
    assert result['source_bytes'] > 0
    assert result['output_bytes'] > 0
    assert result['audio_codecs'] == {'pcm_f32le': 3}
    assert result['quality']['ssim']['mean'] > 0
