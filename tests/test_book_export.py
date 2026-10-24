from dataclasses import replace

import pytest

from shokz_refill.book_export import BookExportOptions, announcement_text, validate_template


def test_template_uses_book_variables_without_interpreting_book_text_as_code() -> None:
    assert (
        announcement_text("${book_name}, de $author_name. $$", "$literal title", "Auteur")
        == "$literal title, de Auteur. $"
    )


@pytest.mark.parametrize("template", ["", "$unknown", "${book_name", "$", "a\0b", "x" * 2001])
def test_invalid_templates_are_rejected(template: str) -> None:
    with pytest.raises(ValueError):
        validate_template(template)


def test_announcement_settings_change_export_identity_but_disabled_text_does_not() -> None:
    options = BookExportOptions()
    identity = options.fingerprint("Book", "Author")
    assert identity != replace(options, template="Voici $book_name, par $author_name.").fingerprint(
        "Book", "Author"
    )
    assert identity != replace(options, voice="en-us").fingerprint("Book", "Author")
    assert identity != replace(options, rate=85).fingerprint("Book", "Author")
    silent = replace(options, announce=False, announce_chapters=False)
    assert silent.fingerprint("Book", "Author") == replace(silent, template="ignored").fingerprint(
        "Book", "Author"
    )
    assert silent.text("Book", "Author") == ""


def test_missing_author_has_a_readable_announcement() -> None:
    assert BookExportOptions().text("Book", "").startswith("Book, de auteur inconnu.")


def test_every_voice_is_pinned_with_model_config_and_card() -> None:
    import json
    from pathlib import Path

    from shokz_refill.book_export import VOICE_MODELS, VOICES

    assert VOICES.keys() == VOICE_MODELS.keys()
    assert len(set(VOICE_MODELS.values())) == len(VOICE_MODELS)
    manifest = json.loads(
        (Path(__file__).parents[1] / "scripts" / "tts-voices.json").read_text(encoding="utf-8")
    )
    names = {entry["name"] for entry in manifest}
    assert all(len(entry["sha256"]) == 64 for entry in manifest)
    for model in VOICE_MODELS.values():
        assert {f"{model}.onnx", f"{model}.onnx.json", f"{model}.MODEL_CARD.txt"} <= names


def test_first_chapter_and_other_chapters_have_their_own_text() -> None:
    options = BookExportOptions()
    assert options.part_text(1, "Book", "Author", "Intro") == "Book, de Author. Chapitre 1."
    assert options.part_text(2, "Book", "Author", "Two") == "Chapitre 2."
    custom = replace(
        options, template="$book_name. $chapter_title.", chapter_template="N° $chapter_number"
    )
    assert custom.part_text(1, "Book", "Author", "Intro") == "Book. Intro."
    assert custom.part_text(7, "Book", "Author", "Seven") == "N° 7"
    only_first = replace(options, announce_chapters=False)
    assert only_first.part_text(2, "Book", "Author") == ""
    only_others = replace(options, announce=False)
    assert only_others.part_text(1, "Book", "Author") == "Chapitre 1."
    silent = replace(options, announce=False, announce_chapters=False)
    assert silent.part_text(1, "Book", "Author") == ""
    assert options.fingerprint("Book", "Author", 2) != options.fingerprint("Book", "Author", 3)
    assert options.fingerprint("Book", "Author", 2) != replace(
        options, chapter_template="Partie $chapter_number"
    ).fingerprint("Book", "Author", 2)
    assert replace(options, announce_chapters=False).fingerprint("Book", "Author", 2) == (
        replace(options, announce_chapters=False, chapter_template="ignored")
    ).fingerprint("Book", "Author", 2)
    with pytest.raises(ValueError):
        replace(options, chapter_template="$unknown").validate()
