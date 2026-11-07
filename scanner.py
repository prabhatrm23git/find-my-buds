"""Continuous Bluetooth Low Energy scanning on a background thread."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from finder_core import describe_scan_error

try:
    from bleak import BleakScanner  # type: ignore[import-not-found]
except ImportError:  # start() reports a friendly installation message.
    BleakScanner = None  # type: ignore[assignment]

STOP_POLL_S = 0.1


class LiveScanner:
    """Listen for BLE advertisements until stopped.

    ``on_reading(name, address, rssi)`` is called from the scanner thread for
    every advertisement, so it must be thread-safe. ``on_error(message)`` is
    called once, from the scanner thread, if scanning fails; the scanner has
    stopped by then. ``scanner_factory`` accepts ``detection_callback=`` and
    returns an async context manager (``bleak.BleakScanner`` by default).
    """

    def __init__(
        self,
        on_reading: Callable[[str, str, int], None],
        on_error: Callable[[str], None],
        scanner_factory: Any = None,
    ) -> None:
        self._on_reading = on_reading
        self._on_error = on_error
        self._factory: Any = scanner_factory or BleakScanner
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._factory is None:
            raise RuntimeError(
                "Bluetooth support is not installed. Run: "
                "python -m pip install -r requirements.txt"
            )
        if self.running:
            if not self._stop_event.is_set():
                return
            self.stop()  # a previous run is still shutting down

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._thread_main, args=(self._stop_event,), daemon=True
        )
        self._thread.start()

    def stop(self, wait: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(wait)

    def _thread_main(self, stop_event: threading.Event) -> None:
        try:
            asyncio.run(self._run(stop_event))
        except Exception as error:  # noqa: BLE001 - reported to the caller.
            if not stop_event.is_set():
                self._on_error(describe_scan_error(error))

    async def _run(self, stop_event: threading.Event) -> None:
        async with self._factory(detection_callback=self._detected):
            while not stop_event.is_set():
                await asyncio.sleep(STOP_POLL_S)

    def _detected(self, device: Any, advertisement: Any) -> None:
        rssi = getattr(advertisement, "rssi", None)
        if rssi is None:
            return
        name = (
            getattr(advertisement, "local_name", None)
            or getattr(device, "name", None)
            or ""
        )
        address = str(getattr(device, "address", "") or "")
        if not address:
            return
        self._on_reading(str(name), address, int(rssi))
