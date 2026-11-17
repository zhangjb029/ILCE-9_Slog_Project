import unittest

from a9tool import errors


class TestErrorMessages(unittest.TestCase):
    def test_service_not_found_yields_resume_hint(self):
        msg = errors.user_message(RuntimeError('Service device not found'))
        self.assertIn('Zadig', msg)
        self.assertIn('重试', msg)

    def test_busy_identity_yields_power_cycle_hint(self):
        msg = errors.user_message(RuntimeError('Camera busy during identity request'))
        self.assertIn('关机', msg)

    def test_unknown_error_still_gives_next_step(self):
        msg = errors.user_message(ValueError('something odd'))
        self.assertTrue(msg.strip())
        self.assertIn('日志', msg)

    def test_multiple_cameras_message_is_actionable(self):
        msg = errors.user_message(RuntimeError('找到多台相机'))
        self.assertIn('一台', msg)

    def test_no_camera_message_names_the_checks(self):
        msg = errors.user_message(RuntimeError('没找到相机'))
        self.assertIn('大容量存储', msg)
        self.assertIn('Zadig', msg)

    def test_wrong_model_message_names_the_limit(self):
        msg = errors.user_message(ValueError('Only ILCE-9 with firmware 6.00 is supported'))
        self.assertIn('ILCE-9', msg)
        self.assertIn('6.00', msg)

    def test_a_read_timeout_says_it_stopped_and_did_not_retry(self):
        msg = errors.user_message(
            TimeoutError('Service response exceeded 900 seconds; no request retry'))
        self.assertIn('超时', msg)
        self.assertIn('没有重试', msg)

    def test_libusb_not_supported_gets_driver_advice(self):
        """pyusb turns -12 into a bare NotImplementedError; say what it means."""
        msg = errors.user_message(
            NotImplementedError('Operation not supported or unimplemented on this platform'))
        self.assertIn('-12', msg)
        self.assertIn('Zadig', msg)


class TestRawDetailAlwaysReachesTheUser(unittest.TestCase):
    """A remote report showed the fallback text and nothing else.

    The user could not say what had happened, so the fallback now carries the
    exception type, its message, and the note the USB layer attached.
    """

    def test_an_unknown_failure_shows_its_type_and_message(self):
        # IOError is an alias of OSError on Python 3, so the type name is OSError.
        msg = errors.user_message(IOError('Invalid or empty service response'))
        self.assertIn('OSError', msg)
        self.assertIn('Invalid or empty service response', msg)

    def test_the_transport_note_is_included(self):
        error = TimeoutError('Service response exceeded 900 seconds; no request retry')
        error.add_note('Service USB read: phase=payload, frame=412, payload_received=13500416')
        msg = errors.user_message(error)
        self.assertIn('TimeoutError', msg)
        self.assertIn('phase=payload', msg)
        self.assertIn('frame=412', msg)

    def test_a_known_hint_keeps_its_advice_and_gains_the_detail(self):
        msg = errors.user_message(RuntimeError('Service device not found'))
        self.assertIn('Zadig', msg)
        self.assertIn('RuntimeError: Service device not found', msg)

    def test_the_fallback_asks_for_the_detail_lines(self):
        msg = errors.user_message(ValueError('something odd'))
        self.assertIn('技术细节', msg)
        self.assertIn('ValueError: something odd', msg)

    def test_the_fallback_points_at_what_the_detail_records(self):
        msg = errors.user_message(ValueError('something odd'))
        self.assertIn('USB', msg)

    def test_the_innermost_location_is_named(self):
        """One line placing the fault, instead of a stack trace at the user."""

        def deep():
            raise ValueError('boom')

        try:
            deep()
        except ValueError as error:
            msg = errors.user_message(error)
        self.assertIn('deep()', msg)
        self.assertIn('test_errors.py', msg)

    def test_an_error_that_was_never_raised_still_renders(self):
        msg = errors.user_message(ValueError('never raised'))
        self.assertIn('ValueError: never raised', msg)
        self.assertNotIn('位置：', msg)


if __name__ == '__main__':
    unittest.main()
