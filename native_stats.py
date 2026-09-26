"""Optional Windows CPU counters, sampled only by the hardware worker thread.

Uses the same ProcessorInformation counters as the WMI fallback, without
starting PowerShell. English-counter APIs also work on localized Windows.
https://learn.microsoft.com/windows/win32/perfctrs/collecting-performance-data
"""
import ctypes
from ctypes import wintypes as w
import math
import time


class CounterNumber(ctypes.Union):
    _fields_ = [('doubleValue', ctypes.c_double), ('largeValue', ctypes.c_longlong)]


class CounterValue(ctypes.Structure):
    _fields_ = [('CStatus', w.DWORD), ('value', CounterNumber)]


class CpuFrequency:
    """Owns its query on one worker thread; failures leave WMI available."""
    PATHS = (r'\Processor Information(_Total)\Processor Frequency',
             r'\Processor Information(_Total)\% Processor Performance')

    def __init__(self):
        self._api = None
        self._query = w.HANDLE()
        self._counters = []
        self._collected_at = None
        self._retry_at = 0

    def _open(self):
        api = ctypes.WinDLL('pdh.dll')
        api.PdhOpenQueryW.argtypes = [w.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(w.HANDLE)]
        api.PdhAddEnglishCounterW.argtypes = [w.HANDLE, w.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(w.HANDLE)]
        api.PdhCollectQueryData.argtypes = [w.HANDLE]
        api.PdhGetFormattedCounterValue.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(CounterValue)]
        api.PdhCloseQuery.argtypes = [w.HANDLE]
        self._api = api
        if api.PdhOpenQueryW(None, 0, ctypes.byref(self._query)):
            raise OSError('CPU counter query unavailable')
        for path in self.PATHS:
            counter = w.HANDLE()
            if api.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(counter)):
                raise OSError('CPU counter unavailable')
            self._counters.append(counter)

    def sample(self):
        now = time.monotonic()
        if now < self._retry_at:
            return None
        try:
            if not self._query:
                self._open()
            if self._collected_at is not None and now - self._collected_at < 1:
                return None
            if self._api.PdhCollectQueryData(self._query):
                raise OSError('CPU counter collection failed')
            first = self._collected_at is None
            self._collected_at = now
            if first:
                # Rate counters require two samples at least a second apart.
                # The existing WMI path supplies frequency during this warm-up.
                return None
            readings = []
            for counter in self._counters:
                value = CounterValue()
                # NOCAP100 matters for boost clocks above 100% performance.
                if self._api.PdhGetFormattedCounterValue(counter, 0x200 | 0x8000, None, ctypes.byref(value)):
                    raise OSError('Invalid CPU counter')
                if value.CStatus not in (0, 1) or not math.isfinite(value.value.doubleValue) or value.value.doubleValue <= 0:
                    raise ValueError('Invalid CPU counter value')
                readings.append(value.value.doubleValue)
            ghz = readings[0] * readings[1] / 100000
            if not 0 < ghz < 20:
                raise ValueError('Invalid CPU frequency')
            return round(ghz, 2)
        except (OSError, AttributeError, ValueError):
            self.close()
            self._retry_at = now + 60
            return None

    def close(self):
        if self._query and self._api:
            self._api.PdhCloseQuery(self._query)
        self._query = w.HANDLE()
        self._counters = []
        self._collected_at = None
