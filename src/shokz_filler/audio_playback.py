"""Play a short local WAV preview without a Qt multimedia runtime or user-installed codec."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

_LINUX_PLAYERS = (
    ("paplay",),
    ("pw-play",),
    ("aplay", "-q"),
    ("play", "-q"),
    ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"),
)


class Playback(Protocol):
    def stop(self) -> None: ...


class _ProcessPlayback:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()


class _WindowsPlayback:
    """winsound plays one asynchronous sound at a time."""

    def stop(self) -> None:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)  # type: ignore[attr-defined,unused-ignore]


def play_wav(path: Path) -> Playback:
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return _WindowsPlayback()
    for name, *options in _LINUX_PLAYERS:
        executable = shutil.which(name)
        if executable:
            process = subprocess.Popen(
                [executable, *options, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return _ProcessPlayback(process)
    raise RuntimeError(
        "No audio player found. Install PulseAudio/PipeWire (paplay or pw-play) or ALSA (aplay)."
    )
