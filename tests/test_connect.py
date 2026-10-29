"""Drive usbdev.connect() against a fake USB/PMCA module graph.

This is the only test that exercises the whole connection flow. It exists
because the identity-receipt regression it pins — a receipt written by one
successful connection being auto-reused by the next one — silently broke the
tutorial's own happy path.
"""
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from a9tool import journal, usbdev

MASS_STORAGE_PID = 0x0947
SERVICE_PID = 0x0336


class _Interface:
    def __init__(self, class_=8, protocol=0x50):
        self.bInterfaceClass = class_
        self.bInterfaceProtocol = protocol
        self.bInterfaceNumber = 0
        self.bAlternateSetting = 0


class _Device:
    def __init__(self, pid, class_):
        self.idVendor = 0x054c
        self.idProduct = pid
        self.bus = 1
        self.port_numbers = (2,)
        self._interface = _Interface(class_)

    def __iter__(self):
        return iter([iter([self._interface])])


class _Usb:
    USBError = RuntimeError

    def __init__(self):
        self.devices = []
        self.service_visible = False
        self.auto_service = True

    def find(self, find_all=False, idVendor=None, backend=None):
        return list(self.devices) + ([_Device(SERVICE_PID, 255)] if self.service_visible else [])


class _Util:
    def dispose_resources(self, _device):
        pass


class _Backend:
    usb = None

    def __init__(self, device):
        self.device = device


class _Driver:
    def __init__(self, backend):
        self.backend = backend


class _QueryBase:
    MSC_SENSE_DeviceBusy = 0

    def __init__(self, driver):
        self.driver = driver

    def _checkResponse(self, _sense):
        pass

    def getDeviceInfo(self):
        return {'modelName': 'ILCE-9'}


class _ExtCmdCamera:
    def __init__(self, _query):
        pass

    def getCameraInfo(self):
        return types.SimpleNamespace(modelName='ILCE-9', serial='SN-12345')


class _UpdaterCamera:
    def __init__(self, _query):
        pass

    def init(self):
        pass

    def getFirmwareVersion(self):
        return '6.00', None


class _Auth:
    def __init__(self, driver):
        self.driver = driver

    def start(self):
        pass

    def authenticate(self):
        if self.driver.backend.usb.auto_service:
            self.driver.backend.usb.service_visible = True

    def stop(self):
        pass


class _SenserCamera:
    def __init__(self, guard):
        self.guard = guard

    def readHasp(self):
        pass


def _sony():
    return types.SimpleNamespace(
        SONY_ID_PRODUCT_SENSER={SERVICE_PID},
        SONY_ID_PRODUCT_UPDATER={0x0337},
        isSonyMscCamera=lambda _inquiry: True,
        SonyMscExtCmdDevice=_QueryBase,
        SonyExtCmdCamera=_ExtCmdCamera,
        SonyUpdaterCamera=_UpdaterCamera,
        SonySenserAuthDevice=_Auth,
        SonySenserCamera=_SenserCamera,
    )


class TestConnect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.usb = _Usb()
        _Backend.usb = self.usb
        self.deps = (self.usb, _Util(), object(), _sony(), _Driver, _Driver, _Driver, _Backend)
        patcher = mock.patch.object(usbdev, '_load_dependencies', return_value=self.deps)
        patcher.start()
        self.addCleanup(patcher.stop)
        senser = mock.patch.object(usbdev, '_make_senser', return_value=object())
        senser.start()
        self.addCleanup(senser.stop)
        root_patcher = mock.patch.object(journal, 'sessions_root', return_value=self.root)
        root_patcher.start()
        self.addCleanup(root_patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _plug_mass_storage(self, count=1):
        self.usb.devices = [_Device(MASS_STORAGE_PID, 8) for _ in range(count)]

    def test_connect_without_camera_says_not_found(self):
        with self.assertRaises(RuntimeError) as ctx:
            usbdev.connect()
        self.assertIn('没找到相机', str(ctx.exception))

    def test_connect_with_two_cameras_is_refused(self):
        self._plug_mass_storage(2)
        with self.assertRaises(RuntimeError) as ctx:
            usbdev.connect()
        self.assertIn('多台', str(ctx.exception))

    def test_connect_succeeds_and_identifies_the_camera(self):
        self._plug_mass_storage()
        handle = usbdev.connect()
        self.assertEqual(handle.identity['model'], 'ILCE-9')
        self.assertEqual(handle.identity['firmware'], '6.00')
        handle.close()

    def test_successful_connect_leaves_no_reusable_receipt(self):
        self._plug_mass_storage()
        handle = usbdev.connect()
        handle.close()
        self.assertIsNone(usbdev.load_current_receipt())

    def test_second_connect_starts_from_mass_storage_again(self):
        self._plug_mass_storage()
        first = usbdev.connect()
        first.close()
        self.usb.service_visible = False  # camera rebooted back into mass storage
        second = usbdev.connect()  # must not resume into a service device that is not there
        self.assertEqual(second.identity['model'], 'ILCE-9')
        second.close()

    def test_service_device_never_appearing_reports_that_specific_failure(self):
        self._plug_mass_storage()
        self.usb.auto_service = False
        with mock.patch.object(usbdev, '_wait_for_service', return_value=[]):
            with self.assertRaises(RuntimeError) as ctx:
                usbdev.connect()
        self.assertIn('Service device not found', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
