import asyncio
import unittest

from finder_core import (
    DeviceReading,
    describe_proximity,
    describe_trend,
    discover_devices,
    find_target,
    reading_matches,
    signal_percent,
)


class FinderCoreTests(unittest.TestCase):
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
        self.assertIn("again", describe_trend(None, -60))
        self.assertIn("same", describe_trend(-60, -57))
        self.assertIn("warmer", describe_trend(-60, -54))
        self.assertIn("colder", describe_trend(-60, -67))

    def test_matches_address_case_insensitively(self):
        reading = DeviceReading("Buds", "AA:BB:CC", -55)
        self.assertTrue(reading_matches(reading, target_address="aa:bb:cc"))

    def test_matches_name_as_case_insensitive_substring(self):
        reading = DeviceReading("Prabh's Galaxy Buds", "AA", -55)
        self.assertTrue(reading_matches(reading, target_name="galaxy buds"))
        self.assertFalse(reading_matches(reading, target_name="airpods"))

    def test_discovery_sorts_by_strongest_signal(self):
        class Device:
            def __init__(self, name, address):
                self.name = name
                self.address = address

        class Advertisement:
            def __init__(self, rssi, local_name=None):
                self.rssi = rssi
                self.local_name = local_name

        class FakeScanner:
            @classmethod
            async def discover(cls, timeout, return_adv):
                self.assertEqual(timeout, 0.1)
                self.assertTrue(return_adv)
                return {
                    "weak": (Device("Weak", "BB"), Advertisement(-82)),
                    "strong": (Device("Strong", "AA"), Advertisement(-44)),
                }

        readings = asyncio.run(discover_devices(FakeScanner, timeout=0.1))

        self.assertEqual([reading.name for reading in readings], ["Strong", "Weak"])
        self.assertEqual(readings[0].proximity, "Very close")


    def test_find_target_returns_match_by_address(self):
        readings = [
            DeviceReading("Other", "11:22:33", -70),
            DeviceReading("Buds", "AA:BB:CC", -55),
        ]
        result = find_target(readings, target_address="aa:bb:cc")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.name, "Buds")

    def test_find_target_returns_match_by_name(self):
        readings = [
            DeviceReading("Other Device", "11:22:33", -70),
            DeviceReading("Galaxy Buds Pro", "AA:BB:CC", -55),
        ]
        result = find_target(readings, target_name="galaxy buds")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.address, "AA:BB:CC")

    def test_find_target_returns_none_when_no_match(self):
        readings = [
            DeviceReading("Keyboard", "11:22:33", -70),
            DeviceReading("Mouse", "44:55:66", -65),
        ]
        self.assertIsNone(find_target(readings, target_name="galaxy buds"))

    def test_find_target_returns_none_for_empty_list(self):
        self.assertIsNone(find_target([], target_name="Buds", target_address="AA:BB"))


if __name__ == "__main__":
    unittest.main()
