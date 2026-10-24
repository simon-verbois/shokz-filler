"""Voice preview for the speech settings: local synthesis and playback off the UI thread."""

from __future__ import annotations

import uuid
import wave
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from .audio_playback import Playback, play_wav
from .background import TaskRunner
from .book_dialogs import SpeechSettingsPanel
from .book_export import BookExportOptions
from .cancellation import current_cancellation
from .speech import PiperSpeech

_EXAMPLE_BOOK = ("Les Misérables", "Victor Hugo")


class VoicePreview(QObject):
    """Synthesizes the example announcement, plays it, and stops on a second request."""

    def __init__(
        self,
        tasks: TaskRunner,
        cache_dir: Path,
        panel: SpeechSettingsPanel,
        speech: Callable[[Path], PiperSpeech] = lambda cache: PiperSpeech(cache_dir=cache),
        player: Callable[[Path], Playback] = play_wav,
    ) -> None:
        super().__init__(panel)
        self.tasks = tasks
        self.directory = cache_dir / "preview"
        self.speech_cache = cache_dir / "speech"
        self.panel = panel
        self.speech = speech
        self.player = player
        self.playback: Playback | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.stop)
        panel.previewRequested.connect(self.toggle)

    def toggle(self, options: BookExportOptions) -> None:
        if self.playback is not None or self.tasks.active("preview"):
            self.stop()
            return
        text = options.part_text(1, *_EXAMPLE_BOOK, "Prologue")
        output = self.directory / f"preview-{uuid.uuid4().hex}.wav"
        self.panel.set_preview_state("Stop")

        def produce() -> tuple[Playback, float]:
            self.directory.mkdir(parents=True, exist_ok=True)
            for stale in self.directory.glob("preview-*.wav"):
                stale.unlink(missing_ok=True)
            event = current_cancellation.get()
            path = self.speech(self.speech_cache).synthesize(
                text,
                output,
                options.voice,
                options.rate,
                lambda: event is not None and event.is_set(),
            )
            if event is not None and event.is_set():
                raise InterruptedError("Voice preview cancelled")
            with wave.open(str(path), "rb") as audio:
                seconds = audio.getnframes() / audio.getframerate()
            return self.player(path), seconds

        self.tasks.start(produce, self._playing, self._failed, key="preview")

    def _playing(self, started: tuple[Playback, float]) -> None:
        self.playback, seconds = started
        self.timer.start(int(seconds * 1000) + 400)

    def stop(self) -> None:
        self.tasks.cancel("preview")
        self.timer.stop()
        if self.playback is not None:
            self.playback.stop()
            self.playback = None
        self.panel.set_preview_state("Preview")

    def _failed(self, message: str) -> None:
        self.stop()
        self.panel.set_status(message or "Voice preview failed")
