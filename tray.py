"""Silent, single-process tray entry point for K1001 Bridge."""
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import sys
import threading
import winreg
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from bridge import Bridge, APP_ID, DATA_DIR

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'K1001Bridge'


def startup_command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --background'
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    return f'"{pythonw}" "{Path(__file__).resolve()}" --background'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return value == startup_command()
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def make_image():
    image = Image.new('RGBA', (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill='#16775f')
    draw.line((33, 17, 33, 44), fill='white', width=5)
    draw.line((33, 17, 48, 13, 48, 38), fill='white', width=5)
    draw.ellipse((20, 39, 35, 51), fill='white')
    draw.ellipse((35, 33, 50, 45), fill='white')
    return image


class TrayApp:
    def __init__(self):
        self.events = queue.Queue()
        self.bridge = Bridge(self.events)
        self.quit_event = threading.Event()
        self.status = '正在初始化'
        self.choices = []
        self.selected = 'QQMusic.exe'
        self.lyrics_enabled = True
        self.config = DATA_DIR / 'settings.json'
        try:
            saved = json.loads(self.config.read_text(encoding='utf-8'))
            self.selected = saved.get('source', 'QQMusic.exe')
            self.lyrics_enabled = saved.get('lyrics', True)
        except (OSError, ValueError, AttributeError):
            pass
        self.icon = pystray.Icon('K1001Bridge', make_image(), 'K1001 歌曲信息转发器', self.menu())

    def source_menu(self):
        values = [''] + sorted(set(self.choices + ([self.selected] if self.selected else [])))
        def entry(value):
            def select(icon, item):
                self.selected = value
                self.save_settings()
                self.bridge.submit('auto', value)
            return pystray.MenuItem(value or '自动选择', select,
                                    checked=lambda item: self.selected == value, radio=True)
        return tuple(entry(value) for value in values)

    def menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda item: 'K1001 · ' + self.status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('来源播放器', pystray.Menu(self.source_menu)),
            pystray.MenuItem('显示 QQ 音乐歌词', self.toggle_lyrics,
                            checked=lambda item: self.lyrics_enabled),
            pystray.MenuItem('开始转发', lambda: self.bridge.submit('auto', self.selected)),
            pystray.MenuItem('停止转发', lambda: self.bridge.submit('stop')),
            pystray.MenuItem('发送测试文字', lambda: self.bridge.submit('test', 'K1001 TEST 123')),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('开机自启动', self.toggle_startup, checked=lambda item: startup_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', self.exit),
        )

    def save_settings(self):
        try:
            temp = self.config.with_suffix('.tmp')
            temp.write_text(json.dumps({'source': self.selected, 'lyrics': self.lyrics_enabled},
                                       ensure_ascii=False), encoding='utf-8')
            temp.replace(self.config)
        except OSError:
            logging.exception('Could not save settings')

    def toggle_lyrics(self, icon, item):
        self.lyrics_enabled = not self.lyrics_enabled
        self.save_settings()
        self.bridge.submit('lyrics', self.lyrics_enabled)

    def toggle_startup(self, icon, item):
        try:
            set_startup(not startup_enabled())
        except OSError:
            logging.exception('Could not change startup registration')
            self.status = '自启动设置失败，请查看日志'

    def exit(self, icon=None, item=None):
        # The icon's event loop stays responsive while the media session shuts down.
        if self.quit_event.is_set():
            return
        self.quit_event.set()
        self.bridge.submit('close')
        threading.Thread(target=self.finish_exit, daemon=True).start()

    def finish_exit(self):
        self.bridge.thread.join(timeout=15)
        self.icon.stop()

    def consume_events(self):
        while not self.quit_event.is_set():
            try:
                kind, value = self.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == 'ready':
                self.bridge.submit('lyrics', self.lyrics_enabled)
                self.bridge.submit('auto', self.selected)
            elif kind == 'choices':
                self.choices = value
                self.icon.update_menu()
            elif kind in ('status', 'error'):
                self.status = value
                self.icon.title = ('K1001 · ' + value)[:127]
            elif kind == 'closed' and not self.quit_event.is_set():
                self.status = '服务已停止，请退出后重新打开'
                self.icon.title = 'K1001 · ' + self.status

    def setup(self, icon):
        icon.visible = True
        self.bridge.start_thread()
        threading.Thread(target=self.consume_events, daemon=True).start()
        logging.info('Tray ready; pid=%s; windowless startup', os.getpid())

    def run(self):
        self.icon.run(setup=self.setup)
        logging.info('Tray exited; pid=%s', os.getpid())


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, 'Local\\K1001MediaBridge')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return  # Silent duplicate launch: no dialog, no second worker.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        DATA_DIR / 'bridge.log', maxBytes=250000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(message)s')
    try:
        TrayApp().run()
    finally:
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
