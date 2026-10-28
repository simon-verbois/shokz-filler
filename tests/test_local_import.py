import shutil
from pathlib import Path

import pytest

from shokz_filler.local_import import LocalMp3Importer
from shokz_filler.media import Cancelled, Progress
from shokz_filler.metadata import validate_mp3
from shokz_filler.transfer import TransferManager

FIXTURES = Path(__file__).parent / "fixtures"


class Normalizer:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def normalize(
        self, source: Path, output: Path, progress: Progress, cancelled: Cancelled
    ) -> Path:
        self.calls.append(source)
        shutil.copyfile(FIXTURES / "target-stereo.mp3", output)
        progress(100)
        return output


@pytest.mark.parametrize("fixture,conversions", [("target-stereo.mp3", 0), ("source-mono.mp3", 1)])
def test_local_import_always_publishes_the_required_format(
    tmp_path: Path,
    fixture: str,
    conversions: int,
) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = tmp_path / "Song.mp3"
    shutil.copyfile(FIXTURES / fixture, source)
    original = source.read_bytes()
    normalizer = Normalizer()
    importer = LocalMp3Importer(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), normalizer
    )
    progress: list[int] = []
    assert importer.import_files([source], root, root, progress.append) == 1
    validate_mp3(root / source.name)
    assert len(normalizer.calls) == conversions
    assert source.read_bytes() == original
    assert progress[-1] == 100 and progress == sorted(progress)
    assert not list((tmp_path / "cache").rglob("*.mp3"))
    if not conversions:
        assert (root / source.name).read_bytes() == original


def test_interrupted_normalized_import_retains_its_source_for_resume(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    source = FIXTURES / "source-mono.mp3"
    transfer = TransferManager(tmp_path / "state.json", chunk_size=100)
    importer = LocalMp3Importer(tmp_path / "cache", transfer, Normalizer())
    stop = False

    def progress(value: int) -> None:
        nonlocal stop
        if value > 50:
            stop = True

    with pytest.raises(InterruptedError):
        importer.import_files([source], root, root, progress, lambda: stop)
    assert not list(root.glob("*.mp3"))
    assert list(root.glob("*.part"))
    cached = next((tmp_path / "cache").rglob("*.mp3"))
    validate_mp3(cached)
    completed, errors = transfer.resume_for_device(root)
    assert not errors and len(completed) == 1
    validate_mp3(completed[0])
    assert not list(root.glob("*.part"))


def test_invalid_normalization_is_never_copied(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()

    class InvalidNormalizer(Normalizer):
        def normalize(self, source, output, progress, cancelled):  # type: ignore[no-untyped-def]
            shutil.copyfile(source, output)
            return output

    importer = LocalMp3Importer(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), InvalidNormalizer()
    )
    with pytest.raises(ValueError, match="192 kbps"):
        importer.import_files([FIXTURES / "source-mono.mp3"], root, root)
    assert list(root.iterdir()) == []


def test_device_replacement_during_local_conversion_prevents_copy(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()

    class SwappingNormalizer(Normalizer):
        def normalize(self, *args):  # type: ignore[no-untyped-def]
            result = super().normalize(*args)
            root.rename(tmp_path / "detached")
            root.mkdir()
            return result

    importer = LocalMp3Importer(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), SwappingNormalizer()
    )
    with pytest.raises(OSError, match="device changed"):
        importer.import_files([FIXTURES / "source-mono.mp3"], root, root)
    assert list(root.iterdir()) == []


def test_cancelled_local_import_does_not_start_conversion(tmp_path: Path) -> None:
    normalizer = Normalizer()
    importer = LocalMp3Importer(
        tmp_path / "cache", TransferManager(tmp_path / "state.json"), normalizer
    )
    with pytest.raises(InterruptedError):
        importer.import_files(
            [FIXTURES / "source-mono.mp3"], tmp_path, tmp_path, cancelled=lambda: True
        )
    assert not normalizer.calls
