"""Bounded background hardware sampling, independent of the lyric loop."""
import csv
import io
import json
import os
import shutil
import subprocess
import threading
import time

import psutil
from cpu_temperature import CpuTemperature
from native_stats import CpuFrequency

SENSOR_NAMESPACES = ('root\\LibreHardwareMonitor', 'root\\OpenHardwareMonitor')
SENSOR_REDISCOVERY_SECONDS = 300

SENSOR_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$result = @{cpu_ghz=$null; cpu_temp=$null; gpu=$null; gpu_temp=$null; _sensor_namespaces=@()}
if ($env:K1001_CPU_FREQUENCY -eq '1') { try {
    $cpu = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter "Name='_Total'"
    if ($cpu.ProcessorFrequency -gt 0 -and $cpu.PercentProcessorPerformance -gt 0) {
        $result.cpu_ghz = [math]::Round($cpu.ProcessorFrequency * $cpu.PercentProcessorPerformance / 100000, 2)
    }
} catch {} }
$namespaces = @($env:K1001_SENSOR_NAMESPACES -split ';' | Where-Object { $_ -in @('root\LibreHardwareMonitor', 'root\OpenHardwareMonitor') })
foreach ($namespace in $namespaces) {
    try {
        $allTemps = @(Get-CimInstance -Namespace $namespace -ClassName Sensor -Filter "SensorType='Temperature'")
        $result._sensor_namespaces += $namespace
        $gpuTemps = @($allTemps | Where-Object { $_.Parent -match '/(atigpu|nvidiagpu|intelgpu)/' -and $_.Value -gt 0 -and $_.Value -lt 130 })
        if ($gpuTemps.Count) { $result.gpu_temp = [math]::Round(($gpuTemps | Measure-Object Value -Maximum).Maximum) }
        $sensors = @($allTemps | Where-Object { $_.Parent -match '/(intelcpu|amdcpu)/' -and $_.Value -gt 0 -and $_.Value -lt 130 })
        $preferred = @($sensors | Where-Object { $_.Name -match 'Package|Tctl|Tdie' })
        if ($preferred.Count) { $sensors = $preferred }
        if ($sensors.Count -and $null -eq $result.cpu_temp) { $result.cpu_temp = [math]::Round(($sensors | Measure-Object Value -Maximum).Maximum) }
    } catch {}
}
if ($env:K1001_GPU_FALLBACK -eq '1') {
    try {
        $engines = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine
        $loads = @($engines | Group-Object { $_.Name -replace '^pid_\d+_', '' } |
            ForEach-Object { ($_.Group | Measure-Object UtilizationPercentage -Sum).Sum })
        if ($loads.Count) { $result.gpu = [math]::Min(100, ($loads | Measure-Object -Maximum).Maximum) }
    } catch {}
}
$result | ConvertTo-Json -Compress
'''


class SystemStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._values = {}
        self._updated = 0
        self.stop_event = threading.Event()
        self.thread = None
        self.nvidia = shutil.which('nvidia-smi')
        self._consumers = set()
        self._wake = threading.Event()
        self.temperature = CpuTemperature()
        self.frequency = CpuFrequency()
        self._sensor_namespaces = ()
        self._sensor_discovery_at = 0

    def enable_cpu_temperature(self, remove=False):
        result = self.temperature.request_enable(remove=remove)
        self._sensor_discovery_at = 0
        self._wake.set()
        return result

    def set_active(self, consumer, enabled):
        with self._lock:
            before = bool(self._consumers)
            if enabled:
                self._consumers.add(consumer)
            else:
                self._consumers.discard(consumer)
            changed = before != bool(self._consumers)
        if changed:
            self._wake.set()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self._lock:
            if time.monotonic() - self._updated > 25:
                return {}
            return dict(self._values)

    def close(self):
        self.stop_event.set()
        self._wake.set()
        self.temperature.close()

    @staticmethod
    def run_command(args, **kwargs):
        return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=8, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)

    def _run(self):
        psutil.cpu_percent(None)
        try:
            while not self.stop_event.is_set():
                with self._lock:
                    active = bool(self._consumers)
                if not active:
                    # Avoid averaging the next frequency sample across a long
                    # hidden/lyrics-only interval, and release idle query handles.
                    self.frequency.close()
                    self._wake.wait()
                    self._wake.clear()
                    continue
                values = self._sample()
                if self.stop_event.is_set():
                    break
                with self._lock:
                    self._values = values
                    self._updated = time.monotonic()
                self._wake.wait(5)
                self._wake.clear()
        finally:
            # The native query belongs to this thread; never close during a read.
            self.frequency.close()

    def _sample(self):
        # Prefer the bounded, already-authorized CPU worker before considering
        # external WMI namespaces. No temperature readings are cached here.
        values = self.temperature.sample()
        if self.stop_event.is_set():
            return values
        ghz = self.frequency.sample()
        if ghz is not None:
            values['cpu_ghz'] = ghz
        try:
            if self.nvidia:
                result = self.run_command([self.nvidia, '--query-gpu=name,utilization.gpu,temperature.gpu',
                                           '--format=csv,noheader,nounits'])
                if result.returncode == 0:
                    gpus = [row for row in csv.reader(io.StringIO(result.stdout)) if len(row) >= 3]
                    def load(row):
                        try:
                            return float(row[1])
                        except ValueError:
                            return -1
                    gpu = max(gpus, key=load) if gpus else ['', 'N/A', 'N/A']
                    values['gpu_name'] = gpu[0].strip()
                    for key, text in zip(('gpu', 'gpu_temp'), gpu[1:3]):
                        try:
                            values[key] = round(float(text))
                        except (ValueError, OverflowError):
                            pass
        except (OSError, subprocess.SubprocessError, StopIteration):
            pass
        if self.stop_event.is_set():
            return values
        now = time.monotonic()
        needs_temperature = 'cpu_temp' not in values or 'gpu_temp' not in values
        discover = needs_temperature and now >= self._sensor_discovery_at
        namespaces = SENSOR_NAMESPACES if discover else self._sensor_namespaces if needs_temperature else ()
        needs_frequency = 'cpu_ghz' not in values
        needs_gpu = 'gpu' not in values
        if needs_frequency or needs_gpu or namespaces:
            try:
                env = dict(os.environ, K1001_GPU_FALLBACK='1' if needs_gpu else '0',
                           K1001_CPU_FREQUENCY='1' if needs_frequency else '0',
                           K1001_SENSOR_NAMESPACES=';'.join(namespaces))
                result = self.run_command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SENSOR_SCRIPT], env=env)
                if result.returncode == 0:
                    sensor = json.loads(result.stdout)
                    if not isinstance(sensor, dict):
                        raise ValueError('Invalid hardware sample')
                    providers = sensor.pop('_sensor_namespaces', None)
                    if namespaces and isinstance(providers, list):
                        self._sensor_namespaces = tuple(n for n in SENSOR_NAMESPACES if n in providers)
                        if discover:
                            self._sensor_discovery_at = now + SENSOR_REDISCOVERY_SECONDS
                    values.update({k: v for k, v in sensor.items() if v is not None and k not in values})
            except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
                pass
        if 'cpu_temp' in values and 'cpu_temp_source' not in values:
            values['cpu_temp_source'] = 'external'
            values['cpu_temp_status'] = 'ready'
        try:
            values['cpu'] = round(psutil.cpu_percent(None))
            values['memory'] = round(psutil.virtual_memory().percent)
        except OSError:
            pass
        return values
