"""Playback-order compatibility for Shokz MP3 players, independent of Qt and I/O.

Shokz documents two behaviours that disagree: the help article says to name files in the wanted
order, sort by name and copy them in that order; the OpenSwim Pro FAQ says MP3 mode plays by
transmission time. The component therefore applies both: zero-padded name prefixes (so the order
is visible and sorts correctly by name) and strictly sequential publication in that order.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .naming import sanitize_component

MIN_DIGITS = 2
_PREFIX = re.compile(r"^(\d{1,6}) - ")


def digits_for(total: int) -> int:
    return max(MIN_DIGITS, len(str(max(total, 1))))


def ordered_name(position: int, total: int, title: str, *, suffix: str = ".mp3") -> str:
    """`position` is 1-based; the prefix is wide enough for `total` so names sort lexically."""
    if position < 1:
        raise ValueError("Playback positions start at 1")
    width = digits_for(max(total, position))
    return f"{position:0{width}d} - " + sanitize_component(title, max_bytes=170) + suffix


def position_of(name: str) -> int | None:
    match = _PREFIX.match(name)
    return int(match.group(1)) if match else None


def next_position(folder: Path) -> int:
    """First free playback position after the numbered MP3 files already in `folder`."""
    highest = 0
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 1
    for path in entries:
        if path.suffix.casefold() == ".mp3" and not path.is_symlink():
            highest = max(highest, position_of(path.name) or 0)
    return highest + 1


class OrderGate:
    """Releases work strictly by position, so a slow early item never lets a later one jump ahead.

    Items announce readiness with `ready` or give up with `skip`; the gate never blocks a worker
    thread, it only decides when each release callback may run.
    """

    def __init__(self, first: int = 0) -> None:
        self._next = first
        self._ready: dict[int, Callable[[], None]] = {}
        self._skipped: set[int] = set()
        self._lock = threading.Lock()
        self._draining = False

    def ready(self, position: int, release: Callable[[], None]) -> None:
        with self._lock:
            if position < self._next or position in self._skipped:
                return
            self._ready[position] = release
        self._drain()

    def passed(self, position: int) -> bool:
        with self._lock:
            return position < self._next

    def skip(self, position: int) -> None:
        with self._lock:
            if position < self._next:
                return
            self._skipped.add(position)
            self._ready.pop(position, None)
        self._drain()

    def _drain(self) -> None:
        with self._lock:
            if self._draining:
                return
            self._draining = True
        while True:
            with self._lock:
                while self._next in self._skipped:
                    self._skipped.remove(self._next)
                    self._next += 1
                release = self._ready.pop(self._next, None)
                if release is None:
                    self._draining = False
                    return
                self._next += 1
            try:
                release()
            except BaseException:
                with self._lock:
                    self._draining = False
                raise


@dataclass(frozen=True)
class OrderedItem:
    position: int
    title: str


def plan_names(titles: Iterable[str], *, start: int = 1, total: int | None = None) -> list[str]:
    values = list(titles)
    count = total if total is not None else start - 1 + len(values)
    return [ordered_name(start + i, count, title) for i, title in enumerate(values)]
