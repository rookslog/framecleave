"""Internal Unix launcher: set a file-size ceiling without threaded preexec hooks.

The launched process replaces this interpreter. There is no shell or child tree;
cancellation of the Popen handle therefore also stops the media writer.
"""
from __future__ import annotations

import os
import signal
import sys


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
