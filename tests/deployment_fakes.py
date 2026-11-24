"""Fixed-path camera fixtures shared by native R15NH/V8 deployment tests."""
import struct

IDENTITY = dict(model='ILCE-9', firmware='6.00', serial_sha256='a'*64)


class WireTransport:
    def __init__(self, files, tables=()):
        self.files = files
        self.tables = tables
        self.writes = []

    def sendSenserPacket(self, function, data, oData=None):
        status, raw = self._send(function, data)
        if oData is not None:
            oData.write(raw)
            return status, None
        return status, raw

    def _send(self, function, data):
        command, size = struct.unpack_from('<HH', data)
        if function == 0x40:
            if command == 0x603:
                return 0, self.tables[int.from_bytes(data[4:], 'little')-0x30004]
            if size == 0x4002:
                return 0, bytes(4)
            name = data[10:-1].decode('ascii')
            raw = self.files.get(name)
            return (0, (0x10000006).to_bytes(4, 'little') if raw is None else bytes(4)+raw)
        name = data[4:4+size].rstrip(b'\0').decode('ascii')
        if command == 2:
            return 1, self.files[name]
        self.writes.append(name)
        if command == 1:
            self.files[name] = data[4+size:]
        if command == 3:
            self.files.pop(name, None)
        return 1, b''


class WireCamera:
    def __init__(self, guard):
        self.dev = guard

    def readFile(self, name, outFile=None):
        return self.dev.sendSenserPacket(0xff01, self.packet(2, name), outFile)[1]

    def writeFile(self, name, raw):
        self.dev.sendSenserPacket(0xff01, self.packet(1, name, raw))

    def deleteFile(self, name):
        self.dev.sendSenserPacket(0xff01, self.packet(3, name))

    def readBackup(self, pid):
        return self.dev.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 1, pid))[1]

    @staticmethod
    def packet(command, name, raw=b''):
        encoded = name.encode()
        encoded += bytes(4-len(encoded)%4)
        return struct.pack('<HH', command, len(encoded))+encoded+raw


class FramedCameraDriver:
    """Replay fixed file replies beneath the real v1.8.2 Senser transport.

    Unlike WireCamera this fixture does not implement the camera API or bypass
    reply-size limits. The caller uses SonySenserCamera and _make_senser; this
    driver supplies physical frames, including continuation headers and the
    default 512-byte separators on the 0x0336 service interface.
    """
    def __init__(self, files, tables=(), *, padded=True):
        from pmca.usb import sony
        self.sony = sony
        self.wire = WireTransport(files, tables)
        self.padded = padded
        self.pending = bytearray()
        self.response = bytearray()
        self.response_offset = 0
        self.requests = []
        self.overreads = 0

    def reset(self):
        pass

    def getId(self):
        return self.sony.SONY_ID_VENDOR, 0x0336

    def write(self, packet):
        device = self.sony.SonySenserDevice
        header = device.SenserPacketHeader.unpack(packet)
        self.pending.extend(packet[device.SenserPacketHeader.size:])
        if header.size > device.SenserMaxSize:
            return
        request = bytes(self.pending)
        self.pending.clear()
        self.requests.append((header.pFunc, request))
        status, raw = self.wire._send(header.pFunc, request)
        stream = bytearray()
        offset = 0
        while True:
            frame = raw[offset:offset+device.SenserMaxSize]
            stream.extend(device.SenserPacketHeader.pack(
                size=len(raw)-offset, pFunc=header.pFunc, sequence=header.sequence,
                version=0, miconType=0, offsetType=0, response=status))
            for start in range(0, len(frame), device.SenserChunkSize):
                block = frame[start:start+device.SenserChunkSize]
                stream.extend(block)
                if self.padded and len(block) % device.SenserMinSize == 0:
                    stream.extend(bytes(device.SenserMinSize))
            offset += len(frame)
            if offset >= len(raw):
                break
        self.response = stream
        self.response_offset = 0

    def read(self, count, timeout=None):
        if self.response_offset >= len(self.response):
            self.overreads += 1
            raise TimeoutError('Framed reply was already consumed')
        end = min(self.response_offset+count, len(self.response))
        raw = bytes(self.response[self.response_offset:end])
        self.response_offset = end
        return raw
