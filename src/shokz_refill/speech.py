"""Cached offline neural speech with cancellable synthesis and volume normalization."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .book_export import MAX_TEXT_LENGTH, VOICES
from .config import ConfigStore
from .media import Cancelled, bundled_binary, run_process
from .tts_worker import cached_voice_path, valid_voice


class SpeechSynthesizer(Protocol):
    def synthesize(
        self, text: str, output: Path, voice: str, rate: int, cancelled: Cancelled
    ) -> Path: ...


class PiperSpeech:
    def __init__(
        self,
        runner: Callable[[list[str], Cancelled], None] = run_process,
        cache_dir: Path | None = None,
        binary: Callable[[str], Path] = bundled_binary,
    ) -> None:
        self.runner = runner
        self.cache_dir = cache_dir or ConfigStore().cache_dir / "speech"
        self.binary = binary

    def synthesize(
        self, text: str, output: Path, voice: str, rate: int, cancelled: Cancelled
    ) -> Path:
        if cancelled():
            raise InterruptedError("Speech synthesis cancelled")
        if not text.strip() or len(text) > MAX_TEXT_LENGTH or "\0" in text:
            raise ValueError("Invalid announcement text")
        if voice not in VOICES or not 60 <= rate <= 120:
            raise ValueError("Invalid speech voice or speed")
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        original = cached_voice_path(self.cache_dir, text, voice, rate)
        token = uuid.uuid4().hex
        text_path = output.with_name(f"speech-{token}.txt")
        raw = output.with_name(f"speech-{token}.raw.part.wav")
        temporary = output.with_name(f"speech-{token}.part.wav")
        cached_partial = self.cache_dir / f"{original.stem}.{token}.part.wav"
        command = (
            [sys.executable, "--tts-worker"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "shokz_refill.tts_worker"]
        )
        try:
            if valid_voice(original):
                shutil.copyfile(original, temporary)
            else:
                descriptor = os.open(text_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(text)
                self.runner(command + [str(text_path), str(raw), voice, str(rate)], cancelled)
                if cancelled():
                    raise InterruptedError("Speech synthesis cancelled")
                self.runner(
                    [
                        str(self.binary("ffmpeg")),
                        "-nostdin",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(raw),
                        "-af",
                        "aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=7",
                        "-ac",
                        "2",
                        "-ar",
                        "44100",
                        "-c:a",
                        "pcm_s16le",
                        str(temporary),
                    ],
                    cancelled,
                )
                if cancelled():
                    raise InterruptedError("Speech synthesis cancelled")
                if not valid_voice(temporary):
                    raise ValueError("Piper speech processing produced invalid audio")
                descriptor = os.open(cached_partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle, temporary.open("rb") as source:
                    shutil.copyfileobj(source, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                if cancelled():
                    raise InterruptedError("Speech synthesis cancelled")
                cached_partial.replace(original)
            if cancelled():
                raise InterruptedError("Speech synthesis cancelled")
            temporary.replace(output)
            return output
        except (RuntimeError, ValueError):
            raise RuntimeError(
                "Local Piper speech synthesis failed. Check the bundled voice files and retry; "
                "the book has not been exported without its announcement."
            ) from None
        finally:
            text_path.unlink(missing_ok=True)
            raw.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
            cached_partial.unlink(missing_ok=True)
