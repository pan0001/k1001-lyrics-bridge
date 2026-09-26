import ctypes
import unittest
from unittest.mock import Mock, patch

from native_stats import CpuFrequency, CounterValue


class NativeStatsTests(unittest.TestCase):
    def counter(self, readings=(4300, 125), status=0):
        sampler = CpuFrequency()
        sampler._api = Mock()
        sampler._query = ctypes.c_void_p(12)
        sampler._counters = [ctypes.c_void_p(13), ctypes.c_void_p(14)]
        sampler._api.PdhCollectQueryData.return_value = 0
        data = iter(readings)
        def formatted(handle, flags, type_ptr, output):
            self.assertTrue(flags & 0x8000, 'Boost percentage must not be capped at 100')
            value = ctypes.cast(output, ctypes.POINTER(CounterValue)).contents
            value.CStatus = status
            value.value.doubleValue = next(data)
            return 0
        sampler._api.PdhGetFormattedCounterValue.side_effect = formatted
        return sampler

    def test_waits_for_two_samples_and_preserves_boost_frequency(self):
        sampler = self.counter()
        with patch('native_stats.time.monotonic', side_effect=[100, 100.5, 105]):
            self.assertIsNone(sampler.sample())
            self.assertIsNone(sampler.sample())
            self.assertEqual(sampler.sample(), 5.38)
        self.assertEqual(sampler._api.PdhCollectQueryData.call_count, 2)
        sampler.close()
        sampler._api.PdhCloseQuery.assert_called_once()

    def test_invalid_counter_status_or_nonfinite_values_fall_back(self):
        for readings, status in [((4300, 125), 0xC0000BC6), ((float('nan'), 100), 0), ((4300, 0), 0)]:
            with self.subTest(readings=readings, status=status):
                sampler = self.counter(readings, status)
                with patch('native_stats.time.monotonic', side_effect=[100, 105, 110]), \
                     patch.object(sampler, '_open') as reopen:
                    self.assertIsNone(sampler.sample())
                    self.assertIsNone(sampler.sample())
                    self.assertIsNone(sampler.sample())
                    reopen.assert_not_called()
                sampler._api.PdhCloseQuery.assert_called_once()
                self.assertFalse(sampler._query)

    def test_unavailable_api_retries_after_cooldown(self):
        sampler = CpuFrequency()
        with patch('native_stats.time.monotonic', side_effect=[100, 105, 161]), \
             patch.object(sampler, '_open', side_effect=OSError('counter disabled')) as open_query:
            for _ in range(3):
                self.assertIsNone(sampler.sample())
        self.assertEqual(open_query.call_count, 2)


if __name__ == '__main__':
    unittest.main()
