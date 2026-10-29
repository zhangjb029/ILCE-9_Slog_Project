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


if __name__ == '__main__':
    unittest.main()
