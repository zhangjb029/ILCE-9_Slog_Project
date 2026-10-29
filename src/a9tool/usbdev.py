"""USB access: identify the camera, switch to service mode, guard parameter traffic.

Everything here is a port of the already-verified command-line tools. The one
structural change is that the packet guard now allowlists the parameters this
tool is allowed to touch, instead of the two properties one experiment happened
to need.
"""
from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import fnmap
from .journal import digest

MAX_SERVICE_REPLY = 2 * 1024 * 1024  # the A9 snapshot handler's own limit
SERVICE_RESPONSE_SECONDS = 30
RECEIPT_SCHEMA = 'a9tool-identity-v1'
RECEIPT_FILENAME = '_receipt.json'
RECEIPT_TTL_SECONDS = 3600

SUPPORTED_MODEL = 'ILCE-9'
SUPPORTED_FIRMWARE = '6.00'

FEATURE_SELECTOR = 0x0107146D
MENU_SELECTOR = 0x01070316

READABLE = frozenset({fnmap.OVERRIDE, FEATURE_SELECTOR, MENU_SELECTOR, *fnmap.SLOT_PIDS})
# Property -> the only payload length that property accepts. Pinning the length
# here means a sizing bug in core cannot send 1024 bytes at a one-byte slot.
WRITE_SIZES = {fnmap.OVERRIDE: 1024, **{pid: 1 for pid in fnmap.SLOT_PIDS}}
WRITABLE = frozenset(WRITE_SIZES)


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def check_identity(identity: dict) -> None:
    if identity.get('model') != SUPPORTED_MODEL or identity.get('firmware') != SUPPORTED_FIRMWARE:
        raise ValueError('Only ILCE-9 with firmware 6.00 is supported')
    serial = identity.get('serial_sha256', '')
    if len(serial) != 64 or any(c not in '0123456789abcdef' for c in serial):
        raise ValueError('Missing camera identity fingerprint')


def _select_single(devices):
    found = list(devices)
    if not found:
        raise RuntimeError('没找到相机')
    if len(found) > 1:
        raise RuntimeError('找到多台相机')
    return found[0]


# --------------------------------------------------------------------------
# identity receipts
# --------------------------------------------------------------------------

def _receipt_root(root) -> Path:
    from . import journal
    return Path(root) if root is not None else journal.sessions_root()


def save_receipt(identity: dict, usb_port: dict, root=None) -> Path:
    """Remember who we verified and on which USB port, so a service-mode retry
    does not need the user to find a file path."""
    folder = _receipt_root(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / RECEIPT_FILENAME
    record = dict(schema=RECEIPT_SCHEMA, created_epoch=time.time(),
                  identity=identity, usb_port=usb_port)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def load_current_receipt(root=None) -> Path | None:
    path = _receipt_root(root) / RECEIPT_FILENAME
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if record.get('schema') != RECEIPT_SCHEMA:
        return None
    if not 0 <= time.time() - record.get('created_epoch', 0) <= RECEIPT_TTL_SECONDS:
        return None
    check_identity(record.get('identity', {}))
    return path


def discard_receipt(root=None) -> None:
    """Drop the receipt once a connection succeeded.

    A receipt only exists to get the user past the second driver install. Left
    in place it would be auto-reused by the next run, which then skips the
    mass-storage identification step and looks for a service device that is not
    there yet — so every connection after a successful one would fail.
    """
    try:
        (_receipt_root(root) / RECEIPT_FILENAME).unlink()
    except FileNotFoundError:
        pass


def read_receipt(path: Path) -> dict:
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    if record.get('schema') != RECEIPT_SCHEMA:
        raise ValueError('Resume receipt was not written by this tool')
    if not 0 <= time.time() - record.get('created_epoch', 0) <= RECEIPT_TTL_SECONDS:
        raise ValueError('Resume receipt must be less than one hour old')
    check_identity(record.get('identity', {}))
    return record


# --------------------------------------------------------------------------
# packet guard
# --------------------------------------------------------------------------

class ParameterGuard:
    """Allow only the properties this tool is allowed to touch.

    Passes: the backup snapshot request, READs of the properties we model,
    WRITEs of the PP override or an Fn slot, and SAVE(0) — the latter only
    after a write actually happened. Anything else raises before it reaches
    the camera.
    """

    def __init__(self, transport):
        self.transport = transport
        self.wrote = False

    def sendSenserPacket(self, function, data, oData=None):
        if oData is not None or not isinstance(data, bytes):
            raise ValueError('Nonstandard transfers are blocked')
        allowed = function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0)
        if not allowed and function == 0x40 and len(data) >= 4:
            category, command = struct.unpack_from('<HH', data)
            body = data[4:]
            if category == 0x603:
                if command == 5:
                    allowed = body == b'\x01'
                elif command == 1:
                    allowed = len(body) == 4 and struct.unpack('<I', body)[0] in READABLE
                elif command == 2 and len(body) >= 5:
                    pid = struct.unpack_from('<I', body)[0]
                    allowed = WRITE_SIZES.get(pid) == len(body) - 4
                    if allowed:
                        self.wrote = True
                elif command == 3:
                    allowed = self.wrote and body == b'\0\0'
                    if allowed:
                        self.wrote = False
        if not allowed:
            raise ValueError('Camera packet blocked by the parameter allowlist')
        return self.transport.sendSenserPacket(function, data)


# --------------------------------------------------------------------------
# device discovery
# --------------------------------------------------------------------------

def validate_request(group, payload, read_size):
    """Bound the mass-storage identity query to the two commands we need."""
    if group == 1:
        if read_size != 0x2000 or len(payload) != 0x2000:
            raise ValueError('Only the fixed model-info query is allowed')
        if payload[:16] != struct.pack('<IHH8x', 0, 1, 0) or any(payload[16:]):
            raise ValueError('Only model-info command 1 with an empty body is allowed')
        return 'model_info'
    if group == 0:
        if read_size != 512 or len(payload) != 32:
            raise ValueError('Only empty updater query packets are allowed')
        size, protocol, command, response, sequence = struct.unpack_from('<I4H', payload)
        if size or protocol != 0x100 or response or sequence or any(payload[12:]):
            raise ValueError('Invalid query packet framing')
        if command not in (1, 0x20):
            raise ValueError('Only query-session init and version-query are allowed')
        return {1: 'query_session_init', 0x20: 'firmware_version'}[command]
    raise ValueError('Command group is not allowlisted')


@dataclass
class CameraHandle:
    """An open service-mode session. Close it before the process exits."""
    camera: object
    driver: object
    auth: object
    identity: dict
    devices: list = field(default_factory=list)
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.auth is not None:
                self.auth.stop()  # upstream suppresses USB errors on this path
        except Exception:
            pass
        try:
            import usb.util as util
            for device in self.devices:
                util.dispose_resources(device)
        except Exception:
            pass


# --------------------------------------------------------------------------
# connection
# --------------------------------------------------------------------------

def _load_dependencies():
    import libusb_package
    import usb.core
    import usb.util
    from pmca.usb import sony
    from pmca.usb.driver.generic import GenericUsbDriver, MscBbbDriver, MscCbiDriver
    from pmca.usb.driver.generic.libusb import UsbBackend
    backend = libusb_package.get_libusb1_backend()
    if backend is None:
        raise RuntimeError('Bundled libusb backend could not be loaded')
    return usb.core, usb.util, backend, sony, GenericUsbDriver, MscBbbDriver, MscCbiDriver, UsbBackend


def _make_senser(sony, driver):
    class BoundedSenser(sony.SonySenserDevice):
        def _tail_is_continuation_header(self):
            if self._declared_size is None or self._declared_size <= self.SenserMaxSize:
                return None
            if len(self._wire_tail) < self.SenserPacketHeader.size:
                return False
            h = self.SenserPacketHeader.unpack(self._wire_tail[-self.SenserPacketHeader.size:])
            return (h.size == self._declared_size - self.SenserMaxSize
                    and h.pFunc == self._request_function and h.sequence == self._sequence
                    and h.response == self._response_code and h.version == 0
                    and h.miconType == 0 and h.offsetType == 0)

        def _read_bounded(self, count):
            self._read_calls += 1
            try:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Service response exceeded 30 seconds; no request retry')
                timeout = max(1, min(5000, int(remaining * 1000)))
                result = self.driver.read(count, timeout=timeout)
            except Exception as error:
                error.add_note(
                    f'Service USB read: phase={self._read_phase}, frame={self._frame_index}, '
                    f'function={self._request_function:#x}, sequence={self._sequence}, '
                    f'declared_size={self._declared_size}, response={self._response_code}, '
                    f'payload_received={self._payload_received}; no retry')
                raise
            self._physical_received += len(result)
            self._wire_tail = (self._wire_tail + result)[-self.SenserPacketHeader.size:]
            if self._read_phase == 'padding drain':
                self._drain_reads += 1
                self._drain_nonempty += bool(result)
                self._drain_bytes += len(result)
                self._drain_all_zero += bool(result) and not any(result)
            return result

        def _readAll(self, count):
            chunks, received = [], 0
            while received < count:
                chunk = self._read_bounded(count - received)
                if not chunk or len(chunk) > count - received:
                    raise IOError('Invalid or empty service response')
                chunks.append(chunk)
                received += len(chunk)
                self._payload_received += len(chunk)
            return b''.join(chunks)

        def sendSenserPacket(self, function, data, oData=None):
            if oData is not None or not 0 < len(data) <= self.SenserMaxSize:
                raise ValueError('Unsupported service request size')
            header = self.SenserPacketHeader.pack(size=len(data), pFunc=function, sequence=self._sequence,
                                                  version=0, miconType=0, offsetType=0, response=0)
            self._deadline = time.monotonic() + SERVICE_RESPONSE_SECONDS
            self._request_function = function
            self._read_calls = self._physical_received = self._payload_received = 0
            self._declared_size = self._response_code = None
            self._drain_reads = self._drain_nonempty = self._drain_bytes = self._drain_all_zero = 0
            self._wire_tail = b''
            self._usb_product = self.driver.getId()[1]
            self.driver.write(header + data)
            output = bytearray()
            minimum = 0 if self._usb_product == 0x0336 else self.SenserMinSize
            remaining = None
            response = None
            for frame in range(1, 4):
                self._frame_index = frame
                self._read_phase = 'response header'
                padding = max(minimum - self.SenserPacketHeader.size, 0)
                packet = self._read_bounded(self.SenserPacketHeader.size + padding)
                h = self.SenserPacketHeader.unpack(packet)
                self._declared_size, self._response_code = h.size, h.response
                if h.sequence != self._sequence or h.pFunc != function or h.size > MAX_SERVICE_REPLY:
                    raise ValueError('Unexpected service framing or size')
                if remaining is None:
                    remaining, response = h.size, h.response
                elif h.size != remaining or h.response != response:
                    raise ValueError('Inconsistent multi-packet response')
                payload = packet[self.SenserPacketHeader.size:]
                if len(payload) != padding:
                    raise ValueError('Truncated service packet')
                length = min(h.size, self.SenserMaxSize)
                output.extend(payload[:length])
                self._payload_received += min(len(payload), length)
                done = padding
                chunk_size = self.SenserChunkSize - minimum
                while done < length:
                    amount = min(length - done, chunk_size)
                    self._read_phase = 'payload'
                    output.extend(self._readAll(amount))
                    done += amount
                    if not (amount & (self.SenserMinSize - 1)):
                        self._read_phase = 'padding drain'
                        self._read_bounded(self.SenserMinSize)
                    chunk_size = self.SenserChunkSize
                remaining -= length
                if h.size <= self.SenserMaxSize:
                    self._sequence += 1
                    return h.response, bytes(output)
            raise ValueError('Service response exceeds chunk limit')
    return BoundedSenser(driver)


def _wait_for_service(enumerate_devices, transient_error):
    for _ in range(20):
        time.sleep(0.5)
        try:
            found = enumerate_devices()
        except transient_error:
            continue
        if len(found) > 1:
            raise RuntimeError('Multiple service devices appeared; refusing to select a camera')
        if found:
            return found
    return []


def connect(receipt: Path | None = None, progress=None) -> CameraHandle:
    """Open exactly one ILCE-9 and switch it into service mode.

    With ``receipt`` (a fresh identity file written before the mode switch) the
    mass-storage step is skipped, which is what makes the second driver install
    recoverable without asking the user to hunt for a path.
    """
    say = progress or (lambda _msg: None)
    usb, util, backend, sony, Generic, BBB, CBI, UsbBackend = _load_dependencies()

    def candidates(service):
        found = []
        for dev in usb.find(find_all=True, idVendor=0x054c, backend=backend):
            interface = next((i for config in dev for i in config), None)
            if interface is None:
                continue
            if service and dev.idProduct in sony.SONY_ID_PRODUCT_SENSER and interface.bInterfaceClass == 255:
                found.append((dev, interface))
            elif not service and dev.idProduct not in sony.SONY_ID_PRODUCT_UPDATER and interface.bInterfaceClass == 8:
                found.append((dev, interface))
        return found

    def port(dev):
        return dict(bus=dev.bus, ports=list(dev.port_numbers or ()))

    class QueryDevice(sony.SonyMscExtCmdDevice):
        def sendSonyExtCommand(self, cmd, data, bufferSize):
            validate_request(cmd, data, bufferSize)
            cdb = bytes([0x7a]) + struct.pack('<I', cmd) + bytes(7)
            for _ in range(3):
                sense = self.driver.sendWriteCommand(cdb, data)
                if sense != self.MSC_SENSE_DeviceBusy:
                    self._checkResponse(sense)
                    break
            else:
                raise TimeoutError('Camera busy during identity request')
            for _ in range(3):
                sense, response = self.driver.sendReadCommand(cdb, bufferSize)
                if sense != self.MSC_SENSE_DeviceBusy:
                    self._checkResponse(sense)
                    return response
            raise TimeoutError('Camera busy during identity request')

    devices = []
    auth = None
    try:
        expected_port = None
        identity = None
        if receipt is not None:
            record = read_receipt(receipt)
            identity = record['identity']
            check_identity(identity)
            expected_port = record['usb_port']
            if candidates(True):
                say('使用上次的凭据继续')
            else:
                # The camera is no longer in service mode (power-cycled, or never
                # got there). Fall back to the normal path rather than hunting for
                # a device that is not plugged in.
                say('相机不在服务模式，重新从大容量存储开始')
                identity = None
                expected_port = None

        if identity is None:
            found = candidates(False)
            device, interface = _select_single(found)
            if candidates(True):
                raise RuntimeError('Camera is already in service mode; unplug and replug it in Mass Storage mode')
            devices.append(device)
            if interface.bInterfaceNumber != 0 or interface.bAlternateSetting != 0:
                raise RuntimeError('Unsupported USB interface layout')
            usb_backend = UsbBackend(device)
            if interface.bInterfaceProtocol in (0x50, 0x80):
                driver = BBB(usb_backend)
            elif interface.bInterfaceProtocol in (0, 1):
                driver = CBI(usb_backend)
            else:
                raise RuntimeError('Unsupported mass storage protocol')
            query = QueryDevice(driver)
            inquiry = query.getDeviceInfo()
            if not sony.isSonyMscCamera(inquiry):
                raise ValueError('USB inquiry is not a Sony camera')
            info = sony.SonyExtCmdCamera(query).getCameraInfo()
            updater = sony.SonyUpdaterCamera(query)
            updater.init()
            version, _ = updater.getFirmwareVersion()
            identity = dict(model=info.modelName, firmware=version,
                            serial_sha256=digest(info.serial.encode()))
            check_identity(identity)
            expected_port = port(device)
            if not expected_port['ports']:
                raise RuntimeError('USB port path unavailable; cannot bind the service device to this camera')
            receipt = save_receipt(identity, expected_port)
            say('已确认 ILCE-9 / 6.00，正在切换服务模式')
            auth = sony.SonySenserAuthDevice(driver)
            auth.start()
            auth.authenticate()
            auth = None
            util.dispose_resources(device)
            devices.remove(device)
            found = _wait_for_service(lambda: candidates(True), usb.USBError)
            if len(found) != 1:
                raise RuntimeError('Service device not found')

        found = candidates(True)
        device, interface = _select_single(found)
        devices.append(device)
        if expected_port.get('ports') and port(device) != expected_port:
            raise ValueError('Service device is on a different USB port; refusing access')
        if interface.bInterfaceNumber != 0 or interface.bAlternateSetting != 0:
            raise RuntimeError('Unsupported service USB interface layout')
        driver = Generic(UsbBackend(device))
        auth = sony.SonySenserAuthDevice(driver)
        auth.start()
        auth.authenticate()
        say('服务模式已认证，正在读取机身参数')
        guard = ParameterGuard(_make_senser(sony, driver))
        camera = sony.SonySenserCamera(guard)
        camera.readHasp()
        handle = CameraHandle(camera=camera, driver=driver, auth=auth,
                              identity=identity, devices=devices)
        auth = None  # ownership moves to the handle
        discard_receipt()  # a receipt is only for getting past a failed switch
        return handle
    except BaseException:
        if auth is not None:
            try:
                auth.stop()
            except Exception:
                pass
        try:
            for device in devices:
                util.dispose_resources(device)
        except Exception:
            pass
        raise
