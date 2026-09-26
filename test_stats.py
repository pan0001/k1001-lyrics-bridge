import json
import unittest
import threading
from types import SimpleNamespace as NS
from unittest.mock import patch
from system_stats import SystemStats, SENSOR_NAMESPACES


class StatsTests(unittest.TestCase):
    def collect(self, nvidia, responses):
        sampler = SystemStats()
        sampler.nvidia = nvidia
        sampler.set_active('test', True)
        sampler._wake.wait = lambda _: sampler.stop_event.set()
        with patch.object(sampler, 'run_command', side_effect=responses) as run, \
             patch.object(sampler.frequency, 'sample', return_value=None), \
             patch.object(sampler.temperature, 'sample', return_value={'cpu_temp_status': 'unavailable'}):
            sampler._run()
        sampler.close()
        return sampler.snapshot(), run

    def test_hidden_unused_sampler_does_not_query_hardware(self):
        sampler = SystemStats()
        queried = threading.Event()
        def query(*args, **kwargs):
            queried.set()
            return NS(returncode=0, stdout='{}')
        sampler.nvidia = None
        with patch.object(sampler, 'run_command', side_effect=query), \
             patch.object(sampler.frequency, 'sample', return_value=None) as frequency, \
             patch.object(sampler.temperature, 'sample', return_value={'cpu_temp_status': 'unavailable'}):
            sampler.start()
            self.assertFalse(queried.wait(.15))
            frequency.assert_not_called()
            sampler.set_active('panel', True)
            self.assertTrue(queried.wait(2))
            sampler.close()
            sampler.thread.join(2)
            self.assertFalse(sampler.thread.is_alive())

    def test_without_nvidia_uses_windows_and_sensor_provider(self):
        data, run = self.collect(None, [NS(returncode=0, stdout=json.dumps(dict(cpu_ghz=4.2, cpu_temp=57, gpu=28, gpu_temp=45)))])
        self.assertEqual(data['gpu'], 28)
        self.assertEqual(data['cpu_temp'], 57)
        self.assertEqual(run.call_args.kwargs['env']['K1001_GPU_FALLBACK'], '1')

    def test_missing_sensor_provider_keeps_cpu_and_memory(self):
        data, _ = self.collect(None, [OSError('no sensors')])
        self.assertIn('cpu', data)
        self.assertIn('memory', data)
        self.assertNotIn('cpu_temp', data)
        self.assertNotIn('gpu', data)

    def test_multiple_nvidia_cards_select_highest_load(self):
        data, run = self.collect('nvidia-smi', [NS(returncode=0, stdout='Card A, 2, 30\nCard B, 60, 65\n'), NS(returncode=0, stdout='{}')])
        self.assertEqual(data['gpu_name'], 'Card B')
        self.assertEqual(data['gpu'], 60)
        self.assertEqual(data['gpu_temp'], 65)

    def test_working_builtin_sensors_do_not_launch_powershell(self):
        sampler = SystemStats()
        sampler.nvidia = 'nvidia-smi'
        with patch.object(sampler.frequency, 'sample', return_value=5.12), \
             patch.object(sampler.temperature, 'sample', return_value={'cpu_temp': 64, 'cpu_temp_source': 'builtin'}), \
             patch.object(sampler, 'run_command', return_value=NS(returncode=0, stdout='Card A, 20, 40')) as run:
            values = sampler._sample()
        sampler.close()
        self.assertEqual(values['cpu_ghz'], 5.12)
        self.assertEqual(values['cpu_temp'], 64)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], 'nvidia-smi')

    def test_missing_external_providers_are_retried_later_without_stale_temperature(self):
        sampler = SystemStats()
        sampler.nvidia = 'nvidia-smi'
        gpu = NS(returncode=0, stdout='Card A, 20, 40')
        missing = NS(returncode=0, stdout='{"_sensor_namespaces": []}')
        found = NS(returncode=0, stdout=json.dumps({'_sensor_namespaces': [SENSOR_NAMESPACES[0]], 'cpu_temp': 61}))
        with patch.object(sampler.frequency, 'sample', return_value=4.5), \
             patch.object(sampler.temperature, 'sample', side_effect=lambda: {'cpu_temp_status': 'unavailable'}), \
             patch.object(sampler, 'run_command', side_effect=[gpu, missing, gpu, gpu, found, gpu, missing]) as run, \
             patch('system_stats.time.monotonic', side_effect=[100, 105, 401, 406]):
            first = sampler._sample()
            second = sampler._sample()
            recovered = sampler._sample()
            lost = sampler._sample()
        sampler.close()
        self.assertNotIn('cpu_temp', first)
        self.assertNotIn('cpu_temp', second)
        self.assertEqual(recovered['cpu_temp'], 61)
        self.assertEqual(recovered['cpu_temp_source'], 'external')
        self.assertNotIn('cpu_temp', lost)
        # Probe once, skip unavailable providers, rediscover, then query only the found provider.
        commands = [c for c in run.call_args_list if c.args[0][0] == 'powershell.exe']
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[-1].kwargs['env']['K1001_SENSOR_NAMESPACES'], SENSOR_NAMESPACES[0])
        self.assertEqual(commands[-1].kwargs['env']['K1001_CPU_FREQUENCY'], '0')

    def test_frequency_failure_keeps_windows_fallback_but_skips_unneeded_namespaces(self):
        sampler = SystemStats()
        sampler.nvidia = 'nvidia-smi'
        with patch.object(sampler.frequency, 'sample', return_value=None), \
             patch.object(sampler.temperature, 'sample', return_value={'cpu_temp': 64, 'cpu_temp_source': 'builtin'}), \
             patch.object(sampler, 'run_command', side_effect=[NS(returncode=0, stdout='Card A, 20, 40'),
                 NS(returncode=0, stdout='{"cpu_ghz":4.6, "cpu_temp":12, "_sensor_namespaces":[] }')]) as run:
            values = sampler._sample()
        sampler.close()
        self.assertEqual(values['cpu_ghz'], 4.6)
        self.assertEqual(values['cpu_temp'], 64)
        self.assertEqual(run.call_args.kwargs['env']['K1001_SENSOR_NAMESPACES'], '')
        self.assertNotIn('_sensor_namespaces', values)


if __name__ == '__main__':
    unittest.main()
