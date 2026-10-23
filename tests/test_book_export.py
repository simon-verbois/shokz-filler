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
    silent = replace(options, announce=False)
    assert silent.fingerprint("Book", "Author") == replace(silent, template="ignored").fingerprint(
        "Book", "Author"
    )
    assert silent.text("Book", "Author") == ""


def test_missing_author_has_a_readable_announcement() -> None:
    assert BookExportOptions().text("Book", "") == "Book, de auteur inconnu."
