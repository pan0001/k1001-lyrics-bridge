"""Regressions for scroll events causing unnecessary Tk layout work."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import tkinter as tk

from settings_ui import SettingsWindow


class ScrollLayoutTests(unittest.TestCase):
    def make_panel(self):
        panel = SettingsWindow.__new__(SettingsWindow)
        panel.form_canvas = Mock()
        panel.form_id = 1
        panel._form_size = None
        panel._form_width = None
        return panel

    def test_scroll_movement_does_not_reconfigure_content(self):
        panel = self.make_panel()
        panel.update_scroll_region(SimpleNamespace(width=595, height=628, x=0, y=0))
        panel.form_canvas.reset_mock()
        for y in range(-1, -161, -1):
            panel.update_scroll_region(SimpleNamespace(width=595, height=628, x=0, y=y))
        panel.form_canvas.configure.assert_not_called()
        panel.form_canvas.bbox.assert_not_called()

    def test_page_and_viewport_sizes_still_update_content_bounds(self):
        panel = self.make_panel()
        panel.update_scroll_region(SimpleNamespace(width=595, height=628))
        panel.update_scroll_region(SimpleNamespace(width=595, height=429))
        panel.form_canvas.configure.assert_called_with(scrollregion=(0, 0, 595, 429))
        panel.resize_form(SimpleNamespace(width=430, height=383))
        panel.form_canvas.itemconfigure.assert_called_once_with(1, width=430)
        panel.resize_form(SimpleNamespace(width=430, height=500))
        panel.form_canvas.itemconfigure.assert_called_once()
        panel.update_scroll_region(SimpleNamespace(width=430, height=520))
        panel.form_canvas.configure.assert_called_with(scrollregion=(0, 0, 430, 520))

    def test_current_page_click_preserves_scroll_and_skips_layout(self):
        panel = self.make_panel()
        panel.current_page = 2
        panel.pages = [Mock() for _ in range(4)]
        panel.nav = [Mock() for _ in range(4)]
        panel.page_title = Mock()
        panel.switch(2)
        panel.form_canvas.yview_moveto.assert_not_called()
        panel.page_title.set.assert_not_called()
        for page, button in zip(panel.pages, panel.nav):
            page.pack.assert_not_called()
            page.pack_forget.assert_not_called()
            button.paint.assert_not_called()


class StartupDraftTests(unittest.TestCase):
    def setUp(self):
        # A Tcl interpreter exercises variable traces without mapping a window.
        self.interp = tk.Tcl()
        self.panel = SettingsWindow.__new__(SettingsWindow)
        self.panel.startup = tk.BooleanVar(master=self.interp)
        self.panel._startup_known = False
        self.panel._startup_dirty = False
        self.panel._startup_applying = False
        self.trace = self.panel.startup.trace_add('write', self.panel.startup_edited)

    def tearDown(self):
        self.panel.startup.trace_remove('write', self.trace)

    def test_unknown_state_is_not_saved_as_disabled(self):
        self.assertIsNone(self.panel.startup_choice())
        self.panel.receive_startup_state(True)
        self.assertTrue(self.panel.startup_choice())
        self.assertFalse(self.panel._startup_dirty)

    def test_delayed_read_preserves_user_edit(self):
        self.panel.receive_startup_state(True)
        self.panel.startup.set(False)
        self.panel.receive_startup_state(True)
        self.assertFalse(self.panel.startup_choice())
        self.assertTrue(self.panel._startup_dirty)

    def test_edit_while_saving_is_not_cleared_or_overwritten(self):
        self.panel.receive_startup_state(True)
        self.panel.startup.set(False)
        requested = self.panel.startup_choice()
        self.panel.startup.set(True)
        self.panel.startup_saved(requested)
        self.panel.receive_startup_state(False)
        self.assertTrue(self.panel.startup_choice())
        self.assertTrue(self.panel._startup_dirty)

    def test_successful_save_allows_fresh_system_state(self):
        self.panel.startup.set(True)
        self.panel.startup_saved(True)
        self.assertFalse(self.panel._startup_dirty)
        self.panel.receive_startup_state(False)
        self.assertFalse(self.panel.startup_choice())


if __name__ == '__main__':
    unittest.main()
