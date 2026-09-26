"""Original vector widgets for the blue-and-white control panel."""
import tkinter as tk

BLUE = '#168ee6'
CYAN = '#39c9ee'
NAVY = '#243b56'
MUTED = '#8495a6'
BG = '#f5f9fc'
LINE = '#e2edf5'
YELLOW = '#ffe27a'
FONT = 'Microsoft YaHei UI'


def unchanged_size(widget, event):
    """Configure also fires on moves: scrolling must not rebuild every canvas."""
    size = (widget.winfo_width(), widget.winfo_height())
    previous = getattr(widget, '_paint_size', None)
    widget._paint_size = size
    return event is not None and size == previous


class Pattern(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=BG, highlightthickness=0)
        self._triangles, self._crosses = set(), set()
        self._corners = (self.create_polygon(0, 0, 0, 0, fill='#e1f6fd', outline='', tags='corners'),
                         self.create_polygon(0, 0, 0, 0, fill='#e9f4fb', outline='', tags='corners'))
        self.bind('<Configure>', self.paint)

    def paint(self, event=None):
        if unchanged_size(self, event): return
        w, h = self.winfo_width(), self.winfo_height()
        for x in range(-120, w+160, 240):
            for y in range(-100, h+160, 210):
                if (x, y) not in self._triangles:
                    self._triangles.add((x, y))
                    self.create_polygon(x, y+190, x+112, y, x+224, y+190, fill='', outline='#eaf2f7', width=7)
        for x in range(30, w, 110):
            for y in range(30, h, 110):
                if (x, y) not in self._crosses:
                    self._crosses.add((x, y))
                    self.create_line(x-3, y, x+3, y, fill='#dcecf7')
                    self.create_line(x, y-3, x, y+3, fill='#dcecf7')
        self.coords(self._corners[0], w-140, 0, w, 0, w, 210)
        self.coords(self._corners[1], 0, h-125, 0, h, 190, h)
        self.tag_raise('corners')


class CutButton(tk.Canvas):
    def __init__(self, parent, text, command, width=160, height=45, primary=False, small=False):
        super().__init__(parent, width=width, height=height, bg=parent.cget('bg'), highlightthickness=0,
                         cursor='hand2', takefocus=1)
        self.text, self.command, self.primary, self.hover, self.small = text, command, primary, False, small
        self.bind('<Configure>', self.paint)
        self.bind('<Enter>', lambda e: self.state(True))
        self.bind('<Leave>', lambda e: self.state(False))
        self.bind('<FocusIn>', lambda e: self.state(True))
        self.bind('<FocusOut>', lambda e: self.state(False))
        self.bind('<Button-1>', lambda e: self.invoke())
        self.bind('<Return>', lambda e: self.invoke())
        self.bind('<space>', lambda e: self.invoke())

    def invoke(self):
        self.focus_set()
        self.command()

    def state(self, hover):
        if self.hover == hover: return
        self.hover = hover
        self.paint()

    def paint(self, event=None):
        if unchanged_size(self, event): return
        if not hasattr(self, '_face'):
            self._shadow = self.create_polygon(0, 0, 0, 0, fill='#dce8f1', outline='')
            self._face = self.create_polygon(0, 0, 0, 0)
            self._label = self.create_text(0, 0, font=(FONT, 10 if self.small else 11, 'bold'))
            self._layout = self._style = None
        w, h = self.winfo_width(), self.winfo_height()-4
        if self._layout != (w, h):
            self._layout = (w, h)
            self.coords(self._shadow, 11, 4, w-1, 4, w-12, h+3, 0, h+3)
            self.coords(self._face, 12, 0, w-1, 0, w-13, h, 1, h)
            self.coords(self._label, w/2, h/2)
        style = (self.primary, self.hover, self.text)
        if self._style == style: return
        self._style = style
        fill = BLUE if self.primary else ('#e7f6ff' if self.hover else 'white')
        if self.primary and self.hover:
            fill = '#0078cc'
        self.itemconfigure(self._face, fill=fill, outline=BLUE if self.primary else '#d6e6f2')
        self.itemconfigure(self._label, text=self.text, fill='white' if self.primary else NAVY)


class Toggle(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent, width=44, height=25, bg='white', highlightthickness=0, cursor='hand2', takefocus=1)
        self.variable = variable
        variable.trace_add('write', lambda *_: self.paint())
        self.bind('<Button-1>', lambda e: variable.set(not variable.get()))
        self.bind('<space>', lambda e: variable.set(not variable.get()))
        self.bind('<Configure>', self.paint)

    def paint(self, event=None):
        if unchanged_size(self, event): return
        if not hasattr(self, '_track'):
            self._track = self.create_line(12, 12, 32, 12, width=23, capstyle='round')
            self._knob = self.create_oval(0, 4, 16, 20, fill='white', outline='')
            self._shown = None
        on = self.variable.get()
        if self._shown == on: return
        self._shown = on
        color = BLUE if on else '#cad8e3'
        self.itemconfigure(self._track, fill=color)
        x = 32 if on else 12
        self.coords(self._knob, x-8, 4, x+8, 20)


class MetricChip(tk.Canvas):
    def __init__(self, parent, text, variable):
        super().__init__(parent, height=40, width=155, bg='white', highlightthickness=0, cursor='hand2', takefocus=1)
        self.text, self.variable = text, variable
        variable.trace_add('write', lambda *_: self.paint())
        self.bind('<Configure>', self.paint)
        self.bind('<Button-1>', lambda e: variable.set(not variable.get()))
        self.bind('<space>', lambda e: variable.set(not variable.get()))

    def paint(self, event=None):
        if unchanged_size(self, event): return
        if not hasattr(self, '_box'):
            self._body = self.create_rectangle(1, 1, 1, 37)
            self._box = self.create_rectangle(12, 12, 24, 24)
            self._check = self.create_line(14, 18, 17, 21, 22, 15, fill='white', width=2)
            self.create_text(34, 19, anchor='w', text=self.text, font=(FONT, 10), fill=NAVY)
            self._layout = self._shown = None
        w = self.winfo_width()
        if self._layout != w:
            self._layout = w
            self.coords(self._body, 1, 1, w-2, 37)
        on = self.variable.get()
        if self._shown == on: return
        self._shown = on
        self.itemconfigure(self._body, fill='#edf8ff' if on else '#f8fafc', outline='#b9e3ff' if on else LINE)
        self.itemconfigure(self._box, fill=BLUE if on else 'white', outline=BLUE if on else '#bed0df')
        self.itemconfigure(self._check, state='normal' if on else 'hidden')


class StatCard(tk.Canvas):
    def __init__(self, parent, title, number):
        super().__init__(parent, height=103, bg='white', highlightthickness=0)
        self.title, self.number, self.value = title, number, None
        self.bind('<Configure>', self.paint)

    def set(self, value):
        if self.value == value: return
        self.value = value
        self.paint()

    def paint(self, event=None):
        if unchanged_size(self, event): return
        if not hasattr(self, '_reading'):
            self._corner = self.create_polygon(0, 0, 0, 0, fill='#edf8ff', outline='')
            self._number = self.create_text(0, 17, text=self.number, fill='#acd9f7', font=('Segoe UI', 11, 'bold'))
            self.create_text(18, 21, text=self.title, anchor='w', font=(FONT, 9), fill=MUTED)
            self._reading = self.create_text(18, 59, anchor='w', font=('Segoe UI', 28, 'bold'), fill=NAVY)
            self._unit = self.create_text(0, 65, text='%', anchor='e', font=('Segoe UI', 12), fill=BLUE)
            self._track = self.create_rectangle(18, 87, 18, 90, fill='#eaf1f6', outline='')
            self._bar = self.create_rectangle(18, 87, 18, 90, fill=CYAN, outline='')
            self._layout = None
            self._shown = object()
        w = self.winfo_width()
        resized = self._layout != w
        if resized:
            self._layout = w
            self.coords(self._corner, w-44, 0, w, 0, w, 44)
            self.coords(self._number, w-16, 17)
            self.coords(self._unit, w-20, 65)
            self.coords(self._track, 18, 87, w-18, 90)
        if self._shown != self.value or resized:
            self._shown = self.value
            self.itemconfigure(self._reading, text='--' if self.value is None else str(self.value))
            self.itemconfigure(self._bar, state='hidden' if self.value is None else 'normal')
            self.coords(self._bar, 18, 87, 18+(w-36)*min(100,max(0,self.value or 0))/100, 90)


class Screen(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent, height=132, bg='white', highlightthickness=0)
        self.variable = variable
        variable.trace_add('write', lambda *_: self.paint())
        self.bind('<Configure>', self.paint)
        self.bind('<Map>', lambda _: self.paint())

    def paint(self, event=None):
        if unchanged_size(self, event): return
        if not self.winfo_ismapped():
            return
        if not hasattr(self, '_label'):
            self._shadow = self.create_polygon(0, 0, 0, 0, fill='#dceaf4', outline='')
            self._face = self.create_polygon(0, 0, 0, 0, fill='#eff9ff', outline='#b9dcf2')
            self._dots = {}
            self._accent = self.create_line(25, 21, 47, 21, fill=BLUE, width=3)
            self._live = self.create_text(0, 25, text='LIVE', anchor='e', fill=BLUE, font=('Segoe UI', 8, 'bold'))
            self._label = self.create_text(0, 109, fill=NAVY, justify='center')
            self._caption = self.create_text(0, 176, text='SKYLYRICS  /  DISPLAY OUTPUT', fill='#89b8d6', font=('Segoe UI', 8))
            self._bars = [self.create_rectangle(0, 213, 0, 219, fill=BLUE if i == 0 else '#c7e5f8', outline='') for i in range(4)]
            self._layout = self._shown = None
        w, h = self.winfo_width(), self.winfo_height()
        if self._layout != (w, h):
            self._layout = (w, h)
            scale = max(.35, h/225)
            self.coords(self._shadow, 16, 13*scale, w-12, 13*scale, w-12, 188*scale, w-30, 206*scale, 16, 206*scale)
            self.coords(self._face, 12, 7*scale, w-17, 7*scale, w-17, 182*scale, w-35, 200*scale, 12, 200*scale)
            for x in range(23, w-22, 18):
                if x not in self._dots:
                    self._dots[x] = [self.create_oval(0, 0, 1, 1, fill='#cfe6f6', outline='') for _ in range(24, 190, 18)]
                    for dot in self._dots[x]:
                        self.tag_lower(dot, self._accent)
            for x, dots in self._dots.items():
                for y, dot in zip(range(24, 190, 18), dots):
                    self.coords(dot, x, y*scale, x+1, (y+1)*scale)
                    self.itemconfigure(dot, state='normal' if x < w-22 else 'hidden')
            self.coords(self._accent, 25, 21*scale, 47, 21*scale)
            self.coords(self._live, w-30, 25*scale)
            self.coords(self._label, w/2-2, 109*scale)
            self.itemconfigure(self._label, width=max(80, w-65))
            self.coords(self._caption, w/2, 176*scale)
            for i, bar in enumerate(self._bars):
                self.coords(bar, w-58+i*7, 213*scale, w-55+i*7, 219*scale)
        text = self.variable.get()
        if len(text) > 96:
            text = text[:93]+'…'
        size = 18 if len(text) < 28 else 14 if len(text) < 64 else 11
        if self._shown != (text, size):
            self._shown = (text, size)
            self.itemconfigure(self._label, text=text, font=(FONT, size, 'bold'))

