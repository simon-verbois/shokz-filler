"""Keep the public website build isolated from private and developer files."""

import json
import shutil
from pathlib import Path

import pytest

from scripts import build_site


@pytest.fixture
def website(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repository = tmp_path / "repository"
    source = repository / "docs"
    for name in (*build_site.FILES, *build_site.SOURCE_FILES):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(build_site.ROOT / "docs" / name, target)
    monkeypatch.setattr(build_site, "ROOT", repository)
    return repository


def test_build_excludes_credentials_and_private_docs(website: Path) -> None:
    (website / ".creds").write_text("private")
    (website / "docs" / ".creds").write_text("private")
    (website / "docs" / "development.md").write_text("developer notes")
    output = website / "build" / "site"
    build_site.build(output)
    assert {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()} == set(
        build_site.FILES
    )
    assert (website / ".creds").read_text() == "private"


def test_root_relative_url_fails_instead_of_publishing_a_broken_project_site(website: Path) -> None:
    page = website / "docs" / "index.html"
    page.write_text(page.read_text().replace('href="styles.css"', 'href="/styles.css"'))
    with pytest.raises(ValueError, match="project-prefix"):
        build_site.build(website / "build" / "site")
    assert not (website / "build" / "site").exists()


def test_missing_tutorial_anchor_is_rejected(website: Path) -> None:
    page = website / "docs" / "index.html"
    page.write_text(page.read_text().replace('href="#guide"', 'href="#missing-guide"'))
    with pytest.raises(ValueError, match="Unknown fragment"):
        build_site.validate(website / "docs")


def test_public_symlink_cannot_publish_a_private_file(website: Path) -> None:
    secret = website / ".creds"
    secret.write_text("private")
    asset = website / "docs" / "screenshots" / "music.png"
    asset.unlink()
    try:
        asset.symlink_to(secret)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this platform")
    with pytest.raises(ValueError, match="unsafe public asset"):
        build_site.build(website / "build" / "site")


def test_nonempty_build_directory_is_preserved(website: Path) -> None:
    output = website / "build" / "site"
    output.mkdir(parents=True)
    existing = output / "keep.txt"
    existing.write_text("keep")
    with pytest.raises(ValueError, match="existing files are never deleted"):
        build_site.build(output)
    assert existing.read_text() == "keep"


def test_five_languages_have_local_assets_canonical_urls_and_accessible_copy(website: Path) -> None:
    pages = build_site.render_pages(website / "docs")
    for language, name in zip(build_site.LANGUAGES, build_site.PAGES, strict=True):
        page = pages[name]
        assert f'lang="{language}"' in page
        assert f'href="{build_site.BASE_URL}{build_site.page_path(language)}"' in page
        assert page.count('rel="alternate"') == 6
        assert page.count('hreflang="' + language + '"') == 2
        assert 'aria-current="page"' in page
        assert "data-i18n" not in page
        assert "$book_name" in page and "$author_name" in page
        assert "<strong>Download / transfer selected books</strong>" in page
        if language != "en":
            assert 'src="../screenshots/music.png"' in page
            assert 'href="../styles.css"' in page
    assert '<html lang="en">' in pages["index.html"]
    assert "Your audio." in pages["index.html"]
    assert "Votre audio." in pages["fr/index.html"]
    assert "Je audio." in pages["nl/index.html"]
    assert "Dein Audio." in pages["de/index.html"]
    assert "Tu audio." in pages["es/index.html"]


def test_missing_translation_fails_without_writing_any_pages(website: Path) -> None:
    source = website / "docs"
    original = {name: (source / name).read_bytes() for name in build_site.PAGES}
    path = source / "locales" / "de.json"
    catalogue = json.loads(path.read_text())
    del catalogue["copy-083"]
    path.write_text(json.dumps(catalogue))
    with pytest.raises(ValueError, match="Incomplete or stale de"):
        build_site.generate(source)
    assert original == {name: (source / name).read_bytes() for name in build_site.PAGES}


def test_stale_translated_page_cannot_be_published(website: Path) -> None:
    path = website / "docs" / "es" / "index.html"
    path.write_text(path.read_text() + "\n<!-- stale -->")
    with pytest.raises(ValueError, match="Stale generated page: es/index.html"):
        build_site.build(website / "build" / "site")


def test_translations_cannot_inject_scripts_or_links(website: Path) -> None:
    path = website / "docs" / "locales" / "nl.json"
    catalogue = json.loads(path.read_text())
    catalogue["copy-012"] = "<script>alert(1)</script>"
    path.write_text(json.dumps(catalogue))
    with pytest.raises(ValueError, match="Unsupported translation markup"):
        build_site.render_pages(website / "docs")


def test_unbalanced_inline_translation_is_rejected(website: Path) -> None:
    path = website / "docs" / "locales" / "es.json"
    catalogue = json.loads(path.read_text())
    catalogue["copy-012"] = "<em>Unclosed"
    path.write_text(json.dumps(catalogue))
    with pytest.raises(ValueError, match="Unbalanced es translation"):
        build_site.render_pages(website / "docs")
