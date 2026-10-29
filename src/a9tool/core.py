"""The transaction engine: read the camera, write one property, verify, save.

Every writing function here follows the same shape — snapshot, persist, write,
read back, confirm nothing else moved, then SAVE(0) — because that is the shape
that was proven on hardware before this tool existed.
"""
from dataclasses import dataclass
from pathlib import Path

from . import fnmap, journal, usbdev

READ_PIDS = (fnmap.OVERRIDE, usbdev.FEATURE_SELECTOR, usbdev.MENU_SELECTOR, *fnmap.SLOT_PIDS)

STATUS_ENABLED = 'enabled'
STATUS_DISABLED = 'disabled'
STATUS_MIXED = 'mixed'


@dataclass
class CameraState:
    snapshot: bytes
    override: bytes
    slots: dict[int, int]


def read_state(camera) -> CameraState:
    """Read the whole backup once, then the live value of each property we model.

    The snapshot is kept as the on-disk evidence of the pre-write state; the
    per-property reads are what the transaction actually compares against.
    """
    snapshot = camera.getBackupPresetData(True)
    override = bytes(camera.readBackup(fnmap.OVERRIDE))
    slots = {number: camera.readBackup(pid)[0] for number, pid in fnmap.FN_SLOTS.items()}
    return CameraState(snapshot, override, slots)


def override_status(state: CameraState) -> str:
    values = {state.override[offset] for offset in fnmap.OVERRIDE_OFFSETS}
    if values == {2}:
        return STATUS_ENABLED
    if 2 not in values:
        return STATUS_DISABLED
    return STATUS_MIXED
