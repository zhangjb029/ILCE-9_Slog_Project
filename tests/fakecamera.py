"""A stand-in for SonySenserCamera that never touches USB.

Holds the same surface core.py calls: a whole-backup snapshot, per-property
reads and writes, and saveBackup(0). Writes are recorded so tests can assert
exactly which properties were touched.
"""
from a9tool import fnmap, usbdev

SNAPSHOT_PAD = 8192


class FakeCamera:
    def __init__(self, override: bytes | None = None, slots: dict[int, int] | None = None):
        self.override = bytearray(override if override is not None else b'\x01' * 1024)
        self.slots = dict(slots) if slots is not None else {n: 0x06 for n in fnmap.FN_SLOTS}
        self.written: dict[int, bytes] = {}
        self.saves = 0
        self.fail_on_write: int | None = None

    # -- the camera surface core.py uses -----------------------------------
    def getBackupPresetData(self, _padding=False) -> bytes:
        return bytes(self.override) + bytes(SNAPSHOT_PAD)

    def readBackup(self, pid: int) -> bytes:
        if pid == fnmap.OVERRIDE:
            return bytes(self.override)
        for number, prop in fnmap.FN_SLOTS.items():
            if prop == pid:
                return bytes([self.slots[number]])
        if pid in (usbdev.FEATURE_SELECTOR, usbdev.MENU_SELECTOR):
            return b'\x4b'
        raise ValueError(f'Unknown property {pid:#010x}')

    def writeBackup(self, pid: int, data: bytes) -> None:
        if self.fail_on_write is not None and pid == self.fail_on_write:
            raise IOError('simulated write failure')
        self.written[pid] = bytes(data)
        if pid == fnmap.OVERRIDE:
            self.override = bytearray(data)
            return
        for number, prop in fnmap.FN_SLOTS.items():
            if prop == pid:
                self.slots[number] = data[0]
                return
        raise ValueError(f'Unknown property {pid:#010x}')

    def saveBackup(self, subsystem: int) -> None:
        self.saves += 1


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendSenserPacket(self, function, data, oData=None):
        self.sent.append((function, data))
        return 0, b''
