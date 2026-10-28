from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import Device

_SHOKZ_MARKERS = ("shokz", "swim pro", "openswim")


def _usage(path: Path) -> tuple[int, int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.used, usage.free


def device_identity(root: Path) -> tuple[int, int]:
    """Capture the selected directory's identity in a worker before long operations."""
    info = root.stat()
    return info.st_dev, info.st_ino


def verify_device(root: Path, expected: tuple[int, int]) -> None:
    if device_identity(root) != expected:
        raise OSError("Selected device changed or disconnected; select the original device again")


def manual_device(path: Path) -> Device:
    root = path.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Selected device path is not a folder")
    total, used, free = _usage(root)
    return Device(
        root.name or str(root),
        root,
        total,
        used,
        free,
        automatic=False,
        identity=device_identity(root),
    )


class DeviceDetector:
    def scan(self) -> list[Device]:
        if sys.platform == "linux":
            return self._linux()
        if sys.platform == "win32":
            return self._windows()
        return []

    def _linux(self) -> list[Device]:
        try:
            result = subprocess.run(
                ["lsblk", "--json", "-o", "NAME,LABEL,MOUNTPOINT,RM,TRAN,VENDOR,MODEL"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            data = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        devices: list[Device] = []

        def visit(node: dict[str, Any], parent_usb: bool = False) -> None:
            removable = bool(node.get("rm")) or parent_usb or node.get("tran") == "usb"
            label = str(node.get("label") or "")
            description = " ".join(
                str(node.get(key) or "") for key in ("vendor", "model", "label")
            ).strip()
            mount = node.get("mountpoint")
            recognized = any(marker in description.casefold() for marker in _SHOKZ_MARKERS)
            if mount and removable and recognized:
                path = Path(str(mount)).resolve()
                try:
                    total, used, free = _usage(path)
                    devices.append(
                        Device(
                            label or description or path.name,
                            path,
                            total,
                            used,
                            free,
                            identity=device_identity(path),
                        )
                    )
                except OSError:
                    pass
            for child in node.get("children") or []:
                visit(child, removable)

        for block in data.get("blockdevices", []):
            visit(block)
        return devices

    def _windows(self) -> list[Device]:
        devices: list[Device] = []
        kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - absent on non-Windows
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root_string = f"{letter}:\\"
            if kernel32.GetDriveTypeW(root_string) != 2:  # DRIVE_REMOVABLE
                continue
            volume = ctypes.create_unicode_buffer(261)
            if not kernel32.GetVolumeInformationW(
                root_string, volume, 261, None, None, None, None, 0
            ):
                continue
            label = volume.value
            if not any(marker in label.casefold() for marker in _SHOKZ_MARKERS):
                continue
            root = Path(root_string)
            try:
                total, used, free = _usage(root)
                devices.append(
                    Device(
                        label or f"Shokz ({letter}:)",
                        root,
                        total,
                        used,
                        free,
                        identity=device_identity(root),
                    )
                )
            except OSError:
                pass
        return devices


def is_within(root: Path, candidate: Path, *, allow_missing: bool = False) -> bool:
    try:
        resolved_root = root.resolve(strict=True)
        if allow_missing:
            resolved_candidate = candidate.parent.resolve(strict=True) / candidate.name
        else:
            resolved_candidate = candidate.resolve(strict=True)
        return resolved_candidate == resolved_root or resolved_root in resolved_candidate.parents
    except (OSError, RuntimeError):
        return False
