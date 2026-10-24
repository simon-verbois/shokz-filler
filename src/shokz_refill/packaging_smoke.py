"""Native portable-build validation of offline neural voices and ordered MP3 production."""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from .audiobook_models import Audiobook, AudioSource, export_plan
from .audiobook_normalizer import AudiobookNormalizer
from .book_export import BookExportOptions
from .local_import import LocalMp3Importer
from .media import bundled_binary, run_process
from .metadata import validate_mp3
from .speech import PiperSpeech
from .transfer import TransferManager
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
            "Test book, by Author.", root / "english.wav", "en-us", 100, lambda: False
        )
        if not valid_voice(english):
            raise ValueError("Bundled English voice failed")
        local = root / "local.mp3"
        run_process(
            [
                str(bundled_binary("ffmpeg")),
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-ar",
                "22050",
                "-ac",
                "1",
                str(local),
            ],
            lambda: False,
        )
        device = root / "device"
        device.mkdir()
        LocalMp3Importer(
            root / "local-cache", TransferManager(root / "transfers.json")
        ).import_files([local], device, device)
        validate_mp3(device / local.name)
    return 0
