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
        self.bind('<Configure>', self.paint)

    def paint(self, event=None):
        if unchanged_size(self, event): return
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        for x in range(-120, w+160, 240):
            for y in range(-100, h+160, 210):
                self.create_polygon(x, y+190, x+112, y, x+224, y+190, fill='', outline='#eaf2f7', width=7)
        for x in range(30, w, 110):
            for y in range(30, h, 110):
                self.create_line(x-3, y, x+3, y, fill='#dcecf7')
                self.create_line(x, y-3, x, y+3, fill='#dcecf7')
        self.create_polygon(w-140, 0, w, 0, w, 210, fill='#e1f6fd', outline='')
        self.create_polygon(0, h-125, 0, h, 190, h, fill='#e9f4fb', outline='')


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
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()-4
        fill = BLUE if self.primary else ('#e7f6ff' if self.hover else 'white')
        if self.primary and self.hover:
            fill = '#0078cc'
        self.create_polygon(11, 4, w-1, 4, w-12, h+3, 0, h+3, fill='#dce8f1', outline='')
        self.create_polygon(12, 0, w-1, 0, w-13, h, 1, h, fill=fill, outline=BLUE if self.primary else '#d6e6f2')
        self.create_text(w/2, h/2, text=self.text, fill='white' if self.primary else NAVY,
                         font=(FONT, 10 if self.small else 11, 'bold'))


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
        self.delete('all')
        on = self.variable.get()
        color = BLUE if on else '#cad8e3'
        self.create_line(12, 12, 32, 12, width=23, capstyle='round', fill=color)
        x = 32 if on else 12
        self.create_oval(x-8, 4, x+8, 20, fill='white', outline='')


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
        self.delete('all')
        w = self.winfo_width()
        on = self.variable.get()
        self.create_rectangle(1, 1, w-2, 37, fill='#edf8ff' if on else '#f8fafc', outline='#b9e3ff' if on else LINE)
        self.create_rectangle(12, 12, 24, 24, fill=BLUE if on else 'white', outline=BLUE if on else '#bed0df')
        if on:
            self.create_line(14, 18, 17, 21, 22, 15, fill='white', width=2)
        self.create_text(34, 19, anchor='w', text=self.text, font=(FONT, 10), fill=NAVY)


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
        self.delete('all')
        w = self.winfo_width()
        self.create_polygon(w-44, 0, w, 0, w, 44, fill='#edf8ff', outline='')
        self.create_text(w-16, 17, text=self.number, fill='#acd9f7', font=('Segoe UI', 11, 'bold'))
        self.create_text(18, 21, text=self.title, anchor='w', font=(FONT, 9), fill=MUTED)
        self.create_text(18, 59, text='--' if self.value is None else str(self.value), anchor='w', font=('Segoe UI', 28, 'bold'), fill=NAVY)
        self.create_text(w-20, 65, text='%', anchor='e', font=('Segoe UI', 12), fill=BLUE)
        self.create_rectangle(18, 87, w-18, 90, fill='#eaf1f6', outline='')
        if self.value is not None:
            self.create_rectangle(18, 87, 18+(w-36)*min(100,max(0,self.value))/100, 90, fill=CYAN, outline='')


class Screen(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent, height=132, bg='white', highlightthickness=0)
        self.variable = variable
        variable.trace_add('write', lambda *_: self.paint())
        self.bind('<Configure>', self.paint)
        self.bind('<Map>', self.paint)

    def paint(self, event=None):
        if unchanged_size(self, event): return
        if not self.winfo_ismapped():
            return
        self.delete('all')
        w = self.winfo_width()
        self.create_polygon(16, 13, w-12, 13, w-12, 188, w-30, 206, 16, 206, fill='#dceaf4', outline='')
        self.create_polygon(12, 7, w-17, 7, w-17, 182, w-35, 200, 12, 200, fill='#eff9ff', outline='#b9dcf2')
        for x in range(23, w-22, 18):
            for y in range(24, 190, 18):
                self.create_oval(x, y, x+1, y+1, fill='#cfe6f6', outline='')
        self.create_line(25, 21, 47, 21, fill=BLUE, width=3)
        self.create_text(w-30, 25, text='LIVE', anchor='e', fill=BLUE, font=('Segoe UI', 8, 'bold'))
        text = self.variable.get()
        if len(text) > 96:
            text = text[:93]+'…'
        size = 18 if len(text) < 28 else 14 if len(text) < 64 else 11
        self.create_text(w/2-2, 109, text=text, width=max(80,w-65), fill=NAVY,
                         font=(FONT, size, 'bold'), justify='center')
        self.create_text(w/2, 176, text='SKYLYRICS  /  DISPLAY OUTPUT', fill='#89b8d6', font=('Segoe UI', 8))
        for i in range(4):
            self.create_rectangle(w-58+i*7, 213, w-55+i*7, 219, fill=BLUE if i==0 else '#c7e5f8', outline='')
        self.scale('all', 0, 0, 1, max(.35, self.winfo_height()/225))

