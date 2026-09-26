"""SkyLyrics media metadata bridge. Windows 10 1809+ / Windows 11."""
import asyncio
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta, timezone
from lyrics import LocalLyrics
from idle_display import IdleClock, settings_from, display_pages, idle_needs_stats
from system_stats import SystemStats

from winrt.windows.media import (
    MediaPlaybackStatus, MediaPlaybackType, SystemMediaTransportControlsButton,
    SystemMediaTransportControlsTimelineProperties,
)
from winrt.windows.media.playback import MediaPlayer
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

APP_ID = 'K1001.MediaBridge'
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'K1001Bridge'
ZERO = timedelta(0)


def other_player_playing(sessions, excluded=''):
    for session in sessions:
        try:
            if session.source_app_user_model_id != excluded and int(session.get_playback_info().playback_status) == 4:
                return True
        except Exception:
            # A different app can close between the session list and this query.
            continue
    return False


def position_now(timeline, playing, rate):
    position = timeline.position
    # A zero/ancient timestamp means the app does not provide a usable timeline.
    if playing and timeline.last_updated_time.year > 2000:
        elapsed = max(0, (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds())
        position += timedelta(seconds=elapsed * (1.0 if rate is None else rate))
    position = max(timeline.start_time, position, ZERO)
    if timeline.end_time > timeline.start_time:
        position = min(position, timeline.end_time)
    return position


class Bridge:
    def __init__(self, events):
        self.events = events
        self.commands = queue.Queue()
        self.mode = 'stopped'
        self.selected = ''
        self.source = None
        self.source_id = ''
        self.last_metadata = None
        self.output_disabled = False
        self.last_events = {}
        self.last_choices = None
        self.last_session_reclaim = 0.0
        self.closing = False
        self.loop = None
        self.smtc = None
        self.lyrics = LocalLyrics()
        self.lyrics_enabled = True
        self.settings = settings_from({})
        self.idle_clock = IdleClock()
        self.idle_started = None
        self.preview_until = 0
        self.stats = SystemStats()

    def emit(self, kind, value):
        if kind in ('status', 'track', 'output', 'choices'):
            if kind in self.last_events and self.last_events[kind] == value:
                return
            self.last_events[kind] = value
        self.events.put((kind, value))

    def start_thread(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            asyncio.run(self.main())
        except Exception:
            logging.exception('Bridge worker failed')
            self.emit('error', '启动失败；请查看诊断日志。')
        finally:
            self.emit('closed', None)

    def submit(self, action, value=None):
        self.commands.put((action, value))

    def disable(self):
        if self.smtc and not self.output_disabled:
            self.smtc.playback_status = MediaPlaybackStatus.STOPPED
            self.smtc.display_updater.clear_all()
            self.smtc.display_updater.update()
            self.smtc.is_enabled = False
            self.output_disabled = True
        self.last_metadata = None
        self.source = None
        self.source_id = ''

    def on_button(self, sender, args):
        # WinRT calls this on its own thread. Marshal back to the worker loop.
        if self.loop and not self.closing:
            self.loop.call_soon_threadsafe(self.submit, 'button', args.button)

    async def handle_button(self, button):
        if self.mode != 'auto' or self.source is None:
            return
        methods = {
            SystemMediaTransportControlsButton.PLAY: 'try_play_async',
            SystemMediaTransportControlsButton.PAUSE: 'try_pause_async',
            SystemMediaTransportControlsButton.NEXT: 'try_skip_next_async',
            SystemMediaTransportControlsButton.PREVIOUS: 'try_skip_previous_async',
            SystemMediaTransportControlsButton.STOP: 'try_stop_async',
        }
        name = methods.get(button)
        if name:
            ok = await asyncio.wait_for(getattr(self.source, name)(), 3)
            if not ok:
                self.emit('status', '播放器未接受这次控制指令。')

    def publish(self, title, artist='', album='', playing=True, timeline=None, rate=None):
        c = self.smtc
        self.output_disabled = False
        c.is_enabled = True
        # Keep the session usable even when a source omits capability flags.
        c.is_play_enabled = True
        c.is_pause_enabled = True
        metadata = (title, artist, album)
        if metadata != self.last_metadata:
            updater = c.display_updater
            updater.type = MediaPlaybackType.MUSIC
            updater.music_properties.title = title
            updater.music_properties.artist = artist
            updater.music_properties.album_title = album
            updater.update()
            self.last_metadata = metadata
            self.emit('output', title)
            logging.debug('Published metadata update from %s', self.source_id or 'manual')
        c.playback_status = MediaPlaybackStatus.PLAYING if playing else MediaPlaybackStatus.PAUSED
        props = SystemMediaTransportControlsTimelineProperties()
        if timeline and timeline.end_time > timeline.start_time:
            props.start_time = max(ZERO, timeline.start_time)
            props.end_time = max(props.start_time, timeline.end_time)
            props.min_seek_time = props.start_time
            props.max_seek_time = props.end_time
            props.position = position_now(timeline, playing, rate)
        else:
            props.start_time = props.end_time = props.min_seek_time = props.max_seek_time = props.position = ZERO
        c.update_timeline_properties(props)
        return props.position, props.end_time

    async def show_idle(self, now):
        self.stats.set_active('idle', idle_needs_stats(self.settings))
        if self.idle_started is None:
            self.idle_started = now
            self.smtc.is_enabled = False
            self.smtc.playback_status = MediaPlaybackStatus.STOPPED
            self.last_metadata = None
            await asyncio.sleep(0.15)
        pages = display_pages(self.settings, self.stats.snapshot())
        index = int((now - self.idle_started) / self.settings['rotation_seconds']) % len(pages)
        self.publish(pages[index], '晴空歌词 · 待机显示', playing=False)
        self.emit('status', '正在预览待机显示' if now < self.preview_until else '待机显示 · 恢复播放后自动显示歌词')

    async def poll(self):
        sessions = [s for s in self.manager.get_sessions() if s.source_app_user_model_id != APP_ID]
        choices = sorted(set(s.source_app_user_model_id for s in sessions))
        if choices != self.last_choices:
            self.last_choices = choices
            self.emit('choices', choices)
        if self.mode != 'auto':
            self.stats.set_active('idle', False)
            return
        now = time.monotonic()
        # Snapshot once. An app may close while being queried; skip only that app.
        candidates = []
        for s in sessions:
            if self.selected and s.source_app_user_model_id != self.selected:
                continue
            try:
                p = await asyncio.wait_for(s.try_get_media_properties_async(), 3)
                info = s.get_playback_info()
                if p.title and int(info.playback_status) in (4, 5):
                    candidates.append((s, p, info))
            except Exception as exc:
                logging.debug('Source unavailable: %s', exc)
        if not candidates:
            self.source = None
            self.source_id = ''
            other_playing = other_player_playing(sessions)
            active = self.idle_clock.active(other_playing, now, self.settings['idle_enabled'], self.settings['idle_minutes'])
            self.update_sampling(now, other_playing)
            if not other_playing and (active or now < self.preview_until):
                self.smtc.is_next_enabled = self.smtc.is_previous_enabled = self.smtc.is_stop_enabled = False
                await self.show_idle(now)
                return
            self.idle_started = None
            self.disable()
            self.emit('output', '等待音乐播放')
            self.emit('track', ('等待播放器提供歌曲信息', '', ''))
            self.emit('status', '等待所选播放器…' if self.selected else '等待音乐播放…')
            return
        current = self.manager.get_current_session()
        current_id = current.source_app_user_model_id if current else ''
        # Playing sources beat paused sources; never re-import our own session.
        candidates.sort(key=lambda x: (
            int(x[2].playback_status) == 4,
            x[0].source_app_user_model_id == current_id,
            x[0].source_app_user_model_id == self.source_id,
        ), reverse=True)
        s, p, info = candidates[0]
        self.source = s
        self.source_id = s.source_app_user_model_id
        controls = info.controls
        self.smtc.is_next_enabled = controls.is_next_enabled
        self.smtc.is_previous_enabled = controls.is_previous_enabled
        self.smtc.is_stop_enabled = controls.is_stop_enabled
        timeline = s.get_timeline_properties()
        playing = int(info.playback_status) == 4
        other_playing = other_player_playing(sessions, self.source_id)
        active = self.idle_clock.active(playing or other_playing, now,
                                       self.settings['idle_enabled'], self.settings['idle_minutes'])
        self.update_sampling(now, playing or other_playing)
        if not other_playing and (active or now < self.preview_until):
            await self.show_idle(now)
            return
        if self.idle_started is not None:
            self.last_metadata = None
            self.idle_started = None
        # Resuming the player can make Windows route AVRCP directly to it.
        # Re-register our session only when that source displaced us, with a
        # cooldown. Do not compete with unrelated media apps selected by users.
        if playing and current_id == self.source_id and time.monotonic() - self.last_session_reclaim >= 2:
            self.smtc.is_enabled = False
            self.smtc.playback_status = MediaPlaybackStatus.STOPPED
            self.last_metadata = None
            self.last_session_reclaim = time.monotonic()
            logging.info('Reclaiming media output after source became current')
            # Let Windows observe the inactive session before re-enabling it.
            await asyncio.sleep(0.15)
        output_title = p.title
        lyric_status = ''
        if self.lyrics_enabled and self.source_id.lower() == 'qqmusic.exe':
            lyric = await self.lyrics.current(p.title, p.artist, p.album_title,
                timeline.end_time.total_seconds(), position_now(timeline, playing, info.playback_rate).total_seconds())
            output_title = lyric or p.title
            lyric_status = ' · ' + self.lyrics.status
        position, duration = self.publish(output_title, p.artist, p.album_title,
            playing, timeline, info.playback_rate)
        self.emit('track', (p.title, p.artist, f'{self.source_id}  ·  {format_time(position)} / {format_time(duration)}'))
        self.emit('status', ('正在转发 · 播放中' if playing else '正在转发 · 播放器已暂停') + lyric_status)

    def update_sampling(self, now, playing):
        almost_idle = (not playing and self.settings['idle_enabled'] and self.idle_clock.since is not None
                       and now-self.idle_clock.since >= max(0, self.settings['idle_minutes']*60-10))
        self.stats.set_active('idle', idle_needs_stats(self.settings) and
                              (almost_idle or now < self.preview_until))

    async def main(self):
        self.loop = asyncio.get_running_loop()
        self.manager = await Manager.request_async()
        player = MediaPlayer()
        player.command_manager.is_enabled = False
        self.smtc = player.system_media_transport_controls
        token = self.smtc.add_button_pressed(self.on_button)
        self.smtc.is_enabled = False
        self.stats.start()
        self.emit('ready', None)
        try:
            while not self.closing:
                try:
                    while not self.commands.empty():
                        action, value = self.commands.get_nowait()
                        if action == 'close':
                            self.closing = True
                            break
                        if action == 'auto':
                            self.selected = value or ''
                            self.mode = 'auto'
                            self.last_metadata = None
                            self.idle_clock.since = None
                            self.idle_started = None
                            self.preview_until = 0
                        elif action == 'stop':
                            self.mode = 'stopped'
                            self.disable()
                            self.emit('status', '已停止转发')
                            self.emit('track', ('转发已停止', '', ''))
                            self.emit('output', '转发已停止')
                            self.preview_until = 0
                        elif action == 'test':
                            self.mode = 'test'
                            self.source = None
                            self.source_id = ''
                            self.smtc.is_next_enabled = self.smtc.is_previous_enabled = self.smtc.is_stop_enabled = False
                            title = value or 'K1001 TEST 123'
                            self.publish(title, 'Windows bridge')
                            self.emit('track', (title, 'Windows bridge', '手动测试'))
                            self.emit('status', '测试文字已发布；点击“开始转发”恢复自动模式。')
                        elif action == 'button':
                            await self.handle_button(value)
                        elif action == 'lyrics':
                            self.lyrics_enabled = bool(value)
                        elif action == 'settings':
                            self.settings = settings_from(value)
                            self.selected = self.settings['source']
                            self.lyrics_enabled = self.settings['lyrics']
                            self.idle_started = None
                        elif action == 'preview_idle':
                            self.mode = 'auto'
                            self.preview_until = time.monotonic() + 15
                            self.idle_started = None
                    if self.closing:
                        break
                    await self.poll()
                except Exception:
                    logging.exception('Bridge iteration failed')
                    try:
                        self.disable()
                    except Exception:
                        logging.exception('Could not clear media output')
                    self.emit('status', '读取暂时失败，正在重试…')
                await asyncio.sleep(0.2)
        finally:
            for name, cleanup in [('sensors', self.stats.close), ('media output', self.disable),
                                  ('media buttons', lambda: self.smtc.remove_button_pressed(token)),
                                  ('media player', player.close)]:
                try:
                    cleanup()
                except Exception:
                    logging.exception('Could not close %s', name)
            await self.lyrics.close()


def format_time(value):
    seconds = max(0, int(value.total_seconds()))
    return f'{seconds // 60}:{seconds % 60:02d}'


class App:
    def __init__(self, root):
        self.root = root
        root.title('晴空歌词 · SkyLyrics')
        root.geometry('650x430')
        root.minsize(590, 400)
        root.configure(bg='#f3f5f7')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background='#f3f5f7')
        style.configure('TLabel', background='#f3f5f7')
        style.configure('TButton', padding=(12, 8))
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='晴空歌词 · SkyLyrics', font=('Microsoft YaHei UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='通过 Windows 媒体通道转发歌名、歌手和播放进度。').pack(anchor='w', pady=(6, 20))
        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Label(row, text='来源播放器').pack(side='left', padx=(0, 10))
        self.choice = ttk.Combobox(row, state='readonly', values=['自动选择'], width=35)
        self.choice.current(0)
        self.choice.pack(side='left', fill='x', expand=True)
        self.choice.bind('<<ComboboxSelected>>', self.selection_changed)
        self.title = tk.StringVar(value='正在初始化…')
        self.artist = tk.StringVar()
        self.detail = tk.StringVar()
        ttk.Label(frame, textvariable=self.title, font=('Microsoft YaHei UI', 15, 'bold'), wraplength=560).pack(anchor='w', pady=(22, 4))
        ttk.Label(frame, textvariable=self.artist).pack(anchor='w')
        ttk.Label(frame, textvariable=self.detail, foreground='#657080').pack(anchor='w', pady=(5, 15))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        self.start_btn = ttk.Button(buttons, text='开始转发', command=self.start)
        self.start_btn.pack(side='left')
        ttk.Button(buttons, text='停止转发', command=self.stop).pack(side='left', padx=8)
        ttk.Button(buttons, text='发送测试文字', command=self.test).pack(side='left')
        self.status = tk.StringVar(value='正在连接系统媒体服务…')
        ttk.Label(frame, textvariable=self.status, foreground='#246b55', wraplength=570).pack(anchor='w', pady=(16, 8))
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        ttk.Label(footer, text='保持歌词显示器蓝牙连接；关闭窗口即退出。', foreground='#657080').pack(side='left')
        ttk.Button(footer, text='诊断信息', command=self.diagnostics).pack(side='right')
        self.events = queue.Queue()
        self.bridge = Bridge(self.events)
        self.auto = False
        self.closing = False
        self.bridge.start_thread()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll_ui)

    def selection_changed(self, event=None):
        if self.auto:
            self.start()

    def start(self):
        self.auto = True
        selected = self.choice.get()
        self.bridge.submit('auto', '' if selected == '自动选择' else selected)

    def stop(self):
        self.auto = False
        self.bridge.submit('stop')

    def test(self):
        self.auto = False
        self.bridge.submit('test', 'K1001 TEST 123')

    def diagnostics(self):
        messagebox.showinfo('诊断信息',
            f'转发方式：Windows SMTC → 系统蓝牙 AVRCP\n'
            f'当前模式：{self.bridge.mode}\n'
            f'来源：{self.bridge.source_id or "未选定"}\n\n'
            f'本程序发布系统媒体信息，不能读取屏幕确认显示。\n'
            f'如果无显示，请先点击“发送测试文字”。\n'
            f'日志：{DATA_DIR / "bridge.log"}\n\n'
            f'逐句歌词需要播放器额外提供；本版不下载歌词。')

    def close(self):
        self.closing = True
        self.status.set('正在停止转发并退出…')
        self.bridge.submit('close')

    def poll_ui(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'ready':
                self.start()
            elif kind == 'choices':
                selected = self.choice.get()
                values = ['自动选择'] + value
                # Preserve a manually selected app while it is temporarily closed.
                if selected and selected not in values:
                    values.append(selected)
                self.choice['values'] = values
            elif kind == 'track':
                self.title.set(value[0])
                self.artist.set(value[1])
                self.detail.set(value[2])
            elif kind in ('status', 'error'):
                self.status.set(value)
            elif kind == 'closed':
                if self.closing:
                    self.root.destroy()
                    return
                self.status.set('转发服务已退出；请查看诊断日志。')
        if self.closing and not self.bridge.thread.is_alive():
            self.root.destroy()
            return
        self.root.after(100, self.poll_ui)


async def check():
    manager = await Manager.request_async()
    rows = []
    for session in manager.get_sessions():
        p = await session.try_get_media_properties_async()
        rows.append({'app': session.source_app_user_model_id, 'title': p.title,
                     'artist': p.artist, 'state': int(session.get_playback_info().playback_status)})
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    if '--check' in sys.argv:
        asyncio.run(check())
        return
    # Single instance prevents two bridges from competing for the current session.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'Local\\K1001MediaBridge')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None, '转发器已经在运行，请查看任务栏中的窗口。', '晴空歌词', 0)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        DATA_DIR / 'bridge.log', maxBytes=250000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(message)s')
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        root = tk.Tk()
        App(root)
        root.mainloop()
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
