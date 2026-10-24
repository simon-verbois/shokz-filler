import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from shokz_refill.device import manual_device  # noqa: E402
from shokz_refill.models import Track  # noqa: E402
from shokz_refill.themed_dialog import InputDialog  # noqa: E402
from shokz_refill.transfer_wizard import TransferWizard  # noqa: E402


def pump(app: QApplication, predicate) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def tracks() -> list[Track]:
    return [Track("a", "One", ("X",)), Track("b", "Two", ("X",)), Track("c", "Three", ("X",))]


def make(tmp_path: Path, **options: object) -> tuple[TransferWizard, Path]:
    root = tmp_path / "device"
    (root / "Music").mkdir(parents=True)
    (root / "System Volume Information").mkdir()
    wizard = TransferWizard(tracks(), manual_device(root), **options)  # type: ignore[arg-type]
    return wizard, root


def test_steps_reorder_remove_and_choose_existing_folder(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    wizard, root = make(tmp_path)
    pump(app, lambda: wizard.folder_list.count() == 1)  # Hidden system folders are not offered.
    assert wizard.step_label.text() == "Step 1 of 2" and wizard.next_button.text() == "Next"
    wizard.song_list.item(2).setSelected(True)
    wizard._move(-1)
    assert [t.video_id for t in wizard.tracks] == ["a", "c", "b"]
    wizard.song_list.clearSelection()
    wizard.song_list.item(0).setSelected(True)
    wizard._remove()
    assert [t.video_id for t in wizard.tracks] == ["c", "b"]
    wizard._next()
    assert wizard.step_label.text() == "Step 2 of 2" and wizard.next_button.text() == "Send"
    assert not wizard.next_button.isEnabled()  # A folder must be chosen.
    wizard.folder_list.setCurrentRow(0)
    wizard._next()
    assert wizard.result() == QDialog.DialogCode.Accepted
    assert wizard.destination == root / "Music"


def test_suggested_playlist_folder_is_preselected_even_when_missing(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    wizard, root = make(tmp_path, suggested="Road Trip")
    pump(app, lambda: wizard.folder_list.count() == 2)
    assert wizard.folder_list.currentItem().text().startswith("Road Trip")
    wizard._go(1)
    wizard._next()
    assert wizard.destination == root / "Road Trip"  # Created later, off the UI thread.


def test_new_folder_is_created_and_selected_without_closing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = QApplication.instance() or QApplication([])
    wizard, root = make(tmp_path)
    pump(app, lambda: wizard.folder_list.count() == 1)
    monkeypatch.setattr(InputDialog, "getText", staticmethod(lambda *a, **k: ("Fresh!", True)))
    wizard._go(1)
    wizard._create_folder()
    pump(app, lambda: wizard.folder_list.count() == 2)
    assert (root / "Fresh").is_dir()
    assert wizard.folder_list.currentItem().text() == "Fresh"
    assert wizard.result() != QDialog.DialogCode.Accepted
    wizard._next()
    assert wizard.destination == root / "Fresh"


def test_cannot_send_without_songs_and_last_folder_is_preselected(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "device"
    (root / "Music").mkdir(parents=True)
    wizard = TransferWizard(tracks(), manual_device(root), last=root / "Music")
    pump(app, lambda: wizard.folder_list.count() == 1)
    assert wizard.folder_list.currentItem().text() == "Music"
    wizard.song_list.selectAll()
    wizard._remove()
    assert not wizard.next_button.isEnabled()
