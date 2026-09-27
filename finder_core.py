"""Bluetooth discovery and signal helpers for Find My Buds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from bleak import BleakScanner  # type: ignore[import-not-found]
except ImportError:  # The GUI reports a friendly installation message.
    BleakScanner = None  # type: ignore[assignment]


@dataclass(frozen=True)
class DeviceReading:
    """One Bluetooth Low Energy advertisement reading."""

    name: str
    address: str
    rssi: int

    @property
    def proximity(self) -> str:
        return describe_proximity(self.rssi)


def describe_proximity(rssi: int) -> str:
    """Turn an RSSI value into a deliberately broad proximity estimate."""
    if rssi >= -50:
        return "Very close"
    if rssi >= -65:
        return "Nearby"
    if rssi >= -80:
        return "Far away"
    return "Very weak signal"


def signal_percent(rssi: int) -> int:
    """Map the useful -100 to -30 dBm range onto a progress bar."""
    bounded = min(-30, max(-100, rssi))
    return round((bounded + 100) * 100 / 70)


def describe_trend(previous_rssi: int | None, current_rssi: int) -> str:
    """Compare two scans while ignoring normal small RSSI fluctuations."""
    if previous_rssi is None:
        return "Scan again while moving to get warmer/colder guidance."

    change = current_rssi - previous_rssi
    if change >= 5:
        return "Getting warmer — the signal is stronger."
    if change <= -5:
        return "Getting colder — the signal is weaker."
    return "About the same distance."


def reading_matches(
    reading: DeviceReading,
    target_name: str = "",
    target_address: str = "",
) -> bool:
    """Match a saved address, falling back to a case-insensitive name."""
    wanted_address = target_address.strip().casefold()
    wanted_name = target_name.strip().casefold()

    if wanted_address and reading.address.strip().casefold() == wanted_address:
        return True
    return bool(wanted_name and wanted_name in reading.name.casefold())


async def discover_devices(
    scanner_type: Any = None,
    timeout: float = 5.0,
) -> list[DeviceReading]:
    """Discover nearby BLE devices and retain their strongest reading."""
    scanner = scanner_type or BleakScanner
    if scanner is None:
        raise RuntimeError(
            "Bluetooth support is not installed. Run: "
            "python -m pip install -r requirements.txt"
        )

    discovered = await scanner.discover(timeout=timeout, return_adv=True)
    by_address: dict[str, DeviceReading] = {}

    for device, advertisement in discovered.values():
        rssi = getattr(advertisement, "rssi", None)
        if rssi is None:
            continue

        name = (
            getattr(advertisement, "local_name", None)
            or getattr(device, "name", None)
            or "Unknown device"
        )
        address = str(getattr(device, "address", "Unknown address"))
        reading = DeviceReading(name=str(name), address=address, rssi=int(rssi))

        current = by_address.get(address)
        if current is None or reading.rssi > current.rssi:
            by_address[address] = reading

    return sorted(by_address.values(), key=lambda reading: reading.rssi, reverse=True)
