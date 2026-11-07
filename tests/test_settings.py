import json
import tempfile
import unittest
from pathlib import Path

from settings import drop_legacy_keys, format_last_seen, load_config, save_config


class ConfigFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.json"

    def test_missing_file_is_empty_without_warning(self):
        self.assertEqual(load_config(self.path), ({}, None))

    def test_round_trip(self):
        save_config({"target_name": "Buds"}, self.path)
        self.assertEqual(load_config(self.path), ({"target_name": "Buds"}, None))

    def test_corrupt_file_is_kept_aside_with_warning(self):
        self.path.write_text("{not json", encoding="utf-8")
        config, warning = load_config(self.path)
        self.assertEqual(config, {})
        self.assertIn("config.json.corrupt", warning or "")
        self.assertFalse(self.path.exists())
        self.assertEqual(
            (self.path.parent / "config.json.corrupt").read_text(encoding="utf-8"),
            "{not json",
        )

    def test_non_object_json_is_treated_as_corrupt(self):
        self.path.write_text(json.dumps([1, 2]), encoding="utf-8")
        config, warning = load_config(self.path)
        self.assertEqual(config, {})
        self.assertIsNotNone(warning)


class LegacyKeyTests(unittest.TestCase):
    def test_drops_settings_from_window_based_scanning(self):
        config = {
            "target_name": "Buds",
            "scan_timeout_label": "5 s",
            "rescan_interval_s": 30,
            "auto_rescan": True,
        }
        drop_legacy_keys(config)
        self.assertEqual(config, {"target_name": "Buds"})


class LastSeenTests(unittest.TestCase):
    def test_formats_and_handles_bad_values(self):
        self.assertEqual(format_last_seen(None), "Never")
        self.assertEqual(format_last_seen("garbage"), "Unknown")
        self.assertRegex(
            format_last_seen("2026-01-02T03:04:05+00:00"), r"^[A-Z][a-z]{2} \d{2}, "
        )


if __name__ == "__main__":
    unittest.main()
