import json
import math
import os
import threading
import time
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch, Mock

from cpu_temperature import CpuTemperature, parse_sample, installed_executable


class TemperatureTests(unittest.TestCase):
    def test_rejects_zero_nan_and_invalid_ranges(self):
        for value in (0, -1, 130, float('nan'), float('inf'), True, '65', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_sample(json.dumps({'status': 'ready', 'cpu_temp': value}))

    def test_missing_or_failed_sensor_cannot_publish_a_temperature(self):
        for status in ('permission', 'missing_driver', 'unavailable', 'error', 'timeout'):
            result = parse_sample(json.dumps({'status': status, 'cpu_temp': 60}))
            self.assertNotIn('cpu_temp', result)
            self.assertEqual(result['cpu_temp_status'], status)

    def test_valid_temperature_and_malformed_responses(self):
        self.assertEqual(parse_sample('{"status":"ready","cpu_temp":65.25}')['cpu_temp'], 65.2)
        for data in ('[]', 'null', '{}', '{bad', '{"status":"unknown"}'):
            with self.assertRaises(ValueError):
                parse_sample(data)

    def test_sampling_without_explicit_enable_never_launches_worker(self):
        sensor = CpuTemperature()
        with patch.object(sensor, '_launch') as launch, patch('cpu_temperature.installed_executable', return_value=None):
            sensor.sample()
            sensor.sample()
            launch.assert_not_called()
        sensor.close()

    def test_installation_marker_cannot_escape_protected_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ('../other', 'C:\\temp', 'a'*16+'/..', 'not-a-version'):
                (root/'current.txt').write_text(value,encoding='ascii')
                self.assertIsNone(installed_executable(root))
            version = root/('a'*16)
            version.mkdir()
            (version/'SkyLyricsSensors.exe').write_bytes(b'test')
            (root/'current.txt').write_text('a'*16,encoding='ascii')
            self.assertEqual(installed_executable(root), version/'SkyLyricsSensors.exe')

    def test_existing_configuration_reconnects_without_uac(self):
        sensor = CpuTemperature()
        sensor._kernel = Mock()
        sensor._kernel.CreateFileW.return_value = 123
        with patch('cpu_temperature.installed_executable',return_value=Path('C:/protected/worker.exe')), \
             patch.object(sensor,'_verified_server',return_value=True), \
             patch.object(sensor,'_launch') as launch:
            sensor._connect_persistent()
            self.assertEqual(sensor._pipe,123)
            launch.assert_not_called()
        sensor.close()

    def test_impostor_pipe_is_rejected(self):
        sensor = CpuTemperature()
        sensor._kernel = Mock()
        sensor._kernel.CreateFileW.return_value = 123
        with patch('cpu_temperature.installed_executable',return_value=Path('C:/protected/worker.exe')), \
             patch.object(sensor,'_verified_server',return_value=False):
            sensor._connect_persistent()
            self.assertIsNone(sensor._pipe)
            sensor._kernel.CloseHandle.assert_called_once_with(123)
        sensor.close()

    def test_unavailable_task_retries_are_rate_limited(self):
        import ctypes
        sensor = CpuTemperature()
        sensor._kernel = Mock()
        sensor._kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
        with patch('cpu_temperature.installed_executable',return_value=Path('C:/protected/worker.exe')), \
             patch('cpu_temperature.time.monotonic',side_effect=[100,105,161]), \
             patch('cpu_temperature.subprocess.run') as run, \
             patch.object(sensor,'_launch') as launch:
            for _ in range(3): sensor._connect_persistent()
            self.assertEqual(run.call_count,2)
            launch.assert_not_called()
        sensor.close()

    def test_permission_button_does_not_wait_for_sampling_lock(self):
        sensor = CpuTemperature()
        sensor._lock.acquire()
        try:
            start = time.monotonic()
            self.assertFalse(sensor.request_enable())
            self.assertLess(time.monotonic() - start, .1)
        finally:
            sensor._lock.release()
            sensor.close()

    def test_missing_driver_does_not_request_uac(self):
        sensor = CpuTemperature()
        with patch('cpu_temperature.pawnio_installed', return_value=False), \
             patch('pathlib.Path.is_file', return_value=True), \
             patch.object(sensor, '_launch') as launch:
            self.assertFalse(sensor.request_enable())
            self.assertEqual(sensor.status, 'missing_driver')
            launch.assert_not_called()
        sensor.close()

    def test_broken_worker_does_not_raise_or_keep_stale_temperature(self):
        sensor = CpuTemperature()
        sensor._pipe = 123
        sensor._kernel = Mock()
        sensor._kernel.WriteFile.return_value = False
        self.assertEqual(sensor.sample(), {'cpu_temp_status': 'error'})
        sensor._kernel.CloseHandle.assert_called_once_with(123)
        self.assertIsNone(sensor._pipe)
        sensor.close()

    def test_unresponsive_worker_times_out_and_disconnects(self):
        sensor = CpuTemperature()
        sensor._pipe = 123
        sensor._kernel = Mock()
        def write(pipe, data, size, written, overlapped):
            written._obj.value = 1
            return True
        sensor._kernel.WriteFile.side_effect = write
        with patch('cpu_temperature.time.monotonic', side_effect=[10, 14]):
            self.assertEqual(sensor.sample(), {'cpu_temp_status':'timeout'})
        sensor._kernel.CloseHandle.assert_called_once_with(123)
        sensor.close()

    def test_oversized_response_is_rejected_before_reading(self):
        sensor = CpuTemperature()
        sensor._pipe = 123
        sensor._kernel = Mock()
        def write(pipe, data, size, written, overlapped):
            written._obj.value = 1
            return True
        def peek(pipe, buffer, size, read, available, left):
            available._obj.value = 4096
            return True
        sensor._kernel.WriteFile.side_effect = write
        sensor._kernel.PeekNamedPipe.side_effect = peek
        self.assertEqual(sensor.sample(), {'cpu_temp_status':'error'})
        sensor._kernel.ReadFile.assert_not_called()
        sensor._kernel.CloseHandle.assert_called_once_with(123)
        sensor.close()


@unittest.skipUnless(os.environ.get('SKYLYRICS_TEST_LIVE_SENSOR') == '1',
                     'Requires a configured CPU sensor task and supported hardware')
class LiveTemperatureTests(unittest.TestCase):
    def test_persistent_worker_survives_requests_and_client_restart(self):
        # Exercises real asynchronous pipe completion and normal-permission reconnects.
        for _ in range(2):
            sensor = CpuTemperature()
            try:
                with patch.object(sensor, '_launch', side_effect=AssertionError('Unexpected UAC')):
                    for _ in range(3):
                        result = sensor.sample()
                        self.assertEqual(result['cpu_temp_status'], 'ready', result)
                        self.assertGreater(result['cpu_temp'], 0)
                        self.assertLess(result['cpu_temp'], 130)
                        time.sleep(.25)
            finally:
                sensor.close()


if __name__ == '__main__':
    unittest.main()
