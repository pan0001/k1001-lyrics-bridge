"""Opt-in real Tk regression checks; no windows are created by default.

Run on Windows with SKYLYRICS_TEST_GUI=1. All test windows are positioned
off-screen so a test run does not cover or resize the user's control panel.
"""
import os
import sys
import tkinter as tk
import unittest

from blue_widgets import CutButton, MetricChip, Screen, StatCard, Toggle
from window_chrome import SlimScroll, TitleBar


@unittest.skipUnless(os.environ.get('SKYLYRICS_TEST_GUI') == '1' and sys.platform == 'win32',
                     'Set SKYLYRICS_TEST_GUI=1 on Windows to run real Tk widget tests')
class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title('SkyLyrics off-screen widget tests')
        self.root.geometry('1000x700+30000+30000')
        self.root.configure(bg='white')
        self.frame = tk.Frame(self.root, bg='white')
        self.frame.pack(fill='both', expand=True)

    def tearDown(self):
        self.root.destroy()

    def show(self):
        self.root.deiconify()
        self.root.update()

    def test_dynamic_updates_reuse_items_and_show_current_state(self):
        checked = tk.BooleanVar(master=self.root, value=False)
        output = tk.StringVar(master=self.root, value='initial')
        button = CutButton(self.frame, 'Button', lambda: None)
        toggle = Toggle(self.frame, checked)
        chip = MetricChip(self.frame, 'CPU', checked)
        card = StatCard(self.frame, 'CPU', '01')
        screen = Screen(self.frame, output)
        widgets = (button, toggle, chip, card, screen)
        for widget in widgets:
            widget.pack()
        self.show()
        original_items = [widget.find_all() for widget in widgets]
        for index in range(100):
            button.state(bool(index % 2))
            checked.set(bool(index % 2))
            card.set(index)
            output.set('歌词 ' + str(index))
            self.root.update_idletasks()
        self.assertEqual(original_items, [widget.find_all() for widget in widgets])
        self.assertEqual(button.itemcget(button._label, 'text'), 'Button')
        self.assertEqual(chip.itemcget(chip._check, 'state'), 'normal')
        self.assertEqual(card.itemcget(card._reading, 'text'), '99')
        self.assertEqual(screen.itemcget(screen._label, 'text'), '歌词 99')
        checked.set(False)
        self.assertEqual(chip.itemcget(chip._check, 'state'), 'hidden')
        card.set(None)
        self.assertEqual(card.itemcget(card._reading, 'text'), '--')
        self.assertEqual(card.itemcget(card._bar, 'state'), 'hidden')
        button.text = 'Updated button'
        button.primary = True
        button.paint()
        self.assertEqual(button.itemcget(button._label, 'text'), 'Updated button')
        self.assertEqual(original_items, [widget.find_all() for widget in widgets])

    def test_titlebar_handles_root_events_without_receiving_child_configure(self):
        class CountingTitleBar(TitleBar):
            configure_count = 0

            def on_state(self, event):
                self.configure_count += 1
                super().on_state(event)

        image = tk.PhotoImage(master=self.root, width=1, height=1)
        titlebar = CountingTitleBar(self.root, lambda: None, image)
        self.show()
        before = titlebar.configure_count
        for _ in range(100):
            self.frame.event_generate('<Configure>', width=400, height=300)
        self.root.update()
        self.assertEqual(titlebar.configure_count, before)
        self.root.geometry('1020x710+30000+30000')
        self.root.update()
        self.assertGreater(titlebar.configure_count, before)
        self.assertEqual(titlebar.last_size, (self.root.winfo_width(), self.root.winfo_height()))

    def test_scroll_thumb_visibility_and_repeated_position(self):
        target = tk.Canvas(self.frame)
        scroll = SlimScroll(self.frame, target)
        scroll.pack(fill='y', expand=True)
        self.show()
        self.assertEqual(scroll.itemcget(scroll.thumb, 'state'), 'hidden')
        scroll.set(0, .5)
        self.assertEqual(scroll.itemcget(scroll.thumb, 'state'), 'normal')
        position = scroll.coords(scroll.thumb)
        item_ids = scroll.find_all()
        for _ in range(100):
            scroll.set(0, .5)
        self.assertEqual(scroll.coords(scroll.thumb), position)
        self.assertEqual(scroll.find_all(), item_ids)
        scroll.set(.5, 1)
        self.assertGreater(scroll.coords(scroll.thumb)[1], position[1])
        scroll.set(0, 1)
        self.assertEqual(scroll.itemcget(scroll.thumb, 'state'), 'hidden')

    def test_hidden_preview_refreshes_latest_output_when_mapped(self):
        output = tk.StringVar(master=self.root, value='before hiding')
        screen = Screen(self.frame, output)
        screen.pack(fill='x')
        self.show()
        original_items = screen.find_all()
        self.root.withdraw()
        self.root.update()
        self.assertFalse(screen.winfo_ismapped())
        output.set('updated while hidden')
        self.root.update_idletasks()
        self.assertEqual(screen.itemcget(screen._label, 'text'), 'before hiding')
        self.show()
        self.assertTrue(screen.winfo_ismapped())
        self.assertEqual(screen.itemcget(screen._label, 'text'), 'updated while hidden')
        self.assertEqual(screen.find_all(), original_items)


if __name__ == '__main__':
    unittest.main()
