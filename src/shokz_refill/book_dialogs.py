"""Per-book export choices and application speech preferences."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .audiobook_models import Audiobook
from .book_export import VOICES, BookExportOptions


class BookExportDialog(QDialog):
    def __init__(
        self, book: Audiobook, defaults: BookExportOptions, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.book = book
        self.defaults = defaults
        self.setWindowTitle("Audiobook export")
        self.resize(520, 320)
        layout = QVBoxLayout(self)
        title = QLabel(f"{book.title}\n{book.author}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        explanation = QLabel(
            "One folder and one MP3 for this book. All audio tracks are merged "
            "in the order provided by Audiobookshelf."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.announcement = QCheckBox("Read the book title and author before the book")
        self.announcement.setChecked(True)
        self.announcement.toggled.connect(self._preview)
        layout.addWidget(self.announcement)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        note = QLabel(
            "The voice and announcement text can be changed in Settings. "
            "Existing exports are preserved; a different export gets a new folder."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Queue book")
        self.buttons.accepted.connect(self.accept)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Skip book")
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._preview()

    @property
    def options(self) -> BookExportOptions:
        return replace(self.defaults, announce=self.announcement.isChecked())

    def _preview(self) -> None:
        try:
            text = self.options.text(self.book.title, self.book.author)
            self.preview.setText(
                f"Announcement: “{text}”\nLocal Piper male voice. "
                "Then 3 seconds of silence, then the book."
                if self.options.announce
                else "The MP3 starts directly with the book."
            )
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except ValueError as exc:
            self.preview.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)


class SpeechSettingsPanel(QWidget):
    saveRequested = Signal(object)

    def __init__(self, settings: BookExportOptions) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        introduction = QLabel(
            "Piper generates audiobook announcements locally with bundled neural male voices. "
            "Generated voices are cached locally and inserted into "
            "the single MP3, followed by 3 seconds of silence."
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        form = QFormLayout()
        self.template = QPlainTextEdit(settings.template)
        self.template.setAccessibleName("Audiobook announcement template")
        self.template.setMaximumHeight(150)
        form.addRow("Announcement text", self.template)
        self.voice = QComboBox()
        for code, label in VOICES.items():
            self.voice.addItem(label, code)
        self.voice.setCurrentIndex(self.voice.findData(settings.voice))
        form.addRow("Voice", self.voice)
        self.rate = QSpinBox()
        self.rate.setRange(60, 120)
        self.rate.setSuffix(" %")
        self.rate.setValue(settings.rate)
        form.addRow("Speech rate", self.rate)
        layout.addLayout(form)
        layout.addWidget(QLabel("Variables: $book_name, $author_name. Use $$ for a literal $."))
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.save = QPushButton("Save settings")
        self.save.clicked.connect(self._save)
        layout.addWidget(self.save)
        layout.addStretch()
        self.template.textChanged.connect(self._preview)
        self.voice.currentIndexChanged.connect(self._preview)
        self.rate.valueChanged.connect(self._preview)
        self._preview()

    @property
    def options(self) -> BookExportOptions:
        return BookExportOptions(
            True, self.template.toPlainText(), str(self.voice.currentData()), self.rate.value()
        )

    def _preview(self) -> None:
        try:
            text = self.options.text("Les Misérables", "Victor Hugo")
            self.preview.setText(f"Example: “{text}” → 3 seconds of silence → book")
            self.save.setEnabled(True)
            self.status.clear()
        except ValueError as exc:
            self.preview.clear()
            self.status.setText(str(exc))
            self.save.setEnabled(False)

    def _save(self) -> None:
        try:
            self.options.validate()
            self.status.setText("Saving settings…")
            self.saveRequested.emit(self.options)
        except ValueError as exc:
            self.status.setText(str(exc))
