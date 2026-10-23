import wave
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from shokz_refill.audiobook_models import Audiobook, AudioSource, export_plan
from shokz_refill.audiobook_normalizer import AudiobookNormalizer
from shokz_refill.book_export import BookExportOptions
from shokz_refill.metadata import read_identity


class FakeSpeech:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text, output, voice, rate, cancelled):  # type: ignore[no-untyped-def]
        self.texts.append(text)
        with wave.open(str(output), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            handle.writeframes(b"\0\0" * 2205)
        return output


def test_merged_mp3_contains_speech_silence_then_sources_in_server_order(tmp_path: Path) -> None:
    book = Audiobook(
        "id",
        "Book",
        "Author",
        sources=(AudioSource(1, "z.m4b", "/1", 10), AudioSource(2, "a.mp3", "/2", 10)),
    )
    part = export_plan(book)[0]
    commands: list[list[str]] = []
    manifests: list[str] = []

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        commands.append(command)
        if "concat" in command:
            manifests.append(Path(command[command.index("-i") + 1]).read_text())
        ID3().save(command[-1])

    speech = FakeSpeech()
    normalizer = AudiobookNormalizer(runner, lambda _p: None, lambda _name: Path("fake"), speech)
    output = normalizer.convert(
        part,
        book,
        {1: tmp_path / "z.m4b", 2: tmp_path / "a.mp3"},
        tmp_path / part.filename,
        "source-id",
        1,
        lambda: False,
    )
    assert speech.texts == ["Book, de Author."]
    assert "apad=pad_dur=3" in commands[0]
    assert str(tmp_path / "z.m4b") in commands[1]
    assert str(tmp_path / "a.mp3") in commands[2]
    assert manifests == [
        "ffconcat version 1.0\nfile 'introduction.mp3'\n"
        "file 'normalized-00001.mp3'\nfile 'normalized-00002.mp3'\n"
    ]
    assert commands[-1][commands[-1].index("-codec:a") + 1] == "copy"
    for command in commands[:-1]:
        for option, value in (("-b:a", "192k"), ("-ar", "44100"), ("-ac", "2")):
            assert command[command.index(option) + 1] == value
    tags = ID3(output)
    assert tags.version[:2] == (2, 3)
    assert str(tags["TRCK"]) == "1/1" and str(tags["TALB"]) == "Book"
    assert read_identity(output).source_id == "source-id"


def test_disabling_announcement_does_not_invoke_speech_or_add_silence(tmp_path: Path) -> None:
    book = Audiobook("id", "Book", sources=(AudioSource(1, "source.mp3", "/1", 1),))
    commands: list[list[str]] = []

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        commands.append(command)
        ID3().save(command[-1])

    speech = FakeSpeech()
    normalizer = AudiobookNormalizer(runner, lambda _p: None, lambda _name: Path("fake"), speech)
    part = export_plan(book)[0]
    normalizer.convert(
        part,
        book,
        {1: tmp_path / "source.mp3"},
        tmp_path / part.filename,
        "id",
        1,
        lambda: False,
        options=BookExportOptions(announce=False),
    )
    assert speech.texts == []
    assert len(commands) == 2
    assert all("apad=pad_dur=3" not in command for command in commands)


def test_cancelled_conversion_never_publishes_book(tmp_path: Path) -> None:
    book = Audiobook("id", "Book", sources=(AudioSource(1, "source.mp3", "/1", 1),))

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        Path(command[-1]).write_bytes(b"unfinished")
        raise InterruptedError("Cancelled")

    normalizer = AudiobookNormalizer(
        runner, lambda _p: None, lambda _name: Path("fake"), FakeSpeech()
    )
    part = export_plan(book)[0]
    with pytest.raises(InterruptedError):
        normalizer.convert(
            part,
            book,
            {1: tmp_path / "source.mp3"},
            tmp_path / part.filename,
            "id",
            1,
            lambda: False,
            options=BookExportOptions(announce=False),
        )
    assert not (tmp_path / part.filename).exists()
    assert not list(tmp_path.glob("*.encoding.mp3"))


def test_progress_includes_normalization_and_final_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = Audiobook("id", "Book", sources=(AudioSource(1, "source.mp3", "/1", 10),))
    seen: list[int] = []

    def process(command, cancelled, *, poll):  # type: ignore[no-untyped-def]
        progress_file = Path(command[command.index("-progress") + 1])
        progress_file.write_text("out_time_us=5000000\nprogress=continue\n")
        poll()
        ID3().save(command[-1])

    monkeypatch.setattr("shokz_refill.audiobook_normalizer.run_process", process)
    normalizer = AudiobookNormalizer(
        validator=lambda _p: None, binary=lambda _name: Path("fake"), speech=FakeSpeech()
    )
    part = export_plan(book)[0]
    normalizer.convert(
        part,
        book,
        {1: tmp_path / "source.mp3"},
        tmp_path / part.filename,
        "id",
        1,
        lambda: False,
        seen.append,
        BookExportOptions(announce=False),
    )
    assert seen == [0, 45, 95, 100]
    assert not list(tmp_path.glob("*.progress"))


def test_oversized_merged_book_fails_before_launching_a_process(tmp_path: Path) -> None:
    book = Audiobook("id", "Long Book", sources=(AudioSource(1, "source.mp3", "/1", 200_000),))

    def unexpected(*args):  # type: ignore[no-untyped-def]
        raise AssertionError("Process must not run")

    normalizer = AudiobookNormalizer(unexpected, lambda _p: None, lambda _name: Path("fake"))
    with pytest.raises(ValueError, match="4 GiB"):
        normalizer.convert(
            export_plan(book)[0],
            book,
            {1: tmp_path / "source.mp3"},
            tmp_path / "book.mp3",
            "id",
            1,
            lambda: False,
        )


def test_many_sources_use_a_manifest_and_bounded_commands(tmp_path: Path) -> None:
    book = Audiobook(
        "id",
        "Many files",
        sources=tuple(
            AudioSource(index, f"{index}.mp3", f"/{index}", 1) for index in range(1, 121)
        ),
    )
    commands: list[list[str]] = []
    manifests: list[str] = []

    def runner(command, cancelled):  # type: ignore[no-untyped-def]
        commands.append(command)
        if "concat" in command:
            manifests.append(Path(command[command.index("-i") + 1]).read_text())
        ID3().save(command[-1])

    part = export_plan(book)[0]
    normalizer = AudiobookNormalizer(runner, lambda _p: None, lambda _name: Path("fake"))
    normalizer.convert(
        part,
        book,
        {s.index: tmp_path / s.filename for s in book.sources},
        tmp_path / part.filename,
        "id",
        1,
        lambda: False,
        options=BookExportOptions(announce=False),
    )
    assert len(commands) == 121
    assert max(len(" ".join(command)) for command in commands) < 4000
    assert len(manifests[0].splitlines()) == 121
    assert manifests[0].endswith("file 'normalized-00120.mp3'\n")
