import json
import unittest
import threading
from types import SimpleNamespace as NS
from unittest.mock import patch
from system_stats import SystemStats


class StatsTests(unittest.TestCase):
    def collect(self, nvidia, responses):
        sampler = SystemStats()
        sampler.nvidia = nvidia
        sampler.set_active('test', True)
        sampler._wake.wait = lambda _: sampler.stop_event.set()
        with patch.object(sampler, 'run_command', side_effect=responses) as run:
            sampler._run()
        return sampler.snapshot(), run

    def test_hidden_unused_sampler_does_not_query_hardware(self):
        sampler = SystemStats()
        queried = threading.Event()
        def query(*args, **kwargs):
            queried.set()
            return NS(returncode=0, stdout='{}')
        sampler.nvidia = None
        with patch.object(sampler, 'run_command', side_effect=query):
            sampler.start()
            self.assertFalse(queried.wait(.15))
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


if __name__ == '__main__':
    unittest.main()
