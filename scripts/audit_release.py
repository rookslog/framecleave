#!/usr/bin/env python3
"""Fail if Git or release archives contain private media, secrets or unsafe paths."""
from __future__ import annotations
import argparse
import json
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
    if 'benchmarks' in path.parts:
        relative = path.parts[path.parts.index('benchmarks') + 1:]
        if relative and relative[0] == 'annotations':
            raise ValueError(f'Local-only evaluation annotations: {name}')
        if relative and relative[0] == 'results' and len(relative) > 1:
            if len(relative) != 2 or relative[1] not in {'synthetic.json', 'compact-export.json'}:
                raise ValueError(f'Non-synthetic evaluation artifact: {name}')


def check_content(name: str, content: bytes) -> None:
    path = PurePosixPath(name)
    if 'benchmarks' in path.parts and path.name == 'compact-export.json':
        data = json.loads(content)
        corpora = data.get('corpora') if isinstance(data, dict) else None
        if not isinstance(corpora, dict) or set(corpora) != {'generated'}:
            raise ValueError(f'Calibration evidence must be generated-only: {name}')
        count = corpora['generated']
        if type(count) is not int or count <= 0:
            raise ValueError(f'Invalid generated calibration count: {name}')


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
        check_content(name, content)
        # Only obvious secret signatures; not a substitute for a human privacy audit.
        for marker in [b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----']:
            if marker in content and name != 'scripts/audit_release.py':
                raise ValueError(f'Potential secret in {name}')
        count += 1
    for archive in archives:
        if archive.suffix in {'.whl', '.zip'}:
            with zipfile.ZipFile(archive) as z:
                for entry in z.infolist():
                    check_name(entry.filename)
                    if not entry.is_dir():
                        check_content(entry.filename, z.read(entry))
        else:
            with tarfile.open(archive) as t:
                for entry in t.getmembers():
                    check_name(entry.name)
                    if entry.isfile():
                        with t.extractfile(entry) as member:
                            check_content(entry.name, member.read())
    print(f'Audited {count} tracked files and {len(archives)} archives; no forbidden media/path entries.')
    return count


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archives', nargs='*', type=Path)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    a = p.parse_args()
    audit(a.root, a.archives)
