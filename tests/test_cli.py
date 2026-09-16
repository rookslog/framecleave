import json
import os
from pathlib import Path
import subprocess
import sys


def call_cli(*args):
    return subprocess.run([sys.executable, '-m', 'framecleave', *map(str, args)], capture_output=True, text=True)


def test_help_version_and_diagnostics():
    result=call_cli('--help')
    assert result.returncode == 0
    assert all(name in result.stdout for name in ['inspect','split','batch','verify','doctor'])
    assert '0.1.0rc1' in call_cli('--version').stdout
    result=call_cli('doctor','--json')
    assert result.returncode == 0
    assert json.loads(result.stdout)['backend'] == 'software-cpu'


def test_split_dry_run_cli_and_wrong_cuts(source_video,tmp_path):
    result=call_cli('split',source_video,'-o',tmp_path/'out','--dry-run','--cuts','7,47','--json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['scene_count'] == 3
    assert not (tmp_path/'out'/'scenes').exists()
    result=call_cli('split',source_video,'-o',tmp_path/'bad','--cuts','7,7')
    assert result.returncode == 2
    assert 'Traceback' not in result.stderr


def test_batch_isolates_failure_and_resumes(source_video,tmp_path):
    import shutil
    inputs=tmp_path/'inputs';inputs.mkdir()
    shutil.copy(source_video,inputs/'good clip.mp4')
    (inputs/'broken.mkv').write_text('not video')
    result=call_cli('batch',inputs,'-o',tmp_path/'out','--dry-run','--jobs','2','--json')
    assert result.returncode == 1,result.stderr
    value=json.loads(result.stdout)
    assert value['succeeded'] == 1 and value['failed'] == 1
    assert (tmp_path/'out'/'batch-summary.json').is_file()
    result=call_cli('batch',inputs,'-o',tmp_path/'out','--dry-run','--resume','--json')
    assert result.returncode == 1
    assert json.loads(result.stdout)['succeeded'] == 1


def test_verify_redecodes_outputs(source_video,tmp_path):
    result=call_cli('split',source_video,'-o',tmp_path/'out','--cuts','7,47','--quiet')
    assert result.returncode == 0,result.stderr
    result=call_cli('verify',source_video,tmp_path/'out'/'scene-index.json','--json')
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout)['verified']
