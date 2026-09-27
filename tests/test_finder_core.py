import asyncio
import unittest

from finder_core import (
    DeviceReading,
    describe_proximity,
    describe_trend,
    discover_devices,
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


if __name__ == "__main__":
    unittest.main()
