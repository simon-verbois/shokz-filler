"""One place for accounts and preferences, so connections are not scattered across pages."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .page_layout import PageTemplate
from .theme import role


class SettingsPage(PageTemplate):
    authRequested = Signal()
    disconnectRequested = Signal()

    def __init__(
        self,
        audiobookshelf_card: QWidget,
        speech: QWidget,
        save_button: QPushButton,
        mono: bool = False,
    ) -> None:
        super().__init__("Settings", controls=False, subtitle=False)
        self.scroll_area = QScrollArea()
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.content.addWidget(self.scroll_area)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(10)
        layout.addWidget(self._section("Accounts"))
        layout.addWidget(self._youtube_card())
        layout.addSpacing(8)
        layout.addWidget(self._section("Audiobookshelf"))
        layout.addWidget(audiobookshelf_card)
        layout.addSpacing(8)
        layout.addWidget(self._section("Audio"))
        layout.addWidget(self._audio_card(mono))
        layout.addSpacing(8)
        layout.addWidget(self._section("Audiobook announcement"))
        layout.addWidget(speech)
        layout.addStretch()
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(body, 1)
        self.scroll_area.setWidget(page)
        self.save_button = save_button
        self.footer.addStretch()
        self.footer.addWidget(save_button)
        self.speech = speech
        self.mono_check.toggled.connect(self.refresh_save)
        if hasattr(speech, "changed"):
            speech.changed.connect(self.refresh_save)
        self.refresh_save()

    def _audio_card(self, mono: bool) -> QFrame:
        card = QFrame()
        role(card, "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        self.mono_check = QCheckBox("Convert audio to mono")
        self.mono_saved = mono
        self.mono_check.setChecked(mono)
        note = QLabel(
            "Mixes both channels into one for songs, audiobooks and imported MP3s. "
            "Applies to new conversions once saved; off keeps stereo."
        )
        note.setWordWrap(True)
        role(note, "caption")
        layout.addWidget(self.mono_check)
        layout.addWidget(note)
        return card

    def refresh_save(self) -> None:
        """Save is on only when something differs from what is stored and the texts are valid."""
        speech = self.speech
        modified = getattr(speech, "modified", False) or (
            self.mono_check.isChecked() != self.mono_saved
        )
        self.save_button.setEnabled(bool(getattr(speech, "is_valid", True)) and modified)

    def mark_saved(self, mono: bool) -> None:
        self.mono_saved = mono
        self.refresh_save()

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        role(label, "section")
        return label

    def _youtube_card(self) -> QFrame:
        card = QFrame()
        role(card, "card")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        name = QLabel("YouTube Music")
        role(name, "strong")
        self.auth_label = QLabel()
        role(self.auth_label, "muted")
        self.auth_label.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(self.auth_label)
        row.addLayout(text, 1)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.authRequested.emit)
        self.disconnect_button = QPushButton("Disconnect")
        role(self.disconnect_button, "quiet")
        self.disconnect_button.clicked.connect(self.disconnectRequested.emit)
        row.addWidget(self.connect_button)
        row.addWidget(self.disconnect_button)
        return card
