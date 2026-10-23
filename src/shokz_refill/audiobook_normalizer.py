"""Bounded-memory audiobook assembly with an optional offline neural introduction."""

from __future__ import annotations

import hashlib
import shutil
import wave
from collections.abc import Callable, Mapping
from pathlib import Path

from .audiobook_models import Audiobook, ExportPart, Segment
from .book_export import MAX_MP3_BYTES, SILENCE_SECONDS, BookExportOptions
from .media import Cancelled, Progress, bundled_binary, run_process
from .metadata import read_identity, validate_mp3, write_audiobook_metadata
from .speech import PiperSpeech, SpeechSynthesizer

Runner = Callable[[list[str], Cancelled], None]


class AudiobookNormalizer:
    def __init__(
        self,
        runner: Runner | None = None,
        validator: Callable[[Path], None] = validate_mp3,
        binary: Callable[[str], Path] = bundled_binary,
        speech: SpeechSynthesizer | None = None,
    ) -> None:
        self.runner = runner
        self.validator = validator
        self.binary = binary
        self.speech = speech or PiperSpeech()

    @staticmethod
    def check_size(duration: float) -> None:
        if duration * 24_000 + 2 * 1024**2 >= MAX_MP3_BYTES:
            raise ValueError("The merged MP3 would exceed the safe 4 GiB file limit for the device")

    def _cached(self, path: Path, identity: str) -> bool:
        if not path.is_file() or read_identity(path).source_id != identity:
            return False
        try:
            self.validator(path)
            return True
        except (OSError, ValueError):
            return False

    def _encode(
        self,
        arguments: list[str],
        temporary: Path,
        duration: float,
        cancelled: Cancelled,
        progress: Progress,
    ) -> None:
        command = [str(self.binary("ffmpeg")), "-nostdin", "-loglevel", "error", "-xerror", "-y"]
        command += arguments + [str(temporary)]
        progress_file = temporary.with_suffix(".progress")
        last = -1

        def report() -> None:
            nonlocal last
            try:
                with progress_file.open("rb") as handle:
                    handle.seek(0, 2)
                    handle.seek(max(0, handle.tell() - 4096))
                    lines = handle.read().decode("utf-8", errors="replace").splitlines()
                times = [
                    int(line.partition("=")[2]) for line in lines if line.startswith("out_time_us=")
                ]
                if times:
                    value = min(99, max(0, int(times[-1] * 100 / max(duration * 1_000_000, 1))))
                    if value != last:
                        progress(value)
                        last = value
            except (OSError, ValueError):
                pass

        try:
            if cancelled():
                raise InterruptedError("Audiobook conversion cancelled")
            if self.runner is None:
                command[-1:-1] = ["-progress", str(progress_file), "-stats_period", "0.2"]
                run_process(command, cancelled, poll=report)
            else:
                self.runner(command, cancelled)
            if cancelled():
                raise InterruptedError("Audiobook conversion cancelled")
            self.validator(temporary)
        finally:
            progress_file.unlink(missing_ok=True)

    @staticmethod
    def _mp3_options() -> list[str]:
        return [
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-id3v2_version",
            "3",
        ]

    def _component(
        self,
        source: Path,
        segment: Segment,
        output: Path,
        identity: str,
        book: Audiobook,
        total: int,
        ordinal: int,
        cancelled: Cancelled,
        progress: Progress,
    ) -> Path:
        if self._cached(output, identity):
            progress(100)
            return output
        temporary = output.with_suffix(".encoding.mp3")
        try:
            self._encode(
                [
                    "-ss",
                    f"{segment.offset:.6f}",
                    "-t",
                    f"{segment.duration:.6f}",
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    *self._mp3_options(),
                ],
                temporary,
                segment.duration,
                cancelled,
                progress,
            )
            write_audiobook_metadata(
                temporary,
                source_id=identity,
                author=book.author,
                title=book.title,
                book_title=book.title,
                number=ordinal,
                total=total,
            )
            temporary.replace(output)
            return output
        finally:
            temporary.unlink(missing_ok=True)

    def _introduction(
        self, book: Audiobook, cache: Path, options: BookExportOptions, cancelled: Cancelled
    ) -> tuple[Path, float]:
        text = options.text(book.title, book.author)
        identity = "announcement:" + options.fingerprint(book.title, book.author)
        output = cache / "introduction.mp3"
        wave_path = cache / "announcement.wav"
        temporary = output.with_suffix(".encoding.mp3")
        # Regenerate the WAV to measure the exact speech duration.
        try:
            self.speech.synthesize(text, wave_path, options.voice, options.rate, cancelled)
            with wave.open(str(wave_path), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate() + SILENCE_SECONDS
            if not self._cached(output, identity):
                self._encode(
                    [
                        "-i",
                        str(wave_path),
                        "-af",
                        f"apad=pad_dur={SILENCE_SECONDS}",
                        "-map",
                        "0:a:0",
                        *self._mp3_options(),
                    ],
                    temporary,
                    duration,
                    cancelled,
                    lambda _value: None,
                )
                write_audiobook_metadata(
                    temporary,
                    source_id=identity,
                    author=book.author,
                    title="Introduction",
                    book_title=book.title,
                    number=1,
                    total=1,
                )
                temporary.replace(output)
            return output, duration
        finally:
            wave_path.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)

    def convert(
        self,
        part: ExportPart,
        book: Audiobook,
        sources: Mapping[int, Path],
        output: Path,
        source_id: str,
        total_parts: int,
        cancelled: Cancelled,
        progress: Progress = lambda _value: None,
        options: BookExportOptions | None = None,
    ) -> Path:
        options = options or BookExportOptions()
        options.validate()
        if cancelled():
            raise InterruptedError("Audiobook conversion cancelled")
        duration = sum(segment.duration for segment in part.segments)
        self.check_size(duration)
        # Keep a normalized MP3 per input, then remux: no giant filter graph or second lossy encode.
        needed = int(duration * 48_000) + 16 * 1024**2
        if shutil.disk_usage(output.parent).free < needed:
            raise OSError("Not enough local cache space to merge this audiobook")
        pieces: list[Path] = []
        progress(0)
        if options.announce:
            intro, extra = self._introduction(book, output.parent, options, cancelled)
            pieces.append(intro)
            duration += extra
            self.check_size(duration)
        for index, segment in enumerate(part.segments):
            if cancelled():
                raise InterruptedError("Audiobook conversion cancelled")
            component = output.parent / f"normalized-{index + 1:05d}.mp3"
            identity = (
                "component:"
                + hashlib.sha256(
                    f"{source_id}:{segment.source_index}:{segment.offset}:{segment.duration}".encode()
                ).hexdigest()
            )

            def report(percent: int, ordinal: int = index) -> None:
                progress(int((ordinal + percent / 100) * 90 / len(part.segments)))

            pieces.append(
                self._component(
                    sources[segment.source_index],
                    segment,
                    component,
                    identity,
                    book,
                    len(part.segments),
                    index + 1,
                    cancelled,
                    report,
                )
            )
        manifest = output.parent / "merge.ffconcat"
        temporary = output.with_suffix(".encoding.mp3")
        try:
            # Generated basenames avoid manifest injection and Windows command-length limits.
            manifest.write_text(
                "ffconcat version 1.0\n" + "".join(f"file '{piece.name}'\n" for piece in pieces),
                encoding="utf-8",
            )
            self._encode(
                [
                    "-f",
                    "concat",
                    "-safe",
                    "1",
                    "-i",
                    str(manifest),
                    "-map",
                    "0:a:0",
                    "-map_metadata",
                    "-1",
                    "-map_chapters",
                    "-1",
                    "-codec:a",
                    "copy",
                    "-id3v2_version",
                    "3",
                ],
                temporary,
                duration,
                cancelled,
                lambda value: progress(90 + value // 10),
            )
            write_audiobook_metadata(
                temporary,
                source_id=source_id,
                author=book.author,
                title=book.title,
                book_title=book.title,
                number=1,
                total=1,
            )
            self.validator(temporary)
            if temporary.stat().st_size > MAX_MP3_BYTES:
                raise ValueError("The merged MP3 exceeds the safe 4 GiB file limit")
            if cancelled():
                raise InterruptedError("Audiobook conversion cancelled")
            temporary.replace(output)
            progress(100)
            return output
        finally:
            temporary.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
