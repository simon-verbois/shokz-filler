"""Small bundled line icons rendered by Qt, with no theme or network dependency."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "music": '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
    "book": '<path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1v15"/>',
    "folder": '<path d="M3 7V5h7l2 3h9v12H3V7z"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 '
        "0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 "
        "1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82"
        ".33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 "
        "1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 "
        "0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 "
        "1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 "
        "1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 "
        "1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 "
        '1.65 0 0 0-1.51 1z"/>'
    ),
    "headphones": '<path d="M4 14v-3a8 8 0 0 1 16 0v3M4 12H2v8h5v-8H4m16 0h2v8h-5v-8h3"/>',
    "refresh": '<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6"/>',
    "search": '<circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/>',
    "back": '<path d="m15 5-7 7 7 7"/>',
    "forward": '<path d="m9 5 7 7-7 7"/>',
    "up": '<path d="m5 15 7-7 7 7"/>',
    "down": '<path d="m5 9 7 7 7-7"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "more": (
        '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
    ),
    "check": '<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M12 6v7m0 3v1"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 3v.1"/>',
    "minimize": '<path d="M6 12h12"/>',
    "maximize": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "restore": '<rect x="5" y="9" width="10" height="10" rx="1.5"/><path d="M9 9V6h10v10h-4"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "filter": '<path d="M3 5h18M6 12h12M9 19h6"/>',
}


_SIZES = (16, 20, 24, 28, 32, 40, 48, 64)


@lru_cache(maxsize=128)
def icon(name: str, color: str = "#c9d3df") -> QIcon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    # One crisp pixmap per common size, so Qt never has to rescale a bitmap (blurry arrows).
    for size in _SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


# Mirrors assets/logo.svg (a test keeps both identical); embedded so no data file is needed.
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
  <rect width="48" height="48" rx="13" fill="#0b1119" />
  <rect x="1" y="1" width="46" height="46" rx="12" fill="none" stroke="#2b3441" stroke-width="2" />
  <g transform="translate(7 7) scale(1.4167)" fill="none" stroke="#32d4cf" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M4 14v-3a8 8 0 0 1 16 0v3M4 12H2v8h5v-8H4m16 0h2v8h-5v-8h3" />
  </g>
</svg>
"""  # noqa: E501


def logo_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(LOGO_SVG.encode())).render(painter)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(logo_pixmap(size))
    return result
