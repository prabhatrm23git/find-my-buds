"""Persistent settings helpers for Find My Buds (no GUI dependencies)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".find_my_buds.json"

# Settings from versions that scanned in fixed windows; no longer used.
LEGACY_KEYS = (
    "scan_timeout_label",
    "rescan_interval_label",
    "scan_timeout_s",
    "rescan_interval_s",
    "auto_rescan",
)


def load_config(path: Path = CONFIG_PATH) -> tuple[dict[str, Any], str | None]:
    """Load settings, returning ``(config, warning)``.

    A missing file is normal. A file that cannot be parsed is moved aside to
    ``<name>.corrupt`` so the next save does not silently destroy it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, None
    except OSError as error:
        return {}, f"Could not read settings: {error}"

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        return data, None
    return {}, _set_aside(path)


def _set_aside(path: Path) -> str:
    backup = path.with_suffix(path.suffix + ".corrupt")
    try:
        path.replace(backup)
    except OSError:
        return "Settings file was unreadable and has been ignored."
    return f"Settings file was unreadable; a copy was kept as {backup.name}."


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def drop_legacy_keys(config: dict[str, Any]) -> None:
    for key in LEGACY_KEYS:
        config.pop(key, None)


def format_last_seen(value: object) -> str:
    """Render a stored ISO timestamp for display."""
    if not value:
        return "Never"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return "Unknown"
    return parsed.astimezone().strftime("%b %d, %H:%M")
