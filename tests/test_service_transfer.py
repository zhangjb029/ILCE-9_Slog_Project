"""Replay the two service interfaces byte for byte.

The A9 exposes the senser protocol on two product IDs and they do not frame
payload the same way: 0x02a9 pads every block to 512 bytes, 0x0336 does not.
Getting that wrong is invisible in unit tests that only count calls, and cost a
user every read on the camera — a 1 KiB property blocked for five seconds and a
1 MiB snapshot died with EPIPE after 1,032,716 bytes.
"""
import io
from unittest import mock
import unittest

from a9tool import menu_deploy, usbdev

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

    def __init__(self, product, payload, padding, response=0, function=FUNC):
        self._product = product
        payload = bytes(payload)
        header = HEADER.pack(size=len(payload), pFunc=function, sequence=1, version=0,
                             miconType=0, offsetType=0, response=response)
        self.stream = bytearray()
        if padding:
            # A body that separates reply blocks with 512 bytes. On 0x02a9 the
            # header packet also carries the first 500 payload bytes; on 0x0336
            # the header is bare and the separators only start after a block.
            minimum = 0 if product == 0x0336 else MIN
            lead = max(minimum - len(header), 0)
            self.stream += header + payload[:lead]
            position = lead
            for per_block in (CHUNK - minimum, *([CHUNK] * 64)):
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
                # Every continuation frame declares what is still to come.
                declared = len(payload) - offset
                self.stream += HEADER.pack(size=declared, pFunc=function, sequence=1,
                                           version=0, miconType=0, offsetType=0,
                                           response=response) + block
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

    def sent_packets(self):
        """Split what the host wrote back into (declared_remaining, body)."""
        packets, position = [], 0
        while position < len(self.written):
            header = HEADER.unpack(bytes(self.written[position:position + HEADER.size]))
            position += HEADER.size
            body = bytes(self.written[position:position + min(header.size, MAX)])
            position += len(body)
            packets.append((header.size, body))
        return packets


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
    """0x0336 with back-to-back payload — the A9TOOL_UNPADDED=1 body.

    Its separators are absent, so the stock framing mis-reads every block
    after the first. Only a body that needs this should run in this mode.
    """

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(usbdev, 'UNPADDED', True)
        patcher.start()
        self.addCleanup(patcher.stop)

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


class TestPadded0336(Base):
    """A 0x0336 body that *does* separate blocks, which the PID does not predict.

    This is the combination that broke every read after v1.5.1: the product ID
    says "no padding", the hardware sends it anyway, and the payload after the
    first block lands 512 bytes off.
    """

    def test_value_that_ends_on_a_block_boundary(self):
        payload = bytes(range(256)) * 4          # 1024
        (response, data), driver = self.read_back(0x0336, payload, padding=True)
        self.assertEqual(data, payload)
        self.assertEqual(response, 0)
        self.assertEqual(driver.overreads, 0)

    def test_value_that_does_not_end_on_a_boundary(self):
        payload = b'\x42' * 700
        (_, data), driver = self.read_back(0x0336, payload, padding=True)
        self.assertEqual(data, payload)
        self.assertEqual(driver.overreads, 0)

    def test_several_blocks(self):
        payload = bytes((i * 5) & 0xFF for i in range(70000))
        (_, data), driver = self.read_back(0x0336, payload, padding=True)
        self.assertEqual(data, payload)
        self.assertEqual(driver.overreads, 0)


class TestStreamedReply(Base):
    """A reply larger than the in-memory cap must reach a sink instead."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(usbdev, 'UNPADDED', True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_partition_sized_reply_streams_to_the_sink(self):
        payload = bytes((i * 11) & 0xFF for i in range(3 * MAX + 7))
        driver = FakeSenserDriver(0x0336, payload, padding=False)
        device = usbdev._make_senser(sony, driver, response_timeout=10)
        sink = io.BytesIO()
        response, returned = device.sendSenserPacket(FUNC, b'\x00\x01', sink)
        self.assertIsNone(returned, 'a streamed reply must not also be returned')
        self.assertEqual(sink.getvalue(), payload)
        self.assertEqual(driver.overreads, 0)

    def test_the_same_reply_without_a_sink_is_still_capped(self):
        payload = b'\x00' * (3 * MAX)
        driver = FakeSenserDriver(0x0336, payload, padding=False)
        device = usbdev._make_senser(sony, driver, response_timeout=5)
        with self.assertRaises(ValueError):
            device.sendSenserPacket(FUNC, b'\x00\x01')


class TestChunkedRequest(Base):
    """A request larger than 1 MiB leaves as several packets."""

    def test_a_large_request_is_split_into_one_mib_packets(self):
        request = bytes((i * 3) & 0xFF for i in range(2 * MAX + 500))
        driver = FakeSenserDriver(0x0336, b'', padding=False, response=1)
        device = usbdev._make_senser(sony, driver, response_timeout=5)
        device.sendSenserPacket(FUNC, request)

        packets = driver.sent_packets()
        self.assertEqual(len(packets), 3)
        # The size field is how much is still to come, not this packet's size.
        self.assertEqual([size for size, _ in packets],
                         [len(request), len(request) - MAX, 500])
        self.assertEqual(b''.join(body for _, body in packets), request)

    def test_a_small_request_still_leaves_as_one_packet(self):
        driver = FakeSenserDriver(0x0336, b'', padding=False, response=1)
        device = usbdev._make_senser(sony, driver, response_timeout=5)
        device.sendSenserPacket(FUNC, b'\xaa\xbb\xcc')
        packets = driver.sent_packets()
        self.assertEqual(packets, [(3, b'\xaa\xbb\xcc')])


class TestFileControlSink(Base):
    """The whole path: PMCA asks for a file, the guard lets it through."""

    def _camera(self, product=0x0336, payload=b'\x5a\xa5', response=1):
        driver = FakeSenserDriver(product, payload, padding=False, response=response,
                                  function=sony.SonySenserCamera.SONY_PFUNC_FileControl)
        senser = usbdev._make_senser(sony, driver, response_timeout=5)
        return sony.SonySenserCamera(menu_deploy.PartitionGuard(senser)), driver

    def test_readfile_writes_into_the_stream_it_was_given(self):
        camera, _ = self._camera()
        sink = io.BytesIO()
        camera.readFile('/setting/updater/dat4', sink)
        self.assertEqual(sink.getvalue(), b'\x5a\xa5')

    def test_a_path_outside_the_allowlist_is_still_refused(self):
        camera, _ = self._camera()
        with self.assertRaises(ValueError):
            camera.readFile('/etc/passwd', io.BytesIO())

    def test_a_whole_partition_write_leaves_as_packets(self):
        """The same path the deploy step uses, at a size a test can afford."""
        size = 2 * MAX + 7
        driver = FakeSenserDriver(0x0336, b'', padding=False, response=1,
                                  function=sony.SonySenserCamera.SONY_PFUNC_FileControl)
        senser = usbdev._make_senser(sony, driver, response_timeout=10)
        guard = menu_deploy.PartitionGuard(senser, allow_write=True)
        camera = sony.SonySenserCamera(guard)
        image = b'\x33' * size
        with mock.patch.object(menu_deploy, 'PARTITION_BYTES', size):
            camera.writeFile(menu_deploy.PARTITION, image)

        packets = driver.sent_packets()
        self.assertGreater(len(packets), 2, 'a multi-MiB write must be split')
        sent = b''.join(body for _, body in packets)
        name = menu_deploy.PARTITION.encode('latin1')
        self.assertTrue(sent.endswith(image))
        self.assertIn(name, sent)
        self.assertEqual(len(sent), 4 + len(name) + 4 - len(name) % 4 + size)

    def test_an_oversized_write_is_still_refused(self):
        _, driver = self._camera()
        senser = usbdev._make_senser(sony, driver, response_timeout=5)
        guard = menu_deploy.PartitionGuard(senser, allow_write=True)
        camera = sony.SonySenserCamera(guard)
        with mock.patch.object(menu_deploy, 'PARTITION_BYTES', 10):
            with self.assertRaises(ValueError):
                camera.writeFile(menu_deploy.PARTITION, b'\x00' * 50)
        self.assertEqual(driver.written, b'', 'nothing may reach the camera')


if __name__ == '__main__':
    unittest.main()
