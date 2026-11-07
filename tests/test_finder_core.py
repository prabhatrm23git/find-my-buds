import unittest

from finder_core import (
    DeviceBook,
    DeviceReading,
    TrendTracker,
    describe_proximity,
    describe_scan_error,
    describe_trend,
    find_target,
    reading_matches,
    signal_percent,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class SignalHelperTests(unittest.TestCase):
    def test_describes_proximity_boundaries(self):
        self.assertEqual(describe_proximity(-50), "Very close")
        self.assertEqual(describe_proximity(-51), "Nearby")
        self.assertEqual(describe_proximity(-66), "Far away")
        self.assertEqual(describe_proximity(-81), "Very weak signal")

    def test_signal_percent_is_bounded(self):
        self.assertEqual(signal_percent(-120), 0)
        self.assertEqual(signal_percent(-65), 50)
        self.assertEqual(signal_percent(-20), 100)

    def test_trend_ignores_small_signal_changes(self):
        self.assertIn("Collecting", describe_trend(None, -60))
        self.assertIn("same", describe_trend(-60, -57))
        self.assertIn("warmer", describe_trend(-60, -54))
        self.assertIn("colder", describe_trend(-60, -67))

    def test_scan_error_messages_are_actionable(self):
        self.assertIn(
            "turned off", describe_scan_error(OSError("Bluetooth is turned off"))
        )
        self.assertIn(
            "denied", describe_scan_error(PermissionError("Access is denied"))
        )
        self.assertEqual(describe_scan_error(RuntimeError("boom")), "boom")
        self.assertEqual(describe_scan_error(RuntimeError()), "RuntimeError")


class MatchingTests(unittest.TestCase):
    def test_matches_address_case_insensitively(self):
        reading = DeviceReading("Buds", "AA:BB:CC", -55)
        self.assertTrue(reading_matches(reading, target_address="aa:bb:cc"))

    def test_matches_name_as_case_insensitive_substring(self):
        reading = DeviceReading("Prabh's Galaxy Buds", "AA", -55)
        self.assertTrue(reading_matches(reading, target_name="galaxy buds"))
        self.assertFalse(reading_matches(reading, target_name="airpods"))

    def test_blank_target_matches_nothing(self):
        self.assertFalse(reading_matches(DeviceReading("Buds", "AA", -50)))

    def test_saved_address_ignores_partial_name_matches(self):
        neighbour = DeviceReading("AirPods Pro", "99:99", -40)
        self.assertFalse(
            reading_matches(neighbour, target_name="Pods", target_address="AA:BB")
        )

    def test_saved_address_falls_back_to_exact_name_for_rotated_address(self):
        rotated = DeviceReading("Buds", "NEW:ADDR", -60)
        self.assertTrue(
            reading_matches(rotated, target_name="buds", target_address="OLD:ADDR")
        )

    def test_find_target_returns_match_by_address(self):
        readings = [
            DeviceReading("Other", "11:22:33", -70),
            DeviceReading("Buds", "AA:BB:CC", -55),
        ]
        result = find_target(readings, target_address="aa:bb:cc")
        assert result is not None
        self.assertEqual(result.name, "Buds")

    def test_find_target_returns_none_when_no_match(self):
        readings = [DeviceReading("Keyboard", "11", -70)]
        self.assertIsNone(find_target(readings, target_name="galaxy buds"))
        self.assertIsNone(find_target([], target_name="Buds", target_address="AA"))

    def test_find_target_prefers_address_over_stronger_name_match(self):
        readings = [
            DeviceReading("Buds", "11", -40),
            DeviceReading("Buds", "AA", -70),
        ]
        result = find_target(readings, target_name="Buds", target_address="AA")
        assert result is not None
        self.assertEqual(result.address, "AA")

    def test_find_target_prefers_exact_name_then_strongest(self):
        readings = [
            DeviceReading("Buds Case", "11", -40),
            DeviceReading("Buds", "22", -80),
            DeviceReading("Buds", "33", -60),
        ]
        result = find_target(readings, target_name="buds")
        assert result is not None
        self.assertEqual(result.address, "33")


class DeviceBookTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.book = DeviceBook(window_s=5.0, stale_s=12.0, clock=self.clock)

    def test_smooths_with_median_so_outliers_are_ignored(self):
        for rssi in (-60, -61, -90):
            self.book.record("Buds", "AA", rssi)
            self.clock.now += 1
        (reading,) = self.book.snapshot()
        self.assertEqual(reading.rssi, -61)
        self.assertEqual(reading.samples, 3)

    def test_old_readings_leave_the_smoothing_window(self):
        self.book.record("Buds", "AA", -40)
        self.clock.now = 6
        self.book.record("Buds", "AA", -80)
        (reading,) = self.book.snapshot()
        self.assertEqual((reading.rssi, reading.samples), (-80, 1))

    def test_quiet_device_keeps_last_reading_until_stale(self):
        self.book.record("Buds", "AA", -50)
        self.clock.now = 8  # outside the window, not yet stale
        (reading,) = self.book.snapshot()
        self.assertEqual(reading.rssi, -50)
        self.clock.now = 13
        self.assertEqual(self.book.snapshot(), [])

    def test_unnamed_advertisements_keep_the_known_name(self):
        self.book.record("Buds", "AA", -50)
        self.book.record("", "AA", -52)
        (reading,) = self.book.snapshot()
        self.assertEqual(reading.name, "Buds")

    def test_device_never_named_has_empty_name_and_display_fallback(self):
        self.book.record("", "AA", -50)
        (reading,) = self.book.snapshot()
        self.assertEqual(reading.name, "")
        self.assertEqual(reading.display_name, "Unknown device")
        self.assertFalse(reading_matches(reading, target_name="Unknown device"))

    def test_snapshot_is_sorted_strongest_first(self):
        self.book.record("Weak", "BB", -82)
        self.book.record("Strong", "AA", -44)
        names = [reading.name for reading in self.book.snapshot()]
        self.assertEqual(names, ["Strong", "Weak"])
        self.assertEqual(self.book.snapshot()[0].proximity, "Very close")

    def test_clear_forgets_everything(self):
        self.book.record("Buds", "AA", -50)
        self.book.clear()
        self.assertEqual(self.book.snapshot(), [])


class TrendTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = TrendTracker(lookback_s=6.0, min_span_s=3.0)

    def test_needs_some_history_before_giving_guidance(self):
        self.assertIn("Collecting", self.tracker.update(-70, 0))
        self.assertIn("Collecting", self.tracker.update(-60, 1))

    def test_reports_warmer_and_colder_over_the_lookback(self):
        self.tracker.update(-70, 0)
        self.assertIn("warmer", self.tracker.update(-60, 4))

        other = TrendTracker(lookback_s=6.0, min_span_s=3.0)
        other.update(-60, 0)
        self.assertIn("colder", other.update(-70, 4))

    def test_small_changes_are_the_same_distance(self):
        self.tracker.update(-60, 0)
        self.assertIn("same", self.tracker.update(-62, 4))

    def test_baseline_slides_forward_with_the_window(self):
        self.tracker.update(-80, 0)
        self.tracker.update(-60, 4)
        # t=0 has left the 6 s window, so the baseline is now t=4 (-60).
        self.assertIn("same", self.tracker.update(-60, 7))

    def test_reset_drops_history(self):
        self.tracker.update(-80, 0)
        self.tracker.reset()
        self.assertIn("Collecting", self.tracker.update(-50, 4))


if __name__ == "__main__":
    unittest.main()
