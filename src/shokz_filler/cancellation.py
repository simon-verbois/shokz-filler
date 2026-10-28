"""Cooperative cancellation for blocking service calls, independent of Qt."""

from __future__ import annotations

import threading
from contextvars import ContextVar

current_cancellation: ContextVar[threading.Event | None] = ContextVar("cancellation", default=None)


def check_cancelled() -> None:
    event = current_cancellation.get()
    if event is not None and event.is_set():
        raise InterruptedError("Operation cancelled")
