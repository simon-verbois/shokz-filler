"""Native portable-build validation of offline neural voices and merged MP3 production."""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from .audiobook_models import Audiobook, AudioSource, export_plan
from .audiobook_normalizer import AudiobookNormalizer
from .book_export import BookExportOptions
from .metadata import validate_mp3
from .speech import PiperSpeech
from .tts_worker import valid_voice


def speech_smoke_test() -> int:
    with tempfile.TemporaryDirectory(prefix="shokz-speech-smoke-") as directory:
        root = Path(directory)
        source = root / "source.wav"
        with wave.open(str(source), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22_050)
            handle.writeframes(b"\0\0" * 22_050)
        book = Audiobook(
            "smoke", "Livre de test", "Auteur", sources=(AudioSource(1, source.name, "/unused", 1),)
        )
        output = root / "book.mp3"
        speech = PiperSpeech(cache_dir=root / "speech-cache")
        AudiobookNormalizer(speech=speech).convert(
            export_plan(book)[0],
            book,
            {1: source},
            output,
            "packaging-smoke",
            1,
            lambda: False,
            options=BookExportOptions(),
        )
        validate_mp3(output)
        english = speech.synthesize(
            "Test book, by Author.", root / "english.wav", "en-us", 95, lambda: False
        )
        if not valid_voice(english):
            raise ValueError("Bundled English voice failed")
    return 0
