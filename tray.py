"""Silent, single-process tray entry point for SkyLyrics."""
import ctypes
import faulthandler
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import winreg
from pathlib import Path

import pystray
from PIL import Image
from bridge import Bridge, APP_ID, DATA_DIR

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'K1001Bridge'


def startup_command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --background'
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    return f'"{pythonw}" "{Path(__file__).resolve()}" --background'


def startup_link():
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/SkyLyrics.lnk'


def old_startup_link():
    return startup_link().with_name('K1001Bridge.lnk')


def legacy_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return value == startup_command()
    except FileNotFoundError:
        return False


def startup_enabled():
    return startup_link().exists() or old_startup_link().exists() or legacy_startup_enabled()


def set_startup(enabled):
    link = startup_link()
    if enabled:
        link.parent.mkdir(parents=True, exist_ok=True)
        frozen = getattr(sys, 'frozen', False)
        target = Path(sys.executable) if frozen else Path(sys.executable).with_name('pythonw.exe')
        arguments = '--background' if frozen else f'"{Path(__file__).resolve()}" --background'
        env = dict(os.environ, K1001_STARTUP_LINK=str(link), K1001_TARGET=str(target),
                   K1001_ARGUMENTS=arguments, K1001_WORKDIR=str(target.parent))
        script = """$ErrorActionPreference = 'Stop'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($env:K1001_STARTUP_LINK)
$shortcut.TargetPath = $env:K1001_TARGET
$shortcut.Arguments = $env:K1001_ARGUMENTS
$shortcut.WorkingDirectory = $env:K1001_WORKDIR
$shortcut.WindowStyle = 7
$shortcut.Description = 'SkyLyrics - 晴空歌词'
$shortcut.Save()
"""
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                       env=env, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                       timeout=20)
    else:
        link.unlink(missing_ok=True)
    old_startup_link().unlink(missing_ok=True)
    # Migrate the old registration, leaving only one startup entry.
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        try:
            winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass


def make_image():
    with Image.open(Path(__file__).parent / 'assets/logo.png') as image:
        return image.convert('RGBA').resize((64,64), Image.Resampling.LANCZOS)


class TrayApp:
    def __init__(self, show_event=None):
        import tkinter as tk
        from settings_ui import SettingsWindow
        from idle_display import settings_from
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = lambda kind, value, tb: logging.error(
            'UI callback failed', exc_info=(kind, value, tb))
        self.events = queue.Queue()
        self.settings_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='SettingsIO')
        self.saving = False
        self.bridge = Bridge(self.events)
        self.quit_event = threading.Event()
        self.config = DATA_DIR / 'settings.json'
        self.show_event = show_event
        self.status = '正在初始化'
        self.choices = []
        try:
            saved = json.loads(self.config.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        self.settings = settings_from(saved)
        from updater import Updater
        self.updater = Updater(self.events, DATA_DIR)
        self.selected = self.settings['source']
        self.lyrics_enabled = self.settings['lyrics']
        self.icon = pystray.Icon('K1001Bridge', make_image(), '晴空歌词 · SkyLyrics', self.menu())
        self.ui = SettingsWindow(self.root, self)
        self.root.protocol('WM_DELETE_WINDOW', self.hide)
        self.root.after(100, self.consume_events)
        self.root.after(30000, self.check_updates_automatically)

    def check_updates_automatically(self):
        if self.quit_event.is_set():
            return
        if self.settings['auto_update_check']:
            self.updater.check()
        self.root.after(60 * 60 * 1000, self.check_updates_automatically)

    def check_updates(self):
        self.show()
        self.ui.switch(3)
        self.updater.check(manual=True)

    def install_update(self):
        from tkinter import messagebox
        if self.updater.busy:
            return
        if not self.updater.release:
            self.updater.check(manual=True)
            return
        if self.saving:
            self.ui.update_note.set('请等待设置保存完成后再安装。')
            return
        if messagebox.askokcancel('安装更新', '下载完成后会重启晴空歌词，转发将短暂停止。\n已保存的设置会保留；未保存的修改不会保留。\n\n现在下载并安装吗？', parent=self.root):
            self.updater.install()

    def post(self, action):
        self.events.put(('ui_action', action))

    def menu(self):
        return pystray.Menu(
            pystray.MenuItem('打开控制面板', lambda: self.post('show'), default=True),
            pystray.MenuItem(lambda item: '晴空歌词 · ' + self.status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('开始转发', lambda: self.bridge.submit('auto', self.selected)),
            pystray.MenuItem('停止转发', lambda: self.bridge.submit('stop')),
            pystray.MenuItem('预览待机显示 15 秒', lambda: self.bridge.submit('preview_idle')),
            pystray.MenuItem('开机自启动', lambda: self.post('startup'), checked=lambda item: startup_enabled()),
            pystray.MenuItem('检查更新', lambda: self.post('update')),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', lambda: self.post('exit')),
        )

    def apply_settings(self, settings, startup, preview=False):
        from idle_display import settings_from
        if self.saving:
            self.ui.message.set('设置正在保存，请稍候。')
            return False
        new = settings_from(settings)
        self.saving = True
        self.ui.message.set('正在保存设置…')
        def write():
            try:
                # Startup target repair already runs once at application launch.
                if startup != startup_enabled():
                    set_startup(startup)
                temp = self.config.with_suffix('.tmp')
                temp.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding='utf-8')
                temp.replace(self.config)
                self.events.put(('settings_saved', (new, preview)))
            except Exception:
                logging.exception('Could not save settings')
                self.events.put(('settings_failed', None))
        self.settings_worker.submit(write)
        return True

    def toggle_startup(self):
        def write():
            try:
                set_startup(not startup_enabled())
                self.events.put(('startup_saved', None))
            except Exception:
                logging.exception('Could not change startup')
                self.events.put(('settings_failed', None))
        self.settings_worker.submit(write)

    def show(self):
        self.bridge.stats.set_active('panel', True)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.ui.refresh_startup()

    def hide(self):
        self.root.withdraw()
        self.bridge.stats.set_active('panel', False)

    def exit(self):
        if self.quit_event.is_set():
            return
        self.quit_event.set()
        self.root.withdraw()
        self.bridge.submit('close')
        self.icon.stop()
        self.settings_worker.shutdown(wait=False)
        self.root.after(100, self.finish_exit)

    def finish_exit(self):
        if self.bridge.thread.is_alive():
            self.root.after(100, self.finish_exit)
        else:
            self.root.destroy()

    def consume_events(self):
        if self.quit_event.is_set():
            return
        self.bridge.stats.set_active('panel', self.root.state() in ('normal', 'zoomed'))
        if self.show_event and ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(self.show_event), 0) == 0:
            self.show()
        for _ in range(100):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'ui_action':
                if value == 'show':
                    self.show()
                elif value == 'exit':
                    self.exit()
                    return
                elif value == 'startup':
                    self.toggle_startup()
                elif value == 'update':
                    self.check_updates()
            elif kind == 'update_state':
                self.ui.update_state(value)
                if value.get('notify'):
                    try:
                        self.icon.notify('发现新版，可在控制面板的「软件更新」下载。', '晴空歌词更新')
                    except Exception:
                        logging.info('Update notification unavailable')
            elif kind == 'update_install_ready':
                self.exit()
                return
            elif kind == 'settings_saved':
                self.saving = False
                new, preview = value
                self.settings = new
                self.selected = new['source']
                self.lyrics_enabled = new['lyrics']
                self.bridge.submit('settings', new)
                if preview:
                    self.bridge.submit('preview_idle')
                self.ui.message.set('正在预览待机内容，15 秒后恢复自动模式。' if preview else '已保存 · 设置即时生效。')
                self.ui.refresh_startup()
                self.icon.update_menu()
            elif kind == 'startup_saved':
                self.ui.refresh_startup()
                self.icon.update_menu()
            elif kind == 'settings_failed':
                self.saving = False
                self.ui.message.set('保存失败，请检查程序日志后重试。')
            elif kind == 'ready':
                self.bridge.submit('settings', self.settings)
                self.bridge.submit('auto', self.selected)
                from updater import signal_ready
                signal_ready()
            elif kind == 'choices':
                self.choices = value
                self.ui.update_sources(value)
            elif kind in ('status', 'error'):
                if self.status != value:
                    self.status = value
                    self.icon.title = ('晴空歌词 · ' + value)[:127]
                    self.ui.status.set(value)
            elif kind == 'track':
                if self.ui.track.get() != value[0]:
                    self.ui.track.set(value[0])
                detail = value[1] + '  ' + value[2]
                if self.ui.detail.get() != detail:
                    self.ui.detail.set(detail)
            elif kind == 'output':
                self.ui.output.set(value)
            elif kind == 'closed':
                self.status = '转发服务已停止，请重新启动程序'
                self.ui.status.set(self.status)
        if self.root.state() in ('normal', 'zoomed'):
            self.ui.update_stats(self.bridge.stats.snapshot())
        self.root.after(250, self.consume_events)

    def setup(self, icon):
        icon.visible = True
        logging.info('Tray ready; pid=%s', os.getpid())

    def run(self):
        self.bridge.start_thread()
        threading.Thread(target=lambda: self.icon.run(setup=self.setup), daemon=True).start()
        if '--background' not in sys.argv:
            self.show()
        self.root.mainloop()
        logging.info('Application exited; pid=%s', os.getpid())


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    show_event = kernel.CreateEventW(None, False, False, 'Local\\K1001BridgeShow')
    handle = kernel.CreateMutexW(None, False, 'Local\\K1001MediaBridge')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        if '--background' not in sys.argv and show_event:
            kernel.SetEvent(show_event)
        kernel.CloseHandle(handle)
        if show_event:
            kernel.CloseHandle(show_event)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        DATA_DIR / 'bridge.log', maxBytes=250000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Process starting; pid=%s', os.getpid())
    # Keep native/Python fatal diagnostics even in a windowless executable.
    fatal_log = (DATA_DIR / 'crash.log').open('w', encoding='utf-8')
    faulthandler.enable(file=fatal_log, all_threads=True)
    try:
        if not (DATA_DIR / 'settings.json').exists():
            from idle_display import settings_from
            try:
                set_startup(True)
            except (OSError, subprocess.SubprocessError):
                logging.exception('Could not enable initial startup registration')
            (DATA_DIR / 'settings.json').write_text(json.dumps(settings_from({}), ensure_ascii=False, indent=2), encoding='utf-8')
        if startup_enabled():
            try:
                set_startup(True)
            except (OSError, subprocess.SubprocessError):
                logging.exception('Could not migrate startup registration')
        TrayApp(show_event).run()
    finally:
        faulthandler.disable()
        fatal_log.close()
        kernel.CloseHandle(handle)
        if show_event:
            kernel.CloseHandle(show_event)


if __name__ == '__main__':
    main()
