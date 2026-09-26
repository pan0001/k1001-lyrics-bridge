"""Lightweight native window frame and event-driven scroll thumb."""
import ctypes
from ctypes import wintypes
import tkinter as tk
from blue_widgets import BG, BLUE, NAVY, LINE, FONT


class TitleBar(tk.Frame):
    def __init__(self, root, close, image):
        super().__init__(root, bg=BG, height=38)
        self.root = root
        self.pack(fill='x')
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetParent.argtypes = [wintypes.HWND]
        self.user32.GetParent.restype = wintypes.HWND
        self.user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        self.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.PostMessageW.restype = wintypes.BOOL
        self.last_state = None
        self.last_size = None
        self.logo = tk.Label(self, image=image, bg=BG)
        self.logo.pack(side='left', padx=(18, 6))
        label = tk.Label(self, text='晴空歌词  /  SKYLYRICS', bg=BG, fg=NAVY, font=(FONT, 9))
        label.pack(side='left')
        for widget in (self, self.logo, label):
            widget.bind('<ButtonPress-1>', self.drag)
            widget.bind('<Double-Button-1>', lambda e:self.maximize())
        for symbol, command, closing in [('×', close, True), ('□', self.maximize, False), ('−', root.iconify, False)]:
            button = tk.Button(self, text=symbol, command=command, bg=BG, fg=NAVY,
                               activebackground='#fce3e8' if closing else '#e3f3fe', activeforeground=BLUE,
                               bd=0, relief='flat', font=('Segoe UI', 15), width=3, takefocus=True)
            button.pack(side='right', ipady=1)
            button.bind('<Enter>', lambda e,b=button,c=closing:b.configure(bg='#fce3e8' if c else '#e3f3fe'))
            button.bind('<Leave>', lambda e,b=button:b.configure(bg=BG))
            if symbol == '□': self.max_button = button
        # A toplevel's ordinary bind tag is also present on every descendant.
        # Use a root-only tag so scrolling child windows does not enter Python
        # title-bar callbacks for their Map/Configure events.
        self._event_tag = f'SkyLyricsTitleBar{id(self)}'
        root.bindtags((self._event_tag,) + root.bindtags())
        root.bind_class(self._event_tag, '<Map>', self.on_map)
        root.bind_class(self._event_tag, '<Configure>', self.on_state)
        root.after_idle(self.apply_frame)

    def hwnd(self):
        return self.user32.GetParent(self.root.winfo_id())

    def apply_frame(self):
        hwnd = self.hwnd()
        style = self.user32.GetWindowLongW(hwnd, -16)
        # Retain the native resize frame, taskbar and minimize/maximize behavior.
        if style & 0x00C00000:
            self.user32.SetWindowLongW(hwnd, -16, style & ~0x00C00000)
            self.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x27)
        try:
            color = wintypes.DWORD(0x00FCF9F5)
            dwm = ctypes.WinDLL('dwmapi')
            dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color), ctypes.sizeof(color))
        except OSError:
            pass

    def on_map(self, event):
        if event.widget is self.root: self.root.after_idle(self.apply_frame)

    def on_state(self, event):
        if event.widget is self.root:
            size = (event.width, event.height)
            if self.last_size == size:
                return
            self.last_size = size
            state = self.root.state()
            if state != self.last_state:
                self.last_state = state
                self.max_button.configure(text='❐' if state == 'zoomed' else '□')

    def maximize(self):
        self.root.state('normal' if self.root.state() == 'zoomed' else 'zoomed')

    def drag(self, event):
        self.user32.ReleaseCapture()
        # Never enter a native modal move loop from a Python/Tk callback.
        # Tk must dispatch this message from its own event loop, with its
        # interpreter thread state restored (otherwise PyEval_RestoreThread aborts).
        self.user32.PostMessageW(self.hwnd(), 0x00A1, 2, 0)


class SlimScroll(tk.Canvas):
    def __init__(self, parent, target):
        super().__init__(parent, width=10, highlightthickness=0, bg='white', cursor='arrow')
        self.target, self.first, self.last = target, 0.0, 1.0
        self.drag_offset = 0
        self._thumb_geometry = self._thumb_state = None
        self.thumb = self.create_line(5, 5, 5, 5, fill='#b7dbf2', width=4, capstyle='round')
        self.bind('<Configure>', lambda e:self.paint())
        self.bind('<Enter>', lambda e:self.itemconfigure(self.thumb, fill=BLUE))
        self.bind('<Leave>', lambda e:self.itemconfigure(self.thumb, fill='#b7dbf2'))
        self.bind('<Button-1>', self.press)
        self.bind('<B1-Motion>', self.move)

    def set(self, first, last):
        first, last = float(first), float(last)
        if (self.first, self.last) == (first, last):
            return
        self.first, self.last = first, last
        self.paint()

    def geometry(self):
        height = max(1, self.winfo_height()-8)
        size = min(height, max(30, (self.last-self.first)*height))
        travel = height-size
        top = 4 + travel*self.first/max(.0001, 1-(self.last-self.first))
        return top, size, travel

    def paint(self):
        top, size, _ = self.geometry()
        state = 'hidden' if self.last-self.first >= .999 else 'normal'
        if state != self._thumb_state:
            self._thumb_state = state
            self.itemconfigure(self.thumb, state=state)
        geometry = (5, top+2, 5, top+size-2)
        if self._thumb_geometry != geometry:
            self._thumb_geometry = geometry
            self.coords(self.thumb, *geometry)

    def press(self, event):
        top, size, _ = self.geometry()
        self.drag_offset = event.y-top if top <= event.y <= top+size else size/2
        self.move(event)

    def move(self, event):
        _, _, travel = self.geometry()
        fraction = (event.y-4-self.drag_offset)/max(1, travel)*(1-(self.last-self.first))
        self.target.yview_moveto(fraction)
