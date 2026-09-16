import json

import pytest

from scripts.audit_release import check_name


@pytest.mark.parametrize('name', [
    'benchmarks/annotations/source.json',
    'benchmarks/results/aggregate.json',
    'framecleave-0.2/benchmarks/results/source-timing.json',
])
def test_release_rejects_private_derived_artifact_locations(name):
    with pytest.raises(ValueError):
        check_name(name)


@pytest.mark.parametrize('name', [
    'benchmarks/results/synthetic.json',
    'framecleave-0.2/benchmarks/results/compact-export.json',
])
def test_release_allows_synthetic_result_locations(name):
    check_name(name)


def test_release_rejects_private_aggregate_in_generated_result_slot():
    from scripts.audit_release import check_content

    with pytest.raises(ValueError):
        check_content('benchmarks/results/compact-export.json',
                      json.dumps({'corpora': {'private': 1}}).encode())


def test_release_allows_generated_calibration_content():
    from scripts.audit_release import check_content

    check_content('benchmarks/results/compact-export.json',
                  json.dumps({'corpora': {'generated': 18}}).encode())


def test_release_checks_generated_calibration_content_in_archives(tmp_path):
    import subprocess
    import zipfile
    from scripts.audit_release import audit

    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    archive = tmp_path / 'candidate.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('framecleave/benchmarks/results/compact-export.json',
                         json.dumps({'corpora': {'private': 1}}))
    with pytest.raises(ValueError):
        audit(tmp_path, [archive])
