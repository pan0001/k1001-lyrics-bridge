"""Regression coverage for settings IO blocking the control-panel thread."""
import queue
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from idle_display import settings_from
from tray import TrayApp


class SettingsIOTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.app = TrayApp.__new__(TrayApp)
        self.app.settings_worker = ThreadPoolExecutor(max_workers=1)
        self.app.config = Path(self.folder.name)/'settings.json'
        self.app.events = queue.Queue()
        self.app.saving = False
        self.app.ui = SimpleNamespace(message=Mock())

    def tearDown(self):
        self.app.settings_worker.shutdown(wait=True)
        self.folder.cleanup()

    def test_slow_startup_change_leaves_ui_thread_free(self):
        entered, release = threading.Event(), threading.Event()
        def slow(_):
            entered.set()
            release.wait(3)
        with patch('tray.startup_enabled', return_value=False), patch('tray.set_startup', side_effect=slow):
            try:
                start = time.monotonic()
                self.assertTrue(self.app.apply_settings(settings_from({}), True, preview=True))
                self.assertLess(time.monotonic()-start, .2)
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.app.events.empty())
                self.assertFalse(self.app.apply_settings(settings_from({}), True))
            finally:
                release.set()
            kind, (saved, preview) = self.app.events.get(timeout=2)
            self.assertEqual(kind, 'settings_saved')
            self.assertTrue(preview)
            self.assertTrue(self.app.config.exists())

    def test_unchanged_startup_does_not_launch_powershell(self):
        with patch('tray.startup_enabled', return_value=True), patch('tray.set_startup') as change:
            self.app.apply_settings(settings_from({}), True)
            self.assertEqual(self.app.events.get(timeout=2)[0], 'settings_saved')
            change.assert_not_called()

    def test_io_failure_is_reported_without_overwriting_config(self):
        self.app.config.write_text('original', encoding='utf-8')
        with patch('tray.startup_enabled', return_value=False), patch('tray.set_startup', side_effect=OSError('test error')):
            with self.assertLogs(level='ERROR'):
                self.app.apply_settings(settings_from({}), True)
                self.assertEqual(self.app.events.get(timeout=2)[0], 'settings_failed')
        self.assertEqual(self.app.config.read_text(encoding='utf-8'), 'original')


if __name__ == '__main__':
    unittest.main()
