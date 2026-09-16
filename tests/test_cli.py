import json
import subprocess
import sys

import pytest


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


@pytest.mark.parametrize('flag', ['--quiet', '--verbose', '--debug'])
def test_presentation_flags_are_accepted_and_keep_stdout_machine_readable(flag):
    result = call_cli('doctor', flag, '--json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['ok'] is True
    assert result.stdout.count('\n') == 1


def test_presentation_flags_are_mutually_exclusive():
    result = call_cli('doctor', '--verbose', '--debug')
    assert result.returncode == 2


@pytest.mark.parametrize('flag', [None, '--verbose', '--debug'])
def test_progress_modes_never_write_progress_to_stdout(flag):
    args = ['doctor', '--json']
    if flag:
        args.insert(1, flag)
    result = call_cli(*args)
    assert result.returncode == 0, result.stderr
    assert list(json.loads(result.stdout))
    assert result.stdout.count('\n') == 1


def test_split_dry_run_cli_and_wrong_cuts(source_video,tmp_path):
    result=call_cli('split',source_video,'-o',tmp_path/'out','--dry-run','--cuts','7,47','--json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['scene_count'] == 3
    assert not (tmp_path/'out'/'scenes').exists()
    result=call_cli('split',source_video,'-o',tmp_path/'bad','--cuts','7,7')
    assert result.returncode == 2
    assert 'Traceback' not in result.stderr


def test_split_progress_modes_keep_recovered_diagnostics_bounded(source_video, tmp_path):
    default = call_cli('split', source_video, '-o', tmp_path / 'default', '--cuts', '30,60', '--json')
    assert default.returncode == 0, default.stderr
    assert 'Non-monotonic DTS' not in default.stderr
    assert 'attempt rejected' not in default.stderr

    verbose = call_cli('split', source_video, '-o', tmp_path / 'verbose', '--cuts', '30,60',
                       '--verbose', '--json')
    assert verbose.returncode == 0, verbose.stderr
    assert 'attempt rejected' in verbose.stderr
    assert 'Non-monotonic DTS' not in verbose.stderr

    debug = call_cli('split', source_video, '-o', tmp_path / 'debug', '--cuts', '30,60',
                     '--debug', '--json')
    assert debug.returncode == 0, debug.stderr
    assert 'DEBUG: exec' in debug.stderr
    assert json.loads(debug.stdout)['status'] == 'complete'


def test_batch_isolates_failure_and_resumes(source_video,tmp_path):
    import shutil
    inputs=tmp_path/'inputs'
    inputs.mkdir()
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


@pytest.mark.parametrize('jobs', [1, 2])
def test_batch_events_are_parent_serialized_for_all_job_counts(source_video, tmp_path, jobs):
    import shutil

    inputs = tmp_path / f'inputs-{jobs}'
    inputs.mkdir()
    shutil.copy(source_video, inputs / 'one.mp4')
    shutil.copy(source_video, inputs / 'two.mp4')
    output = tmp_path / f'out-{jobs}'
    result = call_cli('batch', inputs, '-o', output, '--dry-run', '--jobs', jobs, '--json')
    assert result.returncode == 0, result.stderr
    lines = (output / 'batch-events.jsonl').read_text().splitlines()
    events = [json.loads(line) for line in lines]
    assert {'batch_started', 'job_started', 'job_finished', 'batch_finished'} <= {
        event['event'] for event in events
    }
    assert all('ffmpeg stderr' not in json.dumps(event) for event in events)
    summary = json.loads((output / 'batch-summary.json').read_text())
    assert summary['pending'] == 0
    assert summary['active'] == 0
    assert summary['succeeded'] == 2
    assert summary['event_log'] == 'batch-events.jsonl'
    assert summary['current_bytes'] > 0
    assert summary['peak_bytes'] >= summary['current_bytes']


def test_verify_redecodes_outputs(source_video,tmp_path):
    result=call_cli('split',source_video,'-o',tmp_path/'out','--cuts','7,47','--quiet')
    assert result.returncode == 0,result.stderr
    result=call_cli('verify',source_video,tmp_path/'out'/'scene-index.json','--json')
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout)['verified']


def test_ctrl_c_releases_lock_and_keeps_a_resumable_state(source_video, tmp_path):
    import os
    import shutil
    import signal
    import time

    # Synchronize at the subprocess boundary. A tiny real video can otherwise
    # finish between noticing state.json and sending SIGINT, making this test race.
    out = tmp_path / 'cancel'
    entered = tmp_path / 'decoder-entered'
    shim_dir = tmp_path / 'bin'
    shim_dir.mkdir()
    actual_ffmpeg = shutil.which('ffmpeg')
    assert actual_ffmpeg
    shim = shim_dir / 'ffmpeg'
    shim.write_text(
        f'#!{sys.executable}\n'
        'import os,sys,time\n'
        'from pathlib import Path\n'
        'if "-/filter:v" in sys.argv or "-filter_script:v" in sys.argv:\n'
        f'    Path({str(entered)!r}).write_text(str(os.getpid()))\n'
        '    while True: time.sleep(0.01)\n'
        f'os.execv({actual_ffmpeg!r}, [{actual_ffmpeg!r}] + sys.argv[1:])\n'
    )
    shim.chmod(0o700)
    environment = dict(os.environ)
    environment['PATH'] = str(shim_dir) + os.pathsep + environment.get('PATH', '')
    # A background test runner may inherit SIG_IGN from its shell. Establish the
    # foreground CLI signal disposition explicitly in the child, never preexec_fn.
    bootstrap = ('import signal; signal.signal(signal.SIGINT, signal.default_int_handler); '
                 'from framecleave.cli import main; raise SystemExit(main())')
    process = subprocess.Popen(
        [sys.executable, '-c', bootstrap, 'inspect', str(source_video), '-o', str(out), '--quiet'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
    )
    try:
        deadline = time.monotonic() + 20
        while not entered.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered.exists(), 'Decoder did not reach the controlled cancellation point'
        assert (out / 'state.json').exists()
        assert process.poll() is None
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 130, (stdout, stderr)
        assert not (out / '.lock').exists()
        assert json.loads((out / 'state.json').read_text())['status'] == 'interrupted'
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
        if entered.exists():
            # Also clean the controlled shim if an assertion or timeout killed the CLI.
            try:
                os.kill(int(entered.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_diagnostics_reports_actual_opencv_build_not_just_metadata():
    result = call_cli('doctor', '--json')
    report = json.loads(result.stdout)
    assert report['opencv_build']['version']
    assert report['opencv_build']['gui']
    assert 'opencv-python' in report['packages']
    assert report['opencv_build']['distribution_count'] >= 1


def test_doctor_reports_missing_media_tools_without_traceback(monkeypatch):
    monkeypatch.setenv('PATH', '')
    result = call_cli('doctor', '--json')
    assert result.returncode == 3
    report = json.loads(result.stdout)
    assert not report['ok']
    assert report['ffmpeg'] is None and report['ffprobe'] is None
    assert 'Traceback' not in result.stderr
