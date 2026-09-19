"""Owned job directories, process locks, and durable atomic metadata writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import uuid

from .tempbudget import Reservation, reserve_temp


class _ReservedWriter:
    def __init__(self, handle, reservation):
        self.handle = handle
        self.reservation = reservation

    def write(self, payload):
        self.reservation.grow(self.handle.tell()+len(payload))
        return self.handle.write(payload)

    def __getattr__(self, name):
        # Do not expose truncate: writers must use checked writes to grow files.
        if name == 'truncate':
            raise AttributeError(name)
        return getattr(self.handle, name)


def atomic_write(path: Path, writer) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise FileExistsError(f"Refusing to replace a symlink: {path}")
    with reserve_temp(0) as reservation:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                writer(_ReservedWriter(handle, reservation))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def atomic_bytes(path: Path, payload: bytes) -> None:
    atomic_write(path, lambda handle: handle.write(payload))


def atomic_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8'))


class JobDirectory:
    """Resume may reclaim a dead *local* PID, never a live or foreign-host lock."""
    def __init__(self, path: Path, *, resume: bool = False):
        self.path = Path(path).expanduser().absolute()
        self.resume = resume
        self.token = uuid.uuid4().hex
        self.owned = False
        self.lock_reservation = None

    def __enter__(self) -> Path:
        if self.path.is_symlink():
            raise FileExistsError(f"Job directory must not be a symlink: {self.path}")
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.resume and any(self.path.iterdir()):
            raise FileExistsError(f"Output is not empty; use --resume for a matching job: {self.path}")
        lock = self.path / '.lock'
        if lock.exists() and self.resume and not lock.is_symlink():
            try:
                previous = json.loads(lock.read_text())
                pid = previous['pid']
                if previous['host'] == socket.gethostname() and type(pid) is int and pid > 0:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        lock.unlink()
            except (ValueError, KeyError, PermissionError):
                pass
        try:
            payload = json.dumps({'pid': os.getpid(), 'host': socket.gethostname(), 'token': self.token}).encode('utf-8')
            self.lock_reservation = Reservation(len(payload))
            with lock.open('xb') as handle:
                handle.write(payload)
            self.owned = True
            others = [p for p in self.path.iterdir() if p.name != '.lock']
            if not self.resume and others:
                raise FileExistsError(f"Output changed while acquiring lock: {self.path}")
            if self.resume and others and not (self.path / 'state.json').is_file():
                raise FileExistsError("Cannot resume an unowned directory without state.json")
            return self.path
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_) -> None:
        if self.owned:
            lock = self.path / '.lock'
            try:
                if json.loads(lock.read_text()).get('token') == self.token:
                    lock.unlink()
            except (FileNotFoundError, ValueError):
                pass
            self.owned = False
        if self.lock_reservation is not None:
            self.lock_reservation.close()
            self.lock_reservation = None


class JobLog:
    """Per-job diagnostics; call only after acquiring that job's process lock."""
    def __init__(self, directory: Path, *, filename: str = 'diagnostics.log'):
        self.directory = directory
        if Path(filename).name != filename:
            raise ValueError('Diagnostic filename must be a basename')
        self.filename = filename
        self.handler = None

    def __enter__(self):
        import logging
        path = self.directory / self.filename
        if path.is_symlink():
            raise FileExistsError('Diagnostic log must not be a symlink')
        self.handler = logging.FileHandler(path, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        self.handler.setLevel(logging.DEBUG)
        self.logger = logging.getLogger('framecleave')
        self.previous = self.logger.level
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, *_):
        if self.handler:
            self.logger.removeHandler(self.handler)
            self.handler.close()
            self.logger.setLevel(self.previous)
