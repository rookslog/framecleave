"""Deterministic, generated-only fixtures. No private material belongs in tests."""
from __future__ import annotations

from pathlib import Path
import subprocess
import pytest


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("media")
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=3",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "19",
        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-bf", "3",
        "-threads", "2", "-c:a", "aac", "-metadata", "title=Generated test",
        str(directory / "source.mp4"),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return directory


@pytest.fixture
def source_video(media_dir: Path) -> Path:
    return media_dir / "source.mp4"


@pytest.fixture(params=['h264', 'hevc'])
def integer_audio_video(request, tmp_path):
    source = tmp_path / f'integer-{request.param}.mov'
    encoder = 'libx264' if request.param == 'h264' else 'libx265'
    command = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
               'testsrc2=size=160x120:rate=30:duration=2', '-f', 'lavfi', '-i',
               'sine=frequency=500:sample_rate=48000:duration=2',
               '-c:v', encoder, '-threads', '1', '-g', '60', '-c:a', 'pcm_s16le']
    if request.param == 'hevc':
        command += ['-x265-params', 'pools=1:frame-threads=1:log-level=error']
    subprocess.run(command + [str(source)], check=True, capture_output=True)
    return source
