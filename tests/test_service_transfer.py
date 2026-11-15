"""Replay the two service interfaces byte for byte.

The A9 exposes the senser protocol on two product IDs and they do not frame
payload the same way: 0x02a9 pads every block to 512 bytes, 0x0336 does not.
Getting that wrong is invisible in unit tests that only count calls, and cost a
user every read on the camera — a 1 KiB property blocked for five seconds and a
1 MiB snapshot died with EPIPE after 1,032,716 bytes.
"""
import struct
import unittest

from a9tool import usbdev

from pmca.usb import sony

HEADER = sony.SonySenserDevice.SenserPacketHeader
MIN = sony.SonySenserDevice.SenserMinSize
CHUNK = sony.SonySenserDevice.SenserChunkSize
MAX = sony.SonySenserDevice.SenserMaxSize
FUNC = 0x40


class FakeSenserDriver:
    """Hands the caller exactly the bytes the camera would send, in order.

    Reading past the end raises, which is what a real bulk read does when the
    device has already finished: it blocks until the timeout and fails.
    """

    def __init__(self, product, payload, padding):
        self._product = product
        payload = bytes(payload)
        codec = HEADER
        header = codec.pack(size=len(payload), pFunc=FUNC, sequence=1, version=0,
                            miconType=0, offsetType=0, response=0)
        self.stream = bytearray()
        if padding:
            # Padded framing: the first 512-byte packet carries the header and
            # the first 500 payload bytes; every later full block is followed
            # by 512 bytes that carry no payload.
            lead = MIN - len(header)
            self.stream += header + payload[:lead]
            position = lead
            for per_block in (CHUNK - MIN, *([CHUNK] * 64)):
                if position >= len(payload):
                    break
                block = payload[position:position + per_block]
                self.stream += block + bytes(MIN)
                position += len(block)
        else:
            # Unpadded framing: one header carries as much as fits, and a
            # payload past SenserMaxSize continues in a second frame whose
            # header declares only what is left.
            offset, first = 0, True
            while first or offset < len(payload):
                block = payload[offset:offset + MAX]
                declared = len(payload) if first else len(block)
                self.stream += HEADER.pack(size=declared, pFunc=FUNC, sequence=1,
                                           version=0, miconType=0, offsetType=0,
                                           response=0) + block
                offset += len(block)
                first = False
        self.written = bytearray()
        self.overreads = 0

    def reset(self):
        pass

    def getId(self):
        return (sony.SONY_ID_VENDOR, self._product)

    def write(self, data):
        self.written += data

    def read(self, count, timeout=None):
        if not self.stream:
            self.overreads += 1
            raise TimeoutError('no more data (the camera had already finished)')
        take = min(count, len(self.stream))
        out = bytes(self.stream[:take])
        del self.stream[:take]
        return out


class Base(unittest.TestCase):
    def read_back(self, product, payload, padding):
        driver = FakeSenserDriver(product, payload, padding)
        device = usbdev._make_senser(sony, driver, response_timeout=5)
        return device.sendSenserPacket(FUNC, b'\x00\x01'), driver


class TestPaddedInterface(Base):
    """0x02a9: every block is followed by 512 bytes of padding."""

    def test_small_payload(self):
        payload = bytes(range(256)) * 4          # 1024 bytes
        (response, data), driver = self.read_back(0x02A9, payload, padding=True)
        self.assertEqual(data, payload)
        self.assertEqual(response, 0)
        self.assertEqual(driver.overreads, 0)

    def test_multi_block_payload(self):
        payload = bytes((i * 7) & 0xFF for i in range(70000))
        (_, data), driver = self.read_back(0x02A9, payload, padding=True)
        self.assertEqual(data, payload)
        self.assertEqual(driver.overreads, 0)


class TestUnpaddedInterface(Base):
    """0x0336: payload is sent back-to-back, with no padding at all."""

    def test_small_payload(self):
        payload = bytes(range(256)) * 4
        (response, data), driver = self.read_back(0x0336, payload, padding=False)
        self.assertEqual(data, payload)
        self.assertEqual(response, 0)
        self.assertEqual(driver.overreads, 0)

    def test_snapshot_sized_payload(self):
        payload = bytes((i * 13) & 0xFF for i in range(1_090_266))
        (_, data), driver = self.read_back(0x0336, payload, padding=False)
        self.assertEqual(len(data), 1_090_266)
        self.assertEqual(data, payload)
        self.assertEqual(driver.overreads, 0)

    def test_payload_that_ends_on_a_block_boundary(self):
        payload = b'\x5a' * CHUNK
        (_, data), driver = self.read_back(0x0336, payload, padding=False)
        self.assertEqual(data, payload)
        self.assertEqual(driver.overreads, 0)


if __name__ == '__main__':
    unittest.main()
