"""Optional CPU sensor worker; main UI and lyrics always retain normal privileges."""
import ctypes
from ctypes import wintypes as w
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import winreg


STATUS_TEXT = {
    'permission': 'CPU 温度：在「常规设置」完成一次自动启动配置。',
    'starting': 'CPU 温度：正在等待 Windows 授权或启动采集。',
    'cancelled': 'CPU 温度授权已取消，可以在「常规设置」重试。',
    'missing_driver': 'CPU 温度：缺少 PawnIO 驱动，详见「常规设置」。',
    'missing_component': 'CPU 温度采集组件缺失，请完整解压程序包。',
    'unavailable': '采集已启用，但当前硬件没有返回有效 CPU 温度。',
    'error': 'CPU 温度采集失败，可以在「常规设置」重新启用。',
    'timeout': 'CPU 温度采集超时，歌词转发继续运行，可重新启用采集。',
    'ready': 'CPU 温度来自内置采集组件。',
    'configured': 'CPU 温度自动启动已配置，正在连接采集程序。',
    'disabled': 'CPU 温度自动启动已关闭。',
}


def current_sid():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    api.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    api.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [w.LPVOID]
    token = w.HANDLE()
    if not api.OpenProcessToken(w.HANDLE(-1), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = w.DWORD()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0]
        sid_text = w.LPWSTR()
        if not api.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return sid_text.value
        finally:
            kernel.LocalFree(ctypes.cast(sid_text, w.LPVOID))
    finally:
        kernel.CloseHandle(token)


def installation_root(sid):
    folder = ctypes.create_unicode_buffer(260)
    shell = ctypes.WinDLL('shell32')
    if shell.SHGetFolderPathW(None, 0x26, None, 0, folder) != 0:
        raise OSError('Program Files directory unavailable')
    return Path(folder.value) / 'SkyLyrics Sensors' / sid


def installed_executable(root):
    try:
        version = (root / 'current.txt').read_text(encoding='ascii').strip()
        if not re.fullmatch('[a-f0-9]{16}', version):
            return None
        path = root / version / 'SkyLyricsSensors.exe'
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def parse_sample(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('status') not in STATUS_TEXT:
        raise ValueError('Invalid sensor response')
    result = {'cpu_temp_status': data['status']}
    value = data.get('cpu_temp')
    if data['status'] == 'ready':
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 130:
            raise ValueError('Invalid CPU temperature')
        result.update(cpu_temp=round(value, 1), cpu_temp_source='builtin')
    return result


def pawnio_installed():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return bool(winreg.QueryValueEx(key, 'DisplayVersion')[0])
    except OSError:
        return False


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [('cbSize', w.DWORD), ('fMask', w.ULONG), ('hwnd', w.HWND),
                ('lpVerb', w.LPCWSTR), ('lpFile', w.LPCWSTR), ('lpParameters', w.LPCWSTR),
                ('lpDirectory', w.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', w.HINSTANCE),
                ('lpIDList', w.LPVOID), ('lpClass', w.LPCWSTR), ('hkeyClass', w.HKEY),
                ('dwHotKey', w.DWORD), ('hIcon', w.HANDLE), ('hProcess', w.HANDLE)]


class CpuTemperature:
    def __init__(self):
        base = Path(__file__).resolve().parent / 'sensor_host'
        self.executable = base / 'SkyLyricsSensors.exe'
        if not self.executable.is_file():
            self.executable = base / 'bin' / 'SkyLyricsSensors.exe'
        self.setup_executable = self.executable.with_name('SkyLyricsSensorSetup.exe')
        self.sid = current_sid()
        self.install_root = installation_root(self.sid)
        self._last_kick = -60
        self.status = 'permission' if pawnio_installed() else 'missing_driver'
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._pipe = None
        self._starting = False
        self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self._kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
        self._kernel.CreateFileW.restype = w.HANDLE
        self._kernel.CloseHandle.argtypes = [w.HANDLE]
        self._kernel.GetProcessId.argtypes = [w.HANDLE]
        self._kernel.GetProcessId.restype = w.DWORD
        self._kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self._kernel.OpenProcess.restype = w.HANDLE
        self._kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        self._kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self._kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        self._kernel.GetNamedPipeServerProcessId.argtypes = [w.HANDLE, ctypes.POINTER(w.ULONG)]
        self._kernel.PeekNamedPipe.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, w.LPVOID, ctypes.POINTER(w.DWORD), w.LPVOID]
        self._kernel.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
        self._kernel.WriteFile.argtypes = [w.HANDLE, w.LPCVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]

    def request_enable(self, remove=False):
        """Called only after an explicit click, never during silent startup."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._starting or self._stopped.is_set():
                return False
            if not self.setup_executable.is_file():
                self.status = 'missing_component'
                return False
            if not remove and not pawnio_installed():
                self.status = 'missing_driver'
                return False
            self._starting = True
            self.status = 'starting'
        finally:
            self._lock.release()
        threading.Thread(target=self._launch, args=(remove,), daemon=True, name='TemperaturePermission').start()
        return True

    def _launch(self, remove=False):
        process = None
        status = 'error'
        try:
            info = ShellExecuteInfo()
            info.cbSize = ctypes.sizeof(info)
            info.fMask = 0x40 | 0x100  # Keep process handle; synchronous shell dispatch in this worker.
            info.lpVerb = 'runas'
            info.lpFile = str(self.setup_executable)
            info.lpParameters = f'{"remove" if remove else "install"} {self.sid}'
            info.lpDirectory = str(self.setup_executable.parent)
            info.nShow = 0
            shell = ctypes.WinDLL('shell32', use_last_error=True)
            shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
            shell.ShellExecuteExW.restype = w.BOOL
            if not shell.ShellExecuteExW(ctypes.byref(info)):
                status = 'cancelled' if ctypes.get_last_error() == 1223 else 'error'
                return
            process = info.hProcess
            while not self._stopped.is_set():
                if self._kernel.WaitForSingleObject(process, 200) == 0:
                    code = w.DWORD()
                    if self._kernel.GetExitCodeProcess(process, ctypes.byref(code)) and code.value == 0:
                        status = 'disabled' if remove else 'configured'
                    break
        except OSError:
            status = 'error'
        finally:
            if process:
                self._kernel.CloseHandle(process)
            with self._lock:
                self._disconnect()
                self.status = status
                self._starting = False

    def _verified_server(self, handle, expected_path):
        pid = w.ULONG()
        if not self._kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
            return False
        process = self._kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False
        try:
            size = w.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            return bool(self._kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size))) and \
                os.path.normcase(path.value) == os.path.normcase(str(expected_path))
        finally:
            self._kernel.CloseHandle(process)

    def _connect_persistent(self):
        if self._starting:
            return
        expected = installed_executable(self.install_root)
        if expected is None:
            return
        handle = self._kernel.CreateFileW(r'\\.\pipe\SkyLyricsSensors-Auto-' + self.sid,
            0xC0000000, 0, None, 3, 0x00110000, None)
        if handle != ctypes.c_void_p(-1).value:
            if self._verified_server(handle, expected):
                self._pipe = handle
                return
            self._kernel.CloseHandle(handle)
            self.status = 'error'
            return
        self.status = 'configured'
        now = time.monotonic()
        if now - self._last_kick >= 60:
            self._last_kick = now
            try:
                # Only runs an already-authorized, immutable task; never requests UAC here.
                subprocess.run(['schtasks.exe', '/Run', '/TN', 'SkyLyricsSensors-' + self.sid],
                    capture_output=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass

    def _disconnect(self):
        if self._pipe:
            self._kernel.CloseHandle(self._pipe)
            self._pipe = None

    def sample(self):
        with self._lock:
            if not self._pipe and not self._stopped.is_set():
                self._connect_persistent()
            if not self._pipe or self._stopped.is_set():
                return {'cpu_temp_status': self.status}
            try:
                written = w.DWORD()
                if not self._kernel.WriteFile(self._pipe, b'S', 1, ctypes.byref(written), None) or written.value != 1:
                    raise OSError('Sensor disconnected')
                deadline = time.monotonic() + 3
                raw = bytearray()
                while not self._stopped.is_set() and time.monotonic() < deadline:
                    available = w.DWORD()
                    if not self._kernel.PeekNamedPipe(self._pipe, None, 0, None, ctypes.byref(available), None):
                        raise OSError('Sensor disconnected')
                    if available.value:
                        if len(raw) + available.value > 1024:
                            raise ValueError('Sensor response too large')
                        buf = ctypes.create_string_buffer(available.value)
                        count = w.DWORD()
                        if not self._kernel.ReadFile(self._pipe, buf, available.value, ctypes.byref(count), None):
                            raise OSError('Sensor disconnected')
                        raw.extend(buf.raw[:count.value])
                        if b'\n' in raw:
                            result = parse_sample(raw)
                            self.status = result['cpu_temp_status']
                            self._disconnect()
                            return result
                    self._stopped.wait(.02)
                self.status = 'timeout'
            except (OSError, ValueError, TypeError):
                self.status = 'error'
            self._disconnect()
            return {'cpu_temp_status': self.status}

    def close(self):
        self._stopped.set()
        with self._lock:
            self._disconnect()
