"""Signal helpers for Find My Buds (no GUI or Bluetooth imports)."""

from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

__version__ = "1.2.0"

UNKNOWN_NAME = "Unknown device"

# Each device's signal is the median of the readings from this many seconds.
SMOOTHING_WINDOW_S = 5.0
# A device not heard for this long is dropped (and the target is "lost").
STALE_AFTER_S = 12.0
# The trend compares now with the signal from up to this many seconds ago...
TREND_LOOKBACK_S = 6.0
# ...but only once at least this much history exists.
TREND_MIN_SPAN_S = 3.0

_MAX_SAMPLES_PER_DEVICE = 256

# Match quality, best first. Lower numbers win in ``find_target``.
MATCH_ADDRESS = 0
MATCH_EXACT_NAME = 1
MATCH_PARTIAL_NAME = 2


@dataclass(frozen=True)
class DeviceReading:
    """A device's smoothed signal.

    ``name`` is empty when the device never advertised one; use
    ``display_name`` for anything shown to the user. ``samples`` is how many
    raw advertisements the smoothed ``rssi`` was computed from.
    """

    name: str
    address: str
    rssi: int
    samples: int = 1

    @property
    def display_name(self) -> str:
        return self.name or UNKNOWN_NAME

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
    """Compare two signals while ignoring normal small RSSI fluctuations."""
    if previous_rssi is None:
        return "Collecting signal — walk around to get warmer/colder guidance."

    change = current_rssi - previous_rssi
    if change >= 5:
        return "Getting warmer — the signal is stronger."
    if change <= -5:
        return "Getting colder — the signal is weaker."
    return "About the same distance."


@dataclass
class _Entry:
    name: str
    last_seen: float
    samples: deque[tuple[float, int]]


class DeviceBook:
    """Thread-safe record of every device heard by a continuous scan.

    The scanner thread calls ``record`` for each advertisement; the GUI calls
    ``snapshot`` to get one smoothed reading per device. ``clock`` is
    injectable so the time-based behaviour can be tested.
    """

    def __init__(
        self,
        window_s: float = SMOOTHING_WINDOW_S,
        stale_s: float = STALE_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_s = window_s
        self._stale_s = stale_s
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def record(self, name: str, address: str, rssi: int) -> None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(address)
            if entry is None:
                entry = _Entry(name, now, deque(maxlen=_MAX_SAMPLES_PER_DEVICE))
                self._entries[address] = entry
            elif name:
                entry.name = name
            entry.last_seen = now
            entry.samples.append((now, rssi))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def snapshot(self) -> list[DeviceReading]:
        """Return smoothed readings, strongest first, dropping stale devices."""
        now = self._clock()
        readings: list[DeviceReading] = []
        with self._lock:
            for address in [
                a for a, e in self._entries.items() if now - e.last_seen > self._stale_s
            ]:
                del self._entries[address]

            for address, entry in self._entries.items():
                recent = [r for t, r in entry.samples if now - t <= self._window_s]
                if not recent:  # quiet device: fall back to its last reading
                    recent = [entry.samples[-1][1]]
                readings.append(
                    DeviceReading(
                        entry.name,
                        address,
                        round(statistics.median(recent)),
                        len(recent),
                    )
                )
        return sorted(readings, key=lambda reading: reading.rssi, reverse=True)


class TrendTracker:
    """Warmer/colder guidance from a stream of smoothed signal values.

    Each update is compared with the oldest value still inside the lookback
    window, so the message reflects movement over the last few seconds rather
    than one noisy reading against another.
    """

    def __init__(
        self,
        lookback_s: float = TREND_LOOKBACK_S,
        min_span_s: float = TREND_MIN_SPAN_S,
    ) -> None:
        self._lookback_s = lookback_s
        self._min_span_s = min_span_s
        self._samples: deque[tuple[float, int]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def update(self, rssi: int, now: float) -> str:
        while self._samples and now - self._samples[0][0] > self._lookback_s:
            self._samples.popleft()

        baseline: int | None = None
        if self._samples and now - self._samples[0][0] >= self._min_span_s:
            baseline = self._samples[0][1]

        self._samples.append((now, rssi))
        return describe_trend(baseline, rssi)


def match_rank(
    reading: DeviceReading,
    target_name: str = "",
    target_address: str = "",
) -> int | None:
    """Rank how well ``reading`` matches the saved target (lower is better).

    A saved address is authoritative, with the full saved name as a fallback
    because many earbuds rotate their BLE address. Partial names only match
    when no address is saved, so a target named "Pods" never silently latches
    onto a neighbour's "AirPods" after the real address was chosen.
    """
    wanted_address = target_address.strip().casefold()
    wanted_name = target_name.strip().casefold()
    reading_name = reading.name.strip().casefold()

    if wanted_address:
        if reading.address.strip().casefold() == wanted_address:
            return MATCH_ADDRESS
        if wanted_name and reading_name == wanted_name:
            return MATCH_EXACT_NAME
        return None

    if wanted_name:
        if reading_name == wanted_name:
            return MATCH_EXACT_NAME
        if wanted_name in reading_name:
            return MATCH_PARTIAL_NAME
    return None


def reading_matches(
    reading: DeviceReading,
    target_name: str = "",
    target_address: str = "",
) -> bool:
    """Return True when ``reading`` matches the saved target at all."""
    return match_rank(reading, target_name, target_address) is not None


def find_target(
    readings: list[DeviceReading],
    target_name: str = "",
    target_address: str = "",
) -> DeviceReading | None:
    """Return the best-matching reading (strongest signal on ties), or None."""
    best: DeviceReading | None = None
    best_key: tuple[int, int] | None = None
    for reading in readings:
        rank = match_rank(reading, target_name, target_address)
        if rank is None:
            continue
        key = (rank, -reading.rssi)
        if best_key is None or key < best_key:
            best, best_key = reading, key
    return best


def describe_scan_error(error: BaseException) -> str:
    """Turn a scanner exception into an actionable message."""
    text = str(error).strip()
    lowered = text.lower()

    if "turned off" in lowered or "powered off" in lowered:
        return "Bluetooth is turned off. Turn it on in Windows settings and retry."
    if "no bluetooth adapter" in lowered or "no adapter" in lowered:
        return "No Bluetooth adapter was found on this PC."
    if "access is denied" in lowered or "permission" in lowered:
        return (
            "Windows denied Bluetooth access. Check the Bluetooth privacy "
            "settings and close other apps that use the adapter."
        )
    return text or error.__class__.__name__
