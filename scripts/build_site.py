"""Generate and validate five static language pages using only the standard library."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://simon-verbois.github.io/shokz-filler/"
LANGUAGES = {
    "en": "English",
    "fr": "Français",
    "nl": "Nederlands",
    "de": "Deutsch",
    "es": "Español",
}
PAGES = ("index.html", *(f"{language}/index.html" for language in LANGUAGES if language != "en"))
ASSETS = (
    "styles.css",
    "site.js",
    "favicon.svg",
    ".nojekyll",
    *(
        f"screenshots/{name}.png"
        for name in ("music", "audiobooks", "device", "settings", "book-export")
    ),
)
FILES = (*PAGES, *ASSETS)
SOURCE_FILES = ("site-template.html", *(f"locales/{language}.json" for language in LANGUAGES))
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def page_path(language: str) -> str:
    return "" if language == "en" else f"{language}/"


class TranslationKeys(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.keys = {"language.label"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.keys.update(value for key, value in attrs if key.startswith("data-i18n") and value)


class InlineMarkup(HTMLParser):
    """Catch accidental links, event handlers or scripts in translated prose."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"br", "em", "strong", "code", "kbd", "span", "i"}:
            raise ValueError(f"Unsupported translation markup: {tag}")
        if any(name not in {"class", "aria-hidden", "translate"} for name, _value in attrs):
            raise ValueError("Unsupported translation attributes")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("Unbalanced translation markup")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)


def language_picker(language: str, label: str) -> str:
    prefix = "./" if language == "en" else "../"
    links = "".join(
        f'<li><a href="{prefix}{page_path(code)}" lang="{code}" hreflang="{code}"'
        + (' aria-current="page"' if code == language else "")
        + f">{name}</a></li>"
        for code, name in LANGUAGES.items()
    )
    return (
        '<details class="language-picker"><summary aria-label="'
        + html.escape(label + ": " + LANGUAGES[language], quote=True)
        + '"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle>'
        '<ellipse cx="12" cy="12" rx="4" ry="9"></ellipse><path d="M3 12h18"></path></svg>'
        f'<span>{LANGUAGES[language]}</span><span aria-hidden="true">⌄</span></summary>'
        f"<ul>{links}</ul></details>"
    )


class LocalizedPage(HTMLParser):
    def __init__(self, language: str, catalogue: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self.language = language
        self.catalogue = catalogue
        self.output: list[str] = []
        self.skipped_depth = 0

    def handle_decl(self, declaration: str) -> None:
        self.output.append(f"<!{declaration}>\n")

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if self.skipped_depth:
            if tag not in VOID_TAGS:
                self.skipped_depth += 1
            return
        original = dict(attributes)
        attrs = {key: value for key, value in attributes if not key.startswith("data-i18n")}
        for key, value in original.items():
            if key.startswith("data-i18n-") and value:
                attrs[key.removeprefix("data-i18n-")] = self.catalogue[value]
        if tag == "html":
            attrs["lang"] = self.language
        if tag == "link" and attrs.get("rel") == "canonical":
            attrs["href"] = BASE_URL + page_path(self.language)
        if tag == "meta" and attrs.get("property") == "og:url":
            attrs["content"] = BASE_URL + page_path(self.language)
        if self.language != "en":
            for key in ("href", "src"):
                target = attrs.get(key)
                if (
                    target
                    and target != "./"
                    and not target.startswith("#")
                    and not urlsplit(target).scheme
                ):
                    attrs[key] = "../" + target
        rendered = "".join(
            f" {key}" if value is None else f' {key}="{html.escape(value, quote=True)}"'
            for key, value in attrs.items()
        )
        self.output.append(f"<{tag}{rendered}>")
        if key := original.get("data-i18n"):
            self.output.append(self.catalogue[key])
            if tag not in VOID_TAGS:
                self.skipped_depth = 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skipped_depth:
            self.skipped_depth -= 1
            if self.skipped_depth:
                return
        if tag == "head":
            self.output.extend(
                f'<link rel="alternate" hreflang="{language}" '
                f'href="{BASE_URL}{page_path(language)}">\n'
                for language in LANGUAGES
            )
            self.output.append(f'<link rel="alternate" hreflang="x-default" href="{BASE_URL}">\n')
        if tag == "header":
            self.output.append("</div>")
        self.output.append(f"</{tag}>")
        if tag == "nav":
            self.output.append('<div class="header-actions">')
            self.output.append(language_picker(self.language, self.catalogue["language.label"]))

    def handle_data(self, data: str) -> None:
        if not self.skipped_depth:
            self.output.append(html.escape(data, quote=False))


def render_pages(source: Path) -> dict[str, str]:
    for name in SOURCE_FILES:
        path = source / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(source.resolve())
        ):
            raise ValueError(f"Missing or unsafe translation source: {name}")
    template = (source / "site-template.html").read_text(encoding="utf-8")
    keys = TranslationKeys()
    keys.feed(template)
    pages = {}
    for language in LANGUAGES:
        catalogue = json.loads(
            (source / "locales" / f"{language}.json").read_text(encoding="utf-8")
        )
        if not isinstance(catalogue, dict) or set(catalogue) != keys.keys:
            raise ValueError(f"Incomplete or stale {language} translation catalogue")
        for key, value in catalogue.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Empty {language} translation: {key}")
            if key.startswith("copy-") or key == "example.template":
                fragment = InlineMarkup()
                fragment.feed(value)
                if fragment.stack:
                    raise ValueError(f"Unbalanced {language} translation: {key}")
        page = LocalizedPage(language, catalogue)
        page.feed(template)
        if page.skipped_depth:
            raise ValueError("Unclosed translation element in template")
        pages[page_path(language) + "index.html"] = "".join(page.output)
    return pages


def generate(source: Path) -> None:
    # Resolve all catalogues before writing, so a missing translation cannot leave mixed versions.
    for name, content in render_pages(source).items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print("Generated five complete static language pages")


def check_generated(source: Path) -> None:
    for name, content in render_pages(source).items():
        target = source / name
        if not target.is_file() or target.read_text(encoding="utf-8") != content:
            raise ValueError(
                f"Stale generated page: {name}; run python3 scripts/build_site.py --generate"
            )


class PageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []
        self.ids: set[str] = set()
        self.headings = 0
        self.language = ""

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if tag == "html":
            self.language = attrs.get("lang") or ""
        if identifier := attrs.get("id"):
            if identifier in self.ids:
                raise ValueError(f"Duplicate HTML id: {identifier}")
            self.ids.add(identifier)
        if tag == "h1":
            self.headings += 1
        if tag == "img" and (
            "alt" not in attrs or not attrs.get("width") or not attrs.get("height")
        ):
            raise ValueError("Every image needs alt, width and height attributes")
        for attribute in ("href", "src"):
            if target := attrs.get(attribute):
                self.references.append(target)


def validate(source: Path) -> None:
    source = source.resolve()
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(f"Missing or unsafe public asset: {name}")
    pages: dict[Path, PageLinks] = {}
    for language, name in zip(LANGUAGES, PAGES, strict=True):
        page = PageLinks()
        page.feed((source / name).read_text(encoding="utf-8"))
        if page.headings != 1 or page.language != language:
            raise ValueError(f"Expected one h1 and html lang={language} in {name}")
        pages[(source / name).resolve()] = page
    for path, page in pages.items():
        for target in page.references:
            parsed = urlsplit(target)
            if parsed.scheme in {"https", "http", "mailto"}:
                continue
            if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
                raise ValueError(f"Unsafe or project-prefix-breaking URL: {target}")
            asset = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if asset.is_dir():
                asset /= "index.html"
            if not asset.is_relative_to(source) or not asset.is_file():
                raise ValueError(f"Missing or out-of-site reference: {target}")
            if asset.relative_to(source).as_posix() not in FILES:
                raise ValueError(f"Reference to an asset outside the public allowlist: {target}")
            if parsed.fragment and (asset not in pages or parsed.fragment not in pages[asset].ids):
                raise ValueError(f"Unknown fragment: {target}")
    print("Five languages, public assets, local links, image attributes and anchors verified")


def build(destination: Path) -> None:
    source = ROOT / "docs"
    destination = destination.resolve()
    if (
        destination == ROOT
        or ROOT.is_relative_to(destination)
        or destination.is_relative_to(source)
    ):
        raise ValueError("Build output must be outside docs and cannot contain the repository")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Build destination must be empty; existing files are never deleted")
    validate(source)
    check_generated(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    validate(destination)
    print(f"Built {len(FILES)} public assets in {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate", action="store_true", help="Regenerate committed language pages"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check translations, pages and local links"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "site")
    args = parser.parse_args()
    try:
        if args.generate:
            generate(ROOT / "docs")
        elif args.check:
            validate(ROOT / "docs")
            check_generated(ROOT / "docs")
        else:
            build(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Website: {error}\n")


if __name__ == "__main__":
    main()
