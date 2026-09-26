"""Keep shell and startup work out of Tk; collapse obsolete telemetry."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from tray import TrayApp, repair_startup, take_ui_events


class TrayResponsivenessTests(unittest.TestCase):
    def test_slow_shell_does_not_block_caller_or_build_unbounded_backlog(self):
        entered, finish = threading.Event(), threading.Event()
        caller = threading.get_ident()

        class SlowIcon:
            def __init__(self):
                self.titles = []
                self.menus = 0
                self.threads = []

            @property
            def title(self):
                return self.titles[-1] if self.titles else ''

            @title.setter
            def title(self, value):
                self.threads.append(threading.get_ident())
                self.titles.append(value)
                if value == 'first':
                    entered.set()
                    finish.wait(3)

            def update_menu(self):
                self.menus += 1

        app = TrayApp.__new__(TrayApp)
        app.icon = SlowIcon()
        app.tray_worker = ThreadPoolExecutor(max_workers=1)
        app._tray_lock = threading.Lock()
        app._tray_pending = {}
        app._tray_scheduled = False
        try:
            started = time.monotonic()
            app.update_tray(title='first')
            self.assertLess(time.monotonic() - started, .2)
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            for i in range(200):
                app.update_tray(title=str(i), menu=True)
            self.assertLess(time.monotonic() - started, .2)
            self.assertEqual(len(app._tray_pending), 2)
        finally:
            finish.set()
            app.tray_worker.shutdown(wait=True)
        self.assertEqual(app.icon.titles, ['first', '199'])
        self.assertEqual(app.icon.menus, 1)
        self.assertNotIn(caller, app.icon.threads)

    def test_startup_refresh_runs_in_background_and_deduplicates(self):
        entered, finish = threading.Event(), threading.Event()
        app = TrayApp.__new__(TrayApp)
        app.events = queue.Queue()
        app.quit_event = threading.Event()
        app._startup_refresh_pending = False
        app.settings_worker = ThreadPoolExecutor(max_workers=1)

        def slow_read():
            entered.set()
            finish.wait(3)
            return True

        with patch('tray.startup_enabled', side_effect=slow_read) as read:
            try:
                started = time.monotonic()
                app.refresh_startup()
                self.assertLess(time.monotonic() - started, .2)
                self.assertTrue(entered.wait(1))
                for _ in range(100):
                    app.refresh_startup()
                self.assertEqual(read.call_count, 1)
            finally:
                finish.set()
                app.settings_worker.shutdown(wait=True)
        self.assertEqual(app.events.get_nowait(), ('startup_state', True))

    def test_tray_menu_uses_cached_startup_state_without_disk_reads(self):
        app = TrayApp.__new__(TrayApp)
        app.startup_active = True
        app.status = 'ready'
        with patch('tray.startup_enabled', side_effect=AssertionError('unexpected disk read')):
            item = next(item for item in app.menu() if item.text == '开机自启动')
            self.assertTrue(item.checked)
            app.startup_active = False
            self.assertFalse(item.checked)

    def test_saving_other_settings_preserves_unknown_startup(self):
        app = TrayApp.__new__(TrayApp)
        app.events = queue.Queue()
        app.saving = False
        app.ui = Mock()
        app.settings_worker = ThreadPoolExecutor(max_workers=1)
        with tempfile.TemporaryDirectory() as folder, \
                patch('tray.startup_enabled', side_effect=AssertionError('unknown startup must be preserved')), \
                patch('tray.set_startup') as write:
            app.config = Path(folder) / 'settings.json'
            try:
                self.assertTrue(app.apply_settings({}, None))
            finally:
                app.settings_worker.shutdown(wait=True)
            write.assert_not_called()
            self.assertTrue(app.config.is_file())
            kind, (_, _, requested) = app.events.get_nowait()
            self.assertEqual(kind, 'settings_saved')
            self.assertIsNone(requested)

    def test_explicit_startup_edit_is_saved_and_returned_with_completion(self):
        app = TrayApp.__new__(TrayApp)
        app.events = queue.Queue()
        app.saving = False
        app.ui = Mock()
        app.settings_worker = ThreadPoolExecutor(max_workers=1)
        with tempfile.TemporaryDirectory() as folder, patch('tray.startup_enabled', return_value=True), \
                patch('tray.set_startup') as write:
            app.config = Path(folder) / 'settings.json'
            try:
                self.assertTrue(app.apply_settings({}, False))
            finally:
                app.settings_worker.shutdown(wait=True)
            write.assert_called_once_with(False)
            kind, (_, _, requested) = app.events.get_nowait()
            self.assertEqual(kind, 'settings_saved')
            self.assertIs(requested, False)

    def test_coalescing_preserves_control_order_and_final_update_text(self):
        events = queue.Queue()
        for event in [('output', 'old'), ('track', ('A', '', '')), ('output', 'latest'),
                      ('status', 'working'), ('error', 'offline'), ('ui_action', 'stop'),
                      ('output', 'after stop'), ('update_state', {'text': 'Downloading', 'busy': True}),
                      ('update_state', {'text': 'Downloaded', 'notify': True}),
                      ('update_state', {'text': '', 'busy': False})]:
            events.put(event)
        self.assertEqual(take_ui_events(events, budget=1), [
            ('output', 'latest'), ('track', ('A', '', '')), ('error', 'offline'), ('ui_action', 'stop'),
            ('output', 'after stop'), ('update_state', {'text': 'Downloaded', 'busy': False, 'notify': True})])

    def test_event_processing_retains_backlog_for_next_tick(self):
        events = queue.Queue()
        for i in range(120):
            events.put(('output', i))
        self.assertEqual(take_ui_events(events, limit=100, budget=1), [('output', 99)])
        self.assertEqual(events.qsize(), 20)

    def test_unchanged_startup_skips_recreation_but_changed_target_repairs(self):
        signature = dict(command='"C:\\App\\SkyLyrics.exe" --background', size=100, modified=1)
        with tempfile.TemporaryDirectory() as folder, patch('tray.DATA_DIR', Path(folder)), \
                patch('tray.startup_enabled', return_value=True), \
                patch('tray.startup_signature', return_value=signature), \
                patch('tray.old_startup_link', return_value=Path(folder) / 'absent.lnk'), \
                patch('tray.legacy_startup_present', return_value=False), patch('tray.set_startup') as write:
            cache = Path(folder) / 'startup-registration.json'
            cache.write_text(json.dumps(signature), encoding='utf-8')
            repair_startup()
            write.assert_not_called()
            cache.write_text(json.dumps(dict(signature, command='old path')), encoding='utf-8')
            repair_startup()
            write.assert_called_once_with(True)

    def test_disabled_startup_is_preserved_and_legacy_registration_is_repaired(self):
        with patch('tray.startup_enabled', return_value=False), patch('tray.set_startup') as write:
            repair_startup()
            write.assert_not_called()
        with patch('tray.startup_enabled', return_value=True), patch('tray.set_startup') as write, \
                patch('tray.startup_signature', return_value=None):
            repair_startup()
            write.assert_called_once_with(True)


if __name__ == '__main__':
    unittest.main()
