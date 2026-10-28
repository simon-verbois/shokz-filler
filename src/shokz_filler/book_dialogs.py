"""Per-book export choices and application speech preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .book_export import SILENCE_SECONDS, VOICES, BookExportOptions
from .icons import icon
from .theme import ON_ACCENT, RoundedComboBox, role


class SpeechSettingsPanel(QWidget):
    saveRequested = Signal(object)
    previewRequested = Signal(object)
    changed = Signal()  # any edit, or a change of validity

    def __init__(self, settings: BookExportOptions) -> None:
        super().__init__()
        self.baseline = settings
        self.is_valid = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        introduction = QLabel(
            "Piper generates audiobook announcements locally with bundled neural voices. "
            "Generated voices are cached locally and inserted into "
            "the spoken lead-in of each chapter file, followed by "
            f"{SILENCE_SECONDS} seconds of silence."
        )
        introduction.setWordWrap(True)
        role(introduction, "muted")
        layout.addWidget(introduction)
        card = QFrame()
        role(card, "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(10)
        self.announce = QCheckBox("Announce the first chapter")
        self.announce.setChecked(settings.announce)
        self.announce.setToolTip("Spoken before chapter 1; when off, it starts directly")
        card_layout.addWidget(self.announce)
        self.template = QPlainTextEdit(settings.template)
        self.template.setAccessibleName("First chapter announcement")
        self.template.setFixedHeight(64)
        card_layout.addWidget(self.template)
        self.announce_chapters = QCheckBox("Announce the other chapters")
        self.announce_chapters.setChecked(settings.announce_chapters)
        self.announce_chapters.setToolTip("Spoken before every chapter after the first")
        card_layout.addWidget(self.announce_chapters)
        self.chapter_template = QPlainTextEdit(settings.chapter_template)
        self.chapter_template.setAccessibleName("Other chapters announcement")
        self.chapter_template.setFixedHeight(64)
        card_layout.addWidget(self.chapter_template)
        form = QFormLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.voice = RoundedComboBox()
        # Long voice names must not set the minimum width of the entire Settings page.
        self.voice.setMinimumContentsLength(16)
        self.voice.setSizeAdjustPolicy(
            RoundedComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        for code, label in VOICES.items():
            self.voice.addItem(label, code)
        self.voice.setCurrentIndex(self.voice.findData(settings.voice))
        voice_row = QHBoxLayout()
        voice_row.setSpacing(8)
        voice_row.addWidget(self.voice, 1)
        self.preview_button = QPushButton("Preview")
        self.preview_button.setIcon(icon("music"))
        self.preview_button.setToolTip("Hear this voice, speed and announcement text")
        self.preview_button.clicked.connect(self._request_preview)
        voice_row.addWidget(self.preview_button)
        form.addRow("Voice", voice_row)
        self.rate = QSpinBox()
        self.rate.setRange(60, 120)
        self.rate.setSuffix(" %")
        self.rate.setValue(settings.rate)
        self.rate.setFixedWidth(110)
        form.addRow("Speech rate", self.rate)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        card_layout.addLayout(form)
        variables = QLabel(
            "Variables: $book_name, $author_name, $chapter_number, $chapter_title. "
            "Use $$ for a literal $."
        )
        variables.setWordWrap(True)
        role(variables, "muted")
        card_layout.addWidget(variables)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        card_layout.addWidget(self.preview)
        layout.addWidget(card)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self._set_status("")
        layout.addWidget(self.status)
        # Not laid out here: the Settings page places it in its footer and decides when it is on.
        self.save = QPushButton("Save settings")
        role(self.save, "primary")
        self.save.setIcon(icon("check", ON_ACCENT))
        self.save.clicked.connect(self._save)
        self.announce.toggled.connect(self._preview)
        self.announce_chapters.toggled.connect(self._preview)
        self.chapter_template.textChanged.connect(self._preview)
        self.template.textChanged.connect(self._preview)
        self.voice.currentIndexChanged.connect(self._preview)
        self.rate.valueChanged.connect(self._preview)
        self._preview()

    @property
    def options(self) -> BookExportOptions:
        return BookExportOptions(
            self.announce.isChecked(),
            self.template.toPlainText(),
            str(self.voice.currentData()),
            self.rate.value(),
            self.announce_chapters.isChecked(),
            self.chapter_template.toPlainText(),
        )

    @property
    def modified(self) -> bool:
        return self.options != self.baseline

    def mark_saved(self, options: BookExportOptions) -> None:
        self.baseline = options
        self.changed.emit()

    def _preview(self) -> None:
        try:
            options = self.options
            speaks = options.announce or options.announce_chapters
            self.template.setEnabled(options.announce)
            self.chapter_template.setEnabled(options.announce_chapters)
            for control in (self.voice, self.rate, self.preview_button):
                control.setEnabled(speaks)
            if not speaks:
                self.preview.setText("Each MP3 starts directly with the chapter.")
                self.is_valid = True
                self._set_status("")
                self.changed.emit()
                return
            lines = []
            for number, title in ((1, "Prologue"), (2, "La rencontre")):
                text = options.part_text(number, "Les Misérables", "Victor Hugo", title)
                lines.append(f"Chapter {number}: “{text}”" if text else f"Chapter {number}: —")
            self.preview.setText(
                "\n".join(lines) + f"\nEach is followed by {SILENCE_SECONDS} seconds of silence."
            )
            self.is_valid = True
            self._set_status("")
        except ValueError as exc:
            self.preview.clear()
            self._set_status(str(exc))
            self.is_valid = False
        self.changed.emit()

    def _request_preview(self) -> None:
        try:
            self.options.validate()
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self.previewRequested.emit(self.options)

    def set_preview_state(self, text: str) -> None:
        """Reflect synthesis or playback; the button doubles as Stop."""
        self.preview_button.setText(text)

    def set_status(self, text: str) -> None:
        self._set_status(text)

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _save(self) -> None:
        try:
            self.options.validate()
            self._set_status("Saving settings…")
            self.saveRequested.emit(self.options)
        except ValueError as exc:
            self._set_status(str(exc))
