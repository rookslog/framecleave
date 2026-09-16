"""Internal Unix launcher: set a file-size ceiling without threaded preexec hooks.

The launched process replaces this interpreter. There is no shell or child tree;
cancellation of the Popen handle therefore also stops the media writer.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys

def run_limited(command: list[str], partial: Path, limit: int, *, label: str, on_progress=None) -> int:
    """Stream bounded diagnostics; the writer cannot grow its file beyond limit."""
    import logging
    from .media import MediaError
    log = logging.getLogger(__name__)
    log.debug('%s command: %r', label, command)
    process = subprocess.Popen([sys.executable, '-m', 'framecleave.limited_process', str(limit), '--', *command],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    tail = bytearray()
    count = 0
    pending = b''
    try:
        assert process.stderr is not None
        while block := process.stderr.read1(4096):
            count += len(block)
            tail.extend(block)
            del tail[:-6000]
            if on_progress:
                lines = (pending + block).split(b'\n')
                pending = lines.pop()[-256:]
                for line in lines:
                    if line.startswith(b'frame=') and line[6:].strip().isdigit():
                        on_progress(int(line[6:].strip()))
        code = process.wait()
        if tail:
            log.debug('%s diagnostics%s: %s', label, ' [tail truncated]' if count > len(tail) else '',
                      tail.decode('utf-8', 'replace'))
        if code:
            if code == -getattr(signal, 'SIGXFSZ', 25) or (partial.exists() and partial.stat().st_size >= limit):
                raise MediaError(f'Temporary media budget exceeded ({limit} bytes) during {label}')
            raise MediaError(f'FFmpeg {label} failed ({code}); consult private diagnostics; no automatic fallback')
        return count
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stderr:
            process.stderr.close()


def main() -> None:
    import resource

    if len(sys.argv) < 4 or sys.argv[2] != '--':
        raise ValueError('Expected a positive byte limit followed by -- and an executable')
    limit = int(sys.argv[1])
    if limit <= 0:
        raise ValueError('File-size limit must be positive')
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
    os.execv(sys.argv[3], sys.argv[3:])


if __name__ == '__main__':
    main()
