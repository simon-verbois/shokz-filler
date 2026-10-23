"""Immutable audiobook export choices and safe announcement template rendering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from string import Template

DEFAULT_ANNOUNCEMENT = "$book_name, de $author_name."
VOICES = {"fr": "Tom — homme, français", "en-us": "John — male, English"}
VOICE_MODELS = {"fr": "fr_FR-tom-medium", "en-us": "en_US-john-medium"}
SPEECH_ENGINE_ID = "piper-1.8.0-tom-john-v1-loudnorm-16"
SILENCE_SECONDS = 3
MAX_TEXT_LENGTH = 2000
MAX_MP3_BYTES = 4 * 1024**3 - 1


def validate_template(text: str) -> None:
    template = Template(text)
    if not text.strip() or len(text) > MAX_TEXT_LENGTH or "\0" in text:
        raise ValueError("Enter an announcement between 1 and 2000 characters")
    if not template.is_valid():
        raise ValueError(
            "Invalid variable syntax. Use $book_name, $author_name, or $$ for a dollar sign"
        )
    unknown = set(template.get_identifiers()) - {"book_name", "author_name"}
    if unknown:
        raise ValueError("Unknown variable(s): " + ", ".join(sorted(unknown)))


def announcement_text(template: str, book_name: str, author_name: str) -> str:
    validate_template(template)
    result = Template(template).substitute(book_name=book_name, author_name=author_name)
    if not result.strip() or len(result) > MAX_TEXT_LENGTH or "\0" in result:
        raise ValueError("The rendered announcement must contain between 1 and 2000 characters")
    return result


@dataclass(frozen=True)
class BookExportOptions:
    announce: bool = True
    template: str = DEFAULT_ANNOUNCEMENT
    voice: str = "fr"
    rate: int = 95

    def validate(self) -> None:
        if self.voice not in VOICES:
            raise ValueError("Choose one of the bundled Piper voices")
        if not 60 <= self.rate <= 120:
            raise ValueError("Speech speed must be between 60% and 120%")
        if self.announce:
            validate_template(self.template)

    def text(self, book_name: str, author_name: str) -> str:
        self.validate()
        return (
            announcement_text(
                self.template, book_name or "Livre sans titre", author_name or "auteur inconnu"
            )
            if self.announce
            else ""
        )

    def fingerprint(self, book_name: str, author_name: str) -> str:
        data: dict[str, object] = {"layout": "single-mp3-v1", "announce": self.announce}
        if self.announce:
            data.update(
                text=self.text(book_name, author_name),
                voice=self.voice,
                rate=self.rate,
                silence=SILENCE_SECONDS,
                engine=SPEECH_ENGINE_ID,
            )
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
