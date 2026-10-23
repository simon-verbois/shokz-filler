"""Shared device mutation lock and filesystem primitives that never replace user data."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")
_DEVICE_LOCK = threading.RLock()


@contextmanager
def device_operation(cancelled: Callable[[], bool] = lambda: False) -> Iterator[None]:
    """Serialize device mutations, allowing queued copies to be cancelled."""
    while not _DEVICE_LOCK.acquire(timeout=0.1):
        if cancelled():
            raise InterruptedError("Operation cancelled while waiting for the device")
    try:
        if cancelled():
            raise InterruptedError("Operation cancelled")
        yield
    finally:
        _DEVICE_LOCK.release()


def serialized(function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with device_operation():
            return function(*args, **kwargs)

    return wrapped


def flush_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        pass  # Not supported by all removable filesystems or Windows.
    finally:
        if descriptor is not None:
            os.close(descriptor)


def rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename without replacement, including on FAT on supported hosts.

    Fail closed if the filesystem cannot guarantee exclusive publication.
    """
    if sys.platform == "win32":
        os.rename(source, destination)  # Windows rename never replaces an existing entry.
        return
    if sys.platform == "linux":
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is not None:
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            rename.restype = ctypes.c_int
            if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
                return
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(destination))
    raise OSError("This platform does not support safe exclusive renaming")
