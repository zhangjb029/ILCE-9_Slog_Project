"""Synthetic two-property BK4 and in-memory service, with no USB access."""
import struct
from tests.flash_fakes import IDENTITY, config

MENU_PID, AV_PID = 0x20008, 0x3000B


def av_data(value=0):
    data = bytearray((i * 31 + 7) & 255 for i in range(256))
    data[0xAD] = value
    return bytes(data)


def backup(menu, av, attr=8):
    start = 0x100 + 4 * 6 + 21 * 6
    raw = bytearray(start + 4 + len(menu) + len(av))
    raw[12:16] = b'BK4\0'
    struct.pack_into('<IIII', raw, 16, 4, 21, start, len(raw) - start)
    struct.pack_into('<HI', raw, 0x100 + 2 * 6, 9, 0)
    struct.pack_into('<HI', raw, 0x100 + 3 * 6, 12, 9)
    for i in range(21):
        struct.pack_into('<HI', raw, 0x100 + 4 * 6 + i * 6, 0, 0xFFFFFFFF)
    cursor = start
    for slot, data, flags in ((8, menu, 0), (20, av, attr)):
        struct.pack_into('<HI', raw, 0x100 + 4 * 6 + slot * 6, flags, 0xFF000000 | cursor)
        struct.pack_into('<H', raw, cursor, len(data))
        raw[cursor + 2:cursor + 2 + len(data)] = data
        cursor += len(data) + 2
    struct.pack_into('<I', raw, 32, sum(raw[:32] + raw[36:]))
    return bytes(raw)


class Transport:
    def __init__(self, menu_value=0, av_value=0):
        self.data = {MENU_PID: config(menu_value), AV_PID: av_data(av_value)}
        self.attr = 8
        self.packets, self.writes = [], []
        self.saves, self.reads = 0, 0
        self.before_write = self.before_read = None
        self.write_error = self.bad_readback = self.bad_saved_readback = False
        self.snapshot_override = None

    def sendSenserPacket(self, function, data, oData=None):
        self.packets.append((function, data))
        if function == 0x10:
            return 0, b''
        assert function == 0x40
        category, command = struct.unpack_from('<HH', data)
        assert category == 0x603
        body = data[4:]
        if command == 5:
            return 0, self.snapshot_override or backup(self.data[MENU_PID], self.data[AV_PID], self.attr)
        if command == 1:
            pid, = struct.unpack('<I', body)
            self.reads += 1
            if self.before_read:
                self.before_read(pid, self.reads)
            raw = self.data[pid]
            if pid == AV_PID and ((self.bad_readback and self.writes) or (self.bad_saved_readback and self.saves)):
                raw = raw[:-1] + bytes([raw[-1] ^ 1])
            return 0, raw
        if command == 2:
            pid, = struct.unpack_from('<I', body)
            assert pid == AV_PID
            if self.before_write:
                self.before_write()
            self.writes.append((pid, body[4:]))
            self.data[pid] = body[4:]
            if self.write_error:
                raise IOError('ambiguous write completion')
            return 0, b''
        if command == 3:
            assert body == b'\0\0'
            self.saves += 1
            return 0, b''
        raise AssertionError('Unexpected packet')
