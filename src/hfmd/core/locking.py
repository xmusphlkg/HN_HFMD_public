"""Small, process-safe advisory file locks for run and publish boundaries."""

from __future__ import annotations

import json
import os
import socket
import stat
import time
from pathlib import Path
from types import TracebackType

try:
    import fcntl
except ImportError as exc:  # pragma: no cover - the supported platform is Linux
    raise RuntimeError("hfmd.core.locking requires POSIX fcntl locks") from exc


class LockTimeout(TimeoutError):
    """Raised when an advisory lock cannot be acquired before its deadline."""


class FileLock:
    """Exclusive advisory lock whose ownership is tied to an open descriptor."""

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 60.0,
        poll_interval: float = 0.1,
    ) -> None:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.path = Path(path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._descriptor: int | None = None

    @property
    def acquired(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> FileLock:
        if self.acquired:
            raise RuntimeError(f"Lock instance is already acquired: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = os.lstat(self.path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            os.close(descriptor)
            raise RuntimeError(f"Lock path is not a safe single-link regular file: {self.path}")
        os.fchmod(descriptor, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise LockTimeout(f"Timed out acquiring lock: {self.path}") from None
                time.sleep(min(self.poll_interval, max(0.0, deadline - time.monotonic())))
        self._descriptor = descriptor
        current = os.lstat(self.path)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            self._descriptor = None
            raise RuntimeError(f"Lock path changed during acquisition: {self.path}")
        metadata = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_unix": time.time(),
        }
        encoded = (json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n").encode()
        os.ftruncate(descriptor, 0)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
        return self

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> FileLock:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
