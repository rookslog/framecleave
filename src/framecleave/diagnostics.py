"""Capability reporting without model downloads or optimistic hardware claims."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import os
import platform
import re
import shutil
import subprocess

from . import __version__


def diagnostics() -> dict:
    packages = {}
    for name in ['numpy', 'opencv-python', 'opencv-python-headless', 'opencv-contrib-python', 'opencv-contrib-python-headless']:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    result = {'tool_version': __version__, 'system': platform.system(), 'release': platform.release(),
              'machine': platform.machine(), 'python': platform.python_version(), 'cpu_count': os.cpu_count(),
              'packages': packages, 'backend': 'software-cpu', 'hardware_acceleration_validated': False,
              'ffmpeg': None, 'ffprobe': None, 'encoders': [], 'warnings': [], 'ok': True}
    for name in ['ffmpeg', 'ffprobe']:
        path = shutil.which(name)
        if not path:
            result['ok'] = False
            result['warnings'].append(f'{name} missing: install system FFmpeg (macOS: brew install ffmpeg)')
            continue
        try:
            text = subprocess.run([path, '-version'], capture_output=True, text=True, check=True, timeout=10).stdout
            result[name] = {'path': path, 'version_line': text.splitlines()[0]}
            major = re.search(r'version\s+(?:n)?(\d+)\.', text)
            if major and int(major[1]) < 7:
                result['ok'] = False
                result['warnings'].append('FFmpeg 7 or newer is required for exact decoded duration metadata')
        except (OSError, subprocess.SubprocessError) as exc:
            result['ok'] = False
            result['warnings'].append(str(exc))
    if result['ffmpeg']:
        try:
            text = subprocess.run([result['ffmpeg']['path'], '-hide_banner', '-encoders'], capture_output=True,
                                  text=True, check=True, timeout=10).stdout
            result['encoders'] = [name for name in ['libx264', 'libx265', 'ffv1', 'h264_videotoolbox', 'hevc_videotoolbox']
                                  if re.search(r'\b' + name + r'\b', text)]
        except subprocess.SubprocessError as exc:
            result['warnings'].append(str(exc))
    if result['system'] == 'Darwin' and result['machine'] != 'arm64':
        result['warnings'].append('This Python process is not arm64; use native Homebrew/Python instead of Rosetta')
    variants = [name for name, value in packages.items() if name.startswith('opencv-') and value]
    result['opencv_build'] = {'version': None, 'gui': None, 'distribution_count': len(variants)}
    try:
        import cv2
        build = cv2.getBuildInformation()
        match = re.search(r'^\s*GUI:\s*(.+)$', build, re.MULTILINE)
        result['opencv_build'].update(version=cv2.__version__, gui=match[1].strip() if match else 'unknown')
    except ImportError as exc:
        result['ok'] = False
        result['warnings'].append(f'OpenCV cannot be imported: {exc}')
    if len(variants) > 1:
        result['warnings'].append('Multiple OpenCV distributions share cv2; use a fresh isolated environment with exactly one')
    if not packages['numpy'] or not packages['opencv-python']:
        result['warnings'].append('A declared Python dependency has no package metadata; reinstall the package')
    if not {'libx264', 'libx265'}.issubset(result['encoders']):
        result['warnings'].append('H.264/HEVC lossless fallback requires both libx264 and libx265 encoders')
    return result
