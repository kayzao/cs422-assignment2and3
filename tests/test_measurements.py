import unittest

from netlab.measurements import CounterSnapshot, measure_interval


class MeasurementTests(unittest.TestCase):
    def test_uses_actual_time_and_acknowledged_bytes(self):
        # A2 Q1(c): 100,000 new acknowledged bytes in 0.25 s -> 3.2 Mbit/s.
        # The counters start above zero, which catches using totals as deltas.
        interval = measure_interval(
            CounterSnapshot(1.0, 1000, 2), CounterSnapshot(1.25, 101000, 5)
        )
        self.assertEqual(interval.goodput_bps, 3_200_000)
        self.assertEqual(interval.bytes_acked_delta, 100_000)
        self.assertEqual(interval.retrans_segments_delta, 3)

    def test_zero_goodput_is_a_valid_interval(self):
        # Stalled intervals belong in A2's plots/statistics; do not drop zeros.
        interval = measure_interval(CounterSnapshot(1, 100, 0), CounterSnapshot(2, 100, 0))
        self.assertEqual(interval.goodput_bps, 0)

    def test_counter_resets_and_invalid_timestamps_are_rejected(self):
        # Prevent plausible-looking results from reversed time or counter resets.
        previous = CounterSnapshot(1, 100, 2)
        for current in (
            CounterSnapshot(1, 200, 2), CounterSnapshot(0, 200, 2),
            CounterSnapshot(2, 99, 2), CounterSnapshot(2, 200, 1),
        ):
            with self.subTest(current=current), self.assertRaises(ValueError):
                measure_interval(previous, current)

    def test_nonfinite_time_and_negative_counters_are_rejected(self):
        for values in ((float("nan"), 0, 0), (float("inf"), 0, 0), (0, -1, 0), (0, 0, -1)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                CounterSnapshot(*values)


if __name__ == "__main__":
    unittest.main()
