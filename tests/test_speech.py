import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shokz_refill.book_export import VOICE_MODELS
from shokz_refill.speech import PiperSpeech
from shokz_refill.tts_worker import cached_voice_path, main, synthesize, valid_voice


def write_wave(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\0\0" * 8820)


def make_speech(runner, cache: Path) -> PiperSpeech:  # type: ignore[no-untyped-def]
    return PiperSpeech(runner, cache, lambda _name: Path("ffmpeg"))


def test_private_text_native_speed_normalization_and_cached_reuse(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        commands.append(command)
        if "shokz_refill.tts_worker" in command:
            text = Path(command[-4])
            assert text.read_text() == "Private book, by Author."
            assert command[-2:] == ["en-us", "95"]
            if __import__("os").name == "posix":
                assert text.stat().st_mode & 0o077 == 0
            write_wave(Path(command[-3]))
        else:
            write_wave(Path(command[-1]))

    output = tmp_path / "speech.wav"
    speech = make_speech(runner, tmp_path / "cache")
    speech.synthesize("Private book, by Author.", output, "en-us", 95, lambda: False)
    assert "Private book, by Author." not in commands[0]
    assert "aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=7" in commands[1]
    assert "atempo" not in " ".join(commands[1])
    assert valid_voice(output)
    speech.synthesize("Private book, by Author.", output, "en-us", 95, lambda: False)
    assert len(commands) == 2
    assert not list(tmp_path.glob("*.txt"))
    assert not list(tmp_path.rglob("*.part.*"))


@pytest.mark.parametrize("stage", ["synthesis", "processing"])
def test_cancellation_cleans_partials_preserving_existing_output(
    tmp_path: Path, stage: str
) -> None:
    output = tmp_path / "speech.wav"
    output.write_bytes(b"existing export")

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        if "shokz_refill.tts_worker" in command:
            write_wave(Path(command[-3]))
            if stage == "synthesis":
                raise InterruptedError("Cancelled")
        else:
            write_wave(Path(command[-1]))
            raise InterruptedError("Cancelled")

    with pytest.raises(InterruptedError):
        make_speech(runner, tmp_path / "cache").synthesize(
            "Text",
            output,
            "fr",
            95,
            lambda: False,
        )
    assert output.read_bytes() == b"existing export"
    assert not list(tmp_path.glob("*.txt"))
    assert not list(tmp_path.rglob("*.part.*"))
    assert not list((tmp_path / "cache").iterdir())


def test_failure_does_not_export_a_silent_book_or_echo_private_errors(tmp_path: Path) -> None:
    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        raise RuntimeError("private detail")

    with pytest.raises(RuntimeError, match="Local Piper speech synthesis failed") as error:
        make_speech(runner, tmp_path / "cache").synthesize(
            "Text",
            tmp_path / "speech.wav",
            "fr",
            95,
            lambda: False,
        )
    assert "private detail" not in str(error.value)
    assert not list(tmp_path.rglob("*.part.*"))
    assert not (tmp_path / "speech.wav").exists()


def test_invalid_cached_audio_is_regenerated(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    original = cached_voice_path(cache, "Text", "fr", 95)
    original.write_bytes(b"corrupt audio" * 100)
    seen: list[list[str]] = []

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        seen.append(command)
        write_wave(Path(command[-3] if "shokz_refill.tts_worker" in command else command[-1]))

    make_speech(runner, cache).synthesize("Text", tmp_path / "speech.wav", "fr", 95, lambda: False)
    assert len(seen) == 2
    assert valid_voice(original)
    assert original != cached_voice_path(cache, "Text", "en-us", 95)
    assert original != cached_voice_path(cache, "Text", "fr", 80)


def test_invalid_processed_wave_is_not_cached_or_exported(tmp_path: Path) -> None:
    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        if "shokz_refill.tts_worker" in command:
            write_wave(Path(command[-3]))
        else:
            Path(command[-1]).write_bytes(b"invalid audio")

    with pytest.raises(RuntimeError, match="Local Piper speech"):
        make_speech(runner, tmp_path / "cache").synthesize(
            "Text",
            tmp_path / "speech.wav",
            "fr",
            95,
            lambda: False,
        )
    assert not list((tmp_path / "cache").iterdir())
    assert not list(tmp_path.glob("*.part.*"))


def test_piper_worker_loads_bundled_male_voice_and_scales_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / (VOICE_MODELS["fr"] + ".onnx")
    model.touch()
    model.with_suffix(".onnx.json").touch()
    monkeypatch.setattr("shokz_refill.tts_worker.VOICE_DIRECTORY", tmp_path)
    engine = Mock()

    def write_raw(text, handle, **kwargs):  # type: ignore[no-untyped-def]
        handle.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0\0" * 100)

    engine.synthesize_wav.side_effect = write_raw
    load = Mock(return_value=engine)
    settings = Mock(return_value=object())
    monkeypatch.setitem(
        sys.modules,
        "piper",
        SimpleNamespace(
            PiperVoice=SimpleNamespace(load=load),
            SynthesisConfig=settings,
        ),
    )
    text = tmp_path / "text.txt"
    text.write_text("Bonjour")
    synthesize(text, tmp_path / "out.wav", "fr", 95)
    load.assert_called_once_with(model, use_cuda=False)
    settings.assert_called_once_with(length_scale=100 / 95, normalize_audio=False)
    assert engine.synthesize_wav.call_args.args[0] == "Bonjour"
    assert engine.synthesize_wav.call_args.kwargs["syn_config"] is settings.return_value


def test_truncated_wave_is_not_a_valid_cache_entry(tmp_path: Path) -> None:
    path = tmp_path / "voice.wav"
    write_wave(path)
    path.write_bytes(path.read_bytes()[:-10])
    assert not valid_voice(path)


def test_worker_errors_do_not_echo_book_text(monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def fail(*args):  # type: ignore[no-untyped-def]
        raise RuntimeError("private title must not be printed")

    monkeypatch.setattr("shokz_refill.tts_worker.synthesize", fail)
    assert main(["text", "output", "fr", "95"]) == 1
    assert "private title" not in capsys.readouterr().err


def test_already_cancelled_speech_does_not_start_worker(tmp_path: Path) -> None:
    runner = Mock()
    with pytest.raises(InterruptedError):
        make_speech(runner, tmp_path / "cache").synthesize(
            "Text",
            tmp_path / "speech.wav",
            "fr",
            95,
            lambda: True,
        )
    runner.assert_not_called()
    assert not list(tmp_path.iterdir())
