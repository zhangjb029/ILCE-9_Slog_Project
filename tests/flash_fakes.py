"""Synthetic BK4 data and an in-memory Senser service; no USB access."""
import struct


IDENTITY = {'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a' * 64}
PID = 0x00020008


def config(value=1):
    # Deliberately move index45 away from its original factory record position.
    indices = list(range(104))
    indices = indices[49:] + indices[:49]
    raw = bytearray(b'\xa5' * 1024)
    struct.pack_into('<4sIIII', raw, 0, b'BIN!', 1, 856, 20160707, 104)
    for i, index in enumerate(indices):
        struct.pack_into('<II', raw, 20 + 8*i, index, value if index == 0x45 else index + 3)
    raw[852:856] = b'FIN!'
    return bytes(raw)


def backup(data, attr=0):
    # Three subsystems, with nine property slots in subsystem2. Only slot8 exists.
    start = 0x100 + 3*6 + 9*6
    raw = bytearray(start + 2 + len(data))
    raw[12:16] = b'BK4\0'
    struct.pack_into('<IIII', raw, 16, 3, 9, start, len(data) + 2)
    struct.pack_into('<HI', raw, 0x100 + 2*6, 9, 0)
    for i in range(9):
        struct.pack_into('<HI', raw, 0x100 + 3*6 + i*6, 0, 0xffffffff)
    struct.pack_into('<HI', raw, 0x100 + 3*6 + 8*6, attr, 0xff000000 | start)
    struct.pack_into('<H', raw, start, len(data))
    raw[start+2:] = data
    struct.pack_into('<I', raw, 32, sum(raw[:32] + raw[36:]))
    return bytes(raw)


class ServiceTransport:
    """Exercise the real SonySenserCamera's packet framing, guard and engine."""
    def __init__(self, data=None, attr=0):
        self.data = config() if data is None else data
        self.attr = attr
        self.packets = []
        self.writes = []
        self.saves = 0
        self.reads = 0
        self.snapshots = 0
        self.before_write = None
        self.write_error = False
        self.bad_readback = False
        self.bad_saved_readback = False
        self.race_on_read = None
        self.snapshot_override = None

    def sendSenserPacket(self, function, data, oData=None):
        self.packets.append((function, data))
        if function != 0x40:
            return 0, b''
        category, command = struct.unpack_from('<HH', data)
        assert category == 0x603
        body = data[4:]
        if command == 5:
            self.snapshots += 1
            return 0, self.snapshot_override or backup(self.data, self.attr)
        if command == 1:
            assert struct.unpack('<I', body)[0] == PID
            self.reads += 1
            if self.race_on_read == self.reads:
                changed = bytearray(self.data)
                changed[-1] ^= 1
                self.data = bytes(changed)
            if (self.bad_readback and self.writes) or (self.bad_saved_readback and self.saves):
                return 0, self.data[:-1] + bytes([self.data[-1] ^ 1])
            return 0, self.data
        if command == 2:
            assert struct.unpack_from('<I', body)[0] == PID
            if self.before_write:
                self.before_write()
            self.writes.append(bytes(body[4:]))
            self.data = bytes(body[4:])
            if self.write_error:
                raise IOError('ambiguous write completion')
            return 0, b''
        if command == 3:
            assert body == b'\0\0'
            self.saves += 1
            return 0, b''
        raise AssertionError('Unexpected service operation')
