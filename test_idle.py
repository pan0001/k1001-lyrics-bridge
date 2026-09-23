import unittest
from datetime import datetime
from idle_display import IdleClock, settings_from, display_pages, validate_template


class IdleTests(unittest.TestCase):
    def test_pause_boundary_resume_and_second_pause(self):
        clock = IdleClock()
        self.assertFalse(clock.active(True, 100, True, 5))
        self.assertFalse(clock.active(False, 101, True, 5))
        self.assertFalse(clock.active(False, 400.9, True, 5))
        self.assertTrue(clock.active(False, 401, True, 5))
        self.assertFalse(clock.active(True, 402, True, 5))
        self.assertFalse(clock.active(False, 403, True, 5))
        self.assertFalse(clock.active(False, 702, True, 5))
        self.assertTrue(clock.active(False, 703, True, 5))

    def test_disabled_does_not_accrue_idle_time(self):
        clock = IdleClock()
        self.assertFalse(clock.active(False, 0, False, 5))
        self.assertFalse(clock.active(False, 1000, True, 5))
        self.assertTrue(clock.active(False, 1300, True, 5))

    def test_old_config_preserves_player_and_lyrics(self):
        s = settings_from({'source': 'Another.exe', 'lyrics': False})
        self.assertEqual(s['source'], 'Another.exe')
        self.assertFalse(s['lyrics'])
        self.assertEqual(s['idle_minutes'], 5)

    def test_invalid_config_is_safe(self):
        s = settings_from({'idle_minutes': float('nan'), 'rotation_seconds': 0, 'metrics': [[], 'bad'], 'custom_text': '{bad}'})
        self.assertEqual(s['idle_minutes'], 5)
        self.assertEqual(s['rotation_seconds'], 5)
        self.assertTrue(s['metrics'])
        self.assertTrue(display_pages(s, {}))

    def test_portable_missing_sensors(self):
        s = settings_from({'metrics': ['cpu_temp', 'gpu', 'memory']})
        pages = display_pages(s, {'gpu': 21, 'memory': 42})
        self.assertEqual(pages, ['CPU 温度：不可用', 'GPU 21%', '内存 42%'])

    def test_custom_pages_and_unavailable_values(self):
        s = settings_from({'idle_mode': 'custom', 'custom_text': '{time}\n\nCPU {cpu}% / {cpu_temp}°C\n{{字面括号}}'})
        pages = display_pages(s, {'cpu': 7}, datetime(2026, 1, 1, 9, 5))
        self.assertEqual(pages, ['09:05', 'CPU 7% / --°C', '{字面括号}'])

    def test_template_disallows_attribute_and_format_expressions(self):
        for text in ('{cpu.real}', '{cpu[0]}', '{cpu!r}', '{cpu:10000}', '{', ' ', '{unknown}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_template(text)


if __name__ == '__main__':
    unittest.main()
