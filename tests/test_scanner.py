import time
import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import scanner as scanner_module
from scanner import LiveScanner


class FakeBleakScanner:
    instances: ClassVar[list["FakeBleakScanner"]] = []

    def __init__(self, detection_callback):
        self.callback = detection_callback
        self.exited = False
        FakeBleakScanner.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.exited = True


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class LiveScannerTests(unittest.TestCase):
    def setUp(self):
        FakeBleakScanner.instances = []
        self.readings = []
        self.errors = []
        self.scanner = LiveScanner(
            lambda *reading: self.readings.append(reading),
            self.errors.append,
            FakeBleakScanner,
        )
        self.addCleanup(self.scanner.stop)

    def test_forwards_advertisements_until_stopped(self):
        self.scanner.start()
        self.assertTrue(wait_for(lambda: FakeBleakScanner.instances))
        fake = FakeBleakScanner.instances[0]

        fake.callback(
            SimpleNamespace(name="Dev", address="AA"),
            SimpleNamespace(rssi=-50, local_name="Buds"),
        )
        fake.callback(  # falls back to the device name
            SimpleNamespace(name="Dev", address="BB"),
            SimpleNamespace(rssi=-60, local_name=None),
        )
        fake.callback(  # no name at all
            SimpleNamespace(name=None, address="CC"),
            SimpleNamespace(rssi=-70, local_name=None),
        )
        fake.callback(  # ignored: no RSSI
            SimpleNamespace(name="X", address="DD"),
            SimpleNamespace(rssi=None, local_name=None),
        )
        self.assertEqual(
            self.readings,
            [("Buds", "AA", -50), ("Dev", "BB", -60), ("", "CC", -70)],
        )

        self.assertTrue(self.scanner.running)
        self.scanner.stop()
        self.assertFalse(self.scanner.running)
        self.assertTrue(fake.exited)
        self.assertEqual(self.errors, [])

    def test_can_be_restarted(self):
        self.scanner.start()
        self.assertTrue(wait_for(lambda: len(FakeBleakScanner.instances) == 1))
        self.scanner.stop()
        self.scanner.start()
        self.assertTrue(wait_for(lambda: len(FakeBleakScanner.instances) == 2))
        self.assertTrue(self.scanner.running)

    def test_start_twice_does_not_open_a_second_scanner(self):
        self.scanner.start()
        self.scanner.start()
        self.assertTrue(wait_for(lambda: FakeBleakScanner.instances))
        time.sleep(0.2)
        self.assertEqual(len(FakeBleakScanner.instances), 1)

    def test_startup_failure_is_reported_in_plain_language(self):
        def failing(detection_callback):
            raise OSError("Bluetooth is turned off")

        scanner = LiveScanner(lambda *_: None, self.errors.append, failing)
        scanner.start()
        self.assertTrue(wait_for(lambda: self.errors))
        self.assertIn("turned off", self.errors[0])
        self.assertTrue(wait_for(lambda: not scanner.running))

    def test_missing_bleak_raises_installation_hint(self):
        with mock.patch.object(scanner_module, "BleakScanner", None):
            scanner = LiveScanner(lambda *_: None, self.errors.append)
        with self.assertRaises(RuntimeError) as context:
            scanner.start()
        self.assertIn("requirements.txt", str(context.exception))


if __name__ == "__main__":
    unittest.main()
