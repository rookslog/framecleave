#!/usr/bin/env python3
"""Fail if Git or release archives contain private media, secrets or unsafe paths."""
from __future__ import annotations
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import zipfile

BANNED_SUFFIXES = {'.mkv', '.mp4', '.mov', '.avi', '.webm', '.jpg', '.jpeg', '.png', '.gif', '.rgb',
                   '.npy', '.npz', '.wav', '.flac', '.pth', '.pt', '.onnx', '.safetensors', '.pem', '.key'}
BANNED_PARTS = {'private', 'work-private', '.venv', '__pycache__', 'node_modules'}


def check_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or path.suffix.lower() in BANNED_SUFFIXES or set(path.parts) & BANNED_PARTS:
        raise ValueError(f'Unsafe/unwanted release entry: {name}')


def audit(root: Path, archives: list[Path]) -> int:
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
    count = 0
    for name in filter(None, tracked):
        check_name(name)
        p = root / name
        if p.is_symlink():
            raise ValueError(f'Symlinks are not included in source releases: {name}')
        if p.stat().st_size > 5_000_000:
            raise ValueError(f'Unexpectedly large source artifact: {name}')
        content = p.read_bytes()
        # Only obvious secret signatures; not a substitute for a human privacy audit.
        for marker in [b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----']:
            if marker in content and name != 'scripts/audit_release.py':
                raise ValueError(f'Potential secret in {name}')
        count += 1
    for archive in archives:
        if archive.suffix in {'.whl', '.zip'}:
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
        else:
            with tarfile.open(archive) as t:
                names = [m.name for m in t.getmembers()]
        for name in names:
            check_name(name)
    print(f'Audited {count} tracked files and {len(archives)} archives; no forbidden media/path entries.')
    return count


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archives', nargs='*', type=Path)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    a = p.parse_args()
    audit(a.root, a.archives)
