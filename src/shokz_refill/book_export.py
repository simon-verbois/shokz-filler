"""Immutable audiobook export choices and safe announcement template rendering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from string import Template

DEFAULT_ANNOUNCEMENT = "$book_name, de $author_name. Chapitre $chapter_number."
DEFAULT_CHAPTER_ANNOUNCEMENT = "Chapitre $chapter_number."
TEMPLATE_VARIABLES = ("book_name", "author_name", "chapter_number", "chapter_title")
# code -> (menu label, bundled Piper model). Codes are persisted in settings: never rename one.
_VOICE_TABLE = {
    "fr": ("Tom — homme, français", "fr_FR-tom-medium"),
    "fr-siwis": ("Siwis — femme, français", "fr_FR-siwis-medium"),
    "en-us": ("John — male, English (US)", "en_US-john-medium"),
    "en-us-kristin": ("Kristin — female, English (US)", "en_US-kristin-medium"),
    "en-gb-cori": ("Cori — female, English (UK)", "en_GB-cori-medium"),
    "de-thorsten": ("Thorsten — Mann, Deutsch", "de_DE-thorsten-medium"),
    "nl-pim": ("Pim — man, Nederlands", "nl_NL-pim-medium"),
    "es-davefx": ("Davefx — hombre, español", "es_ES-davefx-medium"),
}
VOICES = {code: label for code, (label, _model) in _VOICE_TABLE.items()}
VOICE_MODELS = {code: model for code, (_label, model) in _VOICE_TABLE.items()}
SPEECH_ENGINE_ID = "piper-1.8.0-tom-john-v1-loudnorm-16"
SILENCE_SECONDS = 1.5
MAX_TEXT_LENGTH = 2000
MAX_MP3_BYTES = 4 * 1024**3 - 1


def validate_template(text: str) -> None:
    template = Template(text)
    if not text.strip() or len(text) > MAX_TEXT_LENGTH or "\0" in text:
        raise ValueError("Enter an announcement between 1 and 2000 characters")
    if not template.is_valid():
        raise ValueError("Invalid variable syntax. Use $book_name or $$ for a dollar sign")
    unknown = set(template.get_identifiers()) - set(TEMPLATE_VARIABLES)
    if unknown:
        raise ValueError("Unknown variable(s): " + ", ".join(sorted(unknown)))


def announcement_text(
    template: str,
    book_name: str,
    author_name: str,
    chapter_number: int = 1,
    chapter_title: str = "",
) -> str:
    validate_template(template)
    result = Template(template).substitute(
        book_name=book_name,
        author_name=author_name,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
    )
    if not result.strip() or len(result) > MAX_TEXT_LENGTH or "\0" in result:
        raise ValueError("The rendered announcement must contain between 1 and 2000 characters")
    return result


@dataclass(frozen=True)
class BookExportOptions:
    """`announce` speaks `template` before chapter 1; `announce_chapters` speaks
    `chapter_template` before the others (and before chapter 1 when `announce` is off)."""

    announce: bool = True
    template: str = DEFAULT_ANNOUNCEMENT
    voice: str = "fr"
    rate: int = 100
    announce_chapters: bool = True
    chapter_template: str = DEFAULT_CHAPTER_ANNOUNCEMENT

    def validate(self) -> None:
        if self.voice not in VOICES:
            raise ValueError("Choose one of the bundled Piper voices")
        if not 60 <= self.rate <= 120:
            raise ValueError("Speech speed must be between 60% and 120%")
        if self.announce:
            validate_template(self.template)
        if self.announce_chapters:
            validate_template(self.chapter_template)

    def part_text(
        self, part: int, book_name: str, author_name: str, chapter_title: str = ""
    ) -> str:
        """Spoken lead-in of one file, or "" when that file starts directly."""
        self.validate()
        if part == 1 and self.announce:
            template = self.template
        elif self.announce_chapters:
            template = self.chapter_template
        else:
            return ""
        return announcement_text(
            template,
            book_name or "Livre sans titre",
            author_name or "auteur inconnu",
            part,
            chapter_title,
        )

    def text(self, book_name: str, author_name: str) -> str:
        """The first chapter's lead-in."""
        return self.part_text(1, book_name, author_name)

    def fingerprint(
        self, book_name: str, author_name: str, part: int = 1, chapter_title: str = ""
    ) -> str:
        text = self.part_text(part, book_name, author_name, chapter_title)
        data: dict[str, object] = {"layout": "ordered-mp3-v1", "announce": bool(text)}
        if text:
            data.update(
                text=text,
                voice=self.voice,
                rate=self.rate,
                silence=SILENCE_SECONDS,
                engine=SPEECH_ENGINE_ID,
            )
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
