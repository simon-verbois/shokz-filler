"""Isolated Piper neural synthesis using bundled voices; no Qt, service or network."""

from __future__ import annotations

import hashlib
import json
import sys
import wave
from pathlib import Path

from .book_export import MAX_TEXT_LENGTH, SPEECH_ENGINE_ID, VOICE_MODELS

VOICE_DIRECTORY = Path(__file__).parent / "voices"


def cached_voice_path(directory: Path, text: str, voice: str, rate: int) -> Path:
    """Separate neural voice caches by model, speed and normalization version."""
    key = json.dumps([SPEECH_ENGINE_ID, text, VOICE_MODELS[voice], rate], ensure_ascii=False)
    return directory / (hashlib.sha256(key.encode()).hexdigest() + ".wav")


def valid_voice(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getsampwidth() != 2
                or audio.getnchannels() != 2
                or audio.getframerate() != 44100
                or not 0 < audio.getnframes() <= 600 * 44100
            ):
                return False
            audio.setpos(audio.getnframes() - 1)
            return len(audio.readframes(1)) == 4
    except (OSError, ValueError, wave.Error, EOFError):
        return False


def synthesize(text_path: Path, output: Path, voice: str, rate: int) -> None:
    from piper import PiperVoice, SynthesisConfig

    text = text_path.read_text(encoding="utf-8")
    if (
        not text.strip()
        or len(text) > MAX_TEXT_LENGTH
        or "\0" in text
        or voice not in VOICE_MODELS
        or not 60 <= rate <= 120
    ):
        raise ValueError("Invalid speech request")
    model = VOICE_DIRECTORY / (VOICE_MODELS[voice] + ".onnx")
    if not model.is_file() or not model.with_suffix(".onnx.json").is_file():
        raise FileNotFoundError("Bundled Piper voice is missing")
    engine = PiperVoice.load(model, use_cuda=False)
    # Piper uses duration scaling: 95% speed means a length scale of 100 / 95.
    settings = SynthesisConfig(length_scale=100 / rate, normalize_audio=False)
    with wave.open(str(output), "wb") as handle:
        engine.synthesize_wav(text, handle, syn_config=settings)


def main(arguments: list[str] | None = None) -> int:
    values = sys.argv[1:] if arguments is None else arguments
    try:
        if len(values) != 4:
            raise ValueError("Invalid speech worker arguments")
        synthesize(Path(values[0]), Path(values[1]), values[2], int(values[3]))
        return 0
    except Exception:
        print(
            "Local Piper speech synthesis failed; check bundled voices and runtime", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
