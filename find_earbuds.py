"""Find My Buds desktop application."""

from __future__ import annotations

import queue
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any

from finder_core import (
    SMOOTHING_WINDOW_S,
    DeviceBook,
    DeviceReading,
    TrendTracker,
    __version__,
    find_target,
    signal_percent,
)
from scanner import LiveScanner
from settings import (
    drop_legacy_keys,
    format_last_seen,
    load_config,
    save_config,
)

APP_TITLE = "Find My Buds"
TICK_MS = 500
# The list is re-sorted this often so rows don't jump under the mouse.
SORT_INTERVAL_S = 3.0
LAST_SEEN_SAVE_INTERVAL_S = 10.0


class FindMyBudsApp:
    def __init__(self, root: tk.Tk, scanner_factory: Any = None) -> None:
        self.root = root
        self.root.title(f"{APP_TITLE} {__version__}")
        self.root.geometry("820x640")
        self.root.minsize(720, 540)

        self.config, config_warning = load_config()
        drop_legacy_keys(self.config)
        self.target_address = str(self.config.get("target_address", ""))
        self.saved_target_name = str(self.config.get("target_name", ""))

        self.book = DeviceBook()
        self.trend = TrendTracker()
        self.errors: queue.Queue[str] = queue.Queue()
        self.scanner = LiveScanner(
            on_reading=self.book.record,
            on_error=self.errors.put,
            scanner_factory=scanner_factory,
        )
        self.scanning = False
        self._closing = False
        self._tick_after_id: str | None = None
        self._tree_items: dict[str, str] = {}
        self.devices_by_item: dict[str, DeviceReading] = {}
        self._last_sort = float("-inf")
        self._last_seen_saved = float("-inf")

        self.target_name = tk.StringVar(value=self.saved_target_name)
        self.status_text = tk.StringVar(
            value=config_warning or "Press Start scanning to listen for nearby devices."
        )
        self.found_name = tk.StringVar(value="No earbud selected")
        self.signal_text = tk.StringVar(value="Signal: —")
        self.proximity_text = tk.StringVar(value="Proximity: —")
        self.trend_text = tk.StringVar(
            value="Start scanning, then pick your earbuds from the list."
        )
        self.history_text = tk.StringVar(value="")
        self.last_seen_text = tk.StringVar(
            value=f"Last seen: {format_last_seen(self.config.get('last_seen'))}"
        )

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick_after_id = self.root.after(TICK_MS, self._tick)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Result.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("History.TLabel", foreground="#888888")

        main = ttk.Frame(self.root, padding=20)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        ttk.Label(main, text=APP_TITLE, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            main,
            text="Use live Bluetooth signal strength to search for nearby earbuds.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 16))

        # ── earbuds target ────────────────────────────────────────────────────
        target_frame = ttk.LabelFrame(main, text="Your earbuds", padding=12)
        target_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        target_frame.columnconfigure(1, weight=1)

        ttk.Label(target_frame, text="Name:").grid(row=0, column=0, padx=(0, 8))
        target_entry = ttk.Entry(target_frame, textvariable=self.target_name)
        target_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        target_entry.bind("<Return>", lambda _event: self._on_enter())

        self.scan_button = ttk.Button(
            target_frame, text="Start scanning", command=self.start_scanning
        )
        self.scan_button.grid(row=0, column=2, padx=(0, 8))

        self.use_button = ttk.Button(
            target_frame,
            text="Use selected device",
            command=self.use_selected_device,
        )
        self.use_button.grid(row=0, column=3)

        # ── finder panel ──────────────────────────────────────────────────────
        result_frame = ttk.LabelFrame(main, text="Finder", padding=14)
        result_frame.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        result_frame.columnconfigure(0, weight=1)

        ttk.Label(
            result_frame, textvariable=self.found_name, style="Result.TLabel"
        ).grid(row=0, column=0, sticky="w")
        self.signal_bar = ttk.Progressbar(
            result_frame, maximum=100, mode="determinate"
        )
        self.signal_bar.grid(row=1, column=0, sticky="ew", pady=(10, 6))

        details = ttk.Frame(result_frame)
        details.grid(row=2, column=0, sticky="ew")
        details.columnconfigure(0, weight=1)
        details.columnconfigure(1, weight=1)
        ttk.Label(details, textvariable=self.signal_text).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(details, textvariable=self.proximity_text).grid(
            row=0, column=1, sticky="e"
        )

        ttk.Label(
            result_frame, textvariable=self.history_text, style="History.TLabel"
        ).grid(row=3, column=0, sticky="w", pady=(2, 0))
        ttk.Label(result_frame, textvariable=self.trend_text).grid(
            row=4, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Label(result_frame, textvariable=self.last_seen_text).grid(
            row=5, column=0, sticky="w", pady=(4, 0)
        )

        # ── device list ───────────────────────────────────────────────────────
        devices_frame = ttk.LabelFrame(main, text="Nearby BLE devices", padding=8)
        devices_frame.grid(row=4, column=0, sticky="nsew")
        devices_frame.rowconfigure(0, weight=1)
        devices_frame.columnconfigure(0, weight=1)

        columns = ("name", "address", "rssi", "proximity")
        self.devices_tree = ttk.Treeview(
            devices_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.devices_tree.heading("name", text="Device")
        self.devices_tree.heading("address", text="Address")
        self.devices_tree.heading("rssi", text="Signal")
        self.devices_tree.heading("proximity", text="Estimate")
        self.devices_tree.column("name", width=220, minwidth=130)
        self.devices_tree.column("address", width=230, minwidth=150)
        self.devices_tree.column("rssi", width=85, minwidth=70, anchor="center")
        self.devices_tree.column("proximity", width=130, minwidth=100)
        self.devices_tree.grid(row=0, column=0, sticky="nsew")
        self.devices_tree.bind("<Double-1>", lambda _event: self.use_selected_device())

        scrollbar = ttk.Scrollbar(
            devices_frame, orient="vertical", command=self.devices_tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.devices_tree.configure(yscrollcommand=scrollbar.set)

        # ── footer ────────────────────────────────────────────────────────────
        footer = ttk.Frame(main)
        footer.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_text).grid(
            row=0, column=0, sticky="w"
        )
        self.activity = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.activity.grid(row=0, column=1, sticky="e")

    # ── scanning lifecycle ────────────────────────────────────────────────────

    def start_scanning(self) -> None:
        if self.scanning or self._closing:
            return

        self._apply_entered_name()
        self._drain_errors()
        self.book.clear()
        self.trend.reset()
        try:
            self.scanner.start()
        except RuntimeError as error:
            self.stop_scanning(f"Bluetooth scan failed: {error}")
            return

        self.scanning = True
        self.scan_button.configure(text="Stop scanning", command=self.stop_scanning)
        self.activity.start(12)
        self.status_text.set("Listening… walk around and watch the signal.")

    def stop_scanning(self, status: str = "Scanning stopped.") -> None:
        self.scanner.stop()
        self.scanning = False
        self.scan_button.configure(text="Start scanning", command=self.start_scanning)
        self.activity.stop()
        self.status_text.set(status)

    def _drain_errors(self) -> None:
        try:
            while True:
                self.errors.get_nowait()
        except queue.Empty:
            pass

    def _on_enter(self) -> None:
        self._apply_entered_name()
        self.start_scanning()

    def _apply_entered_name(self) -> None:
        entered_name = self.target_name.get().strip()
        if entered_name != self.saved_target_name:
            self._set_target(entered_name, "")

    def _tick(self) -> None:
        if self._closing:
            return
        try:
            try:
                error = self.errors.get_nowait()
            except queue.Empty:
                error = None

            if error is not None:
                self.stop_scanning(f"Bluetooth scan failed: {error}")
            elif self.scanning:
                self._refresh(time.monotonic())
        finally:
            if not self._closing:
                self._tick_after_id = self.root.after(TICK_MS, self._tick)

    # ── display ───────────────────────────────────────────────────────────────

    def _refresh(self, now: float) -> None:
        readings = self.book.snapshot()
        self._update_tree(readings, now)
        has_target = bool(self.saved_target_name or self.target_address)

        if not readings:
            self.status_text.set(
                "Listening… no Bluetooth LE devices heard yet. "
                "Check Bluetooth and open the earbud case."
            )
            if has_target:
                self._show_not_found()
            return

        if not has_target:
            self.status_text.set(
                f"Hearing {len(readings)} devices. Select your earbuds from the list."
            )
            return

        match = find_target(
            readings,
            target_name=self.saved_target_name,
            target_address=self.target_address,
        )
        if match is None:
            self.status_text.set(
                f"{self.saved_target_name or 'Saved earbuds'} not heard recently. "
                "Move closer or open the case."
            )
            self._show_not_found()
            return

        self._show_match(match, now)
        self.status_text.set(
            f"Tracking {match.display_name} among {len(readings)} devices."
        )

    def _update_tree(self, readings: list[DeviceReading], now: float) -> None:
        tree = self.devices_tree
        seen: set[str] = set()

        for reading in readings:
            values = (
                reading.display_name,
                reading.address,
                f"{reading.rssi} dBm",
                reading.proximity,
            )
            item = self._tree_items.get(reading.address)
            if item is None:
                item = tree.insert("", "end", values=values)
                self._tree_items[reading.address] = item
            else:
                tree.item(item, values=values)
            self.devices_by_item[item] = reading
            seen.add(reading.address)

        for address in [a for a in self._tree_items if a not in seen]:
            item = self._tree_items.pop(address)
            tree.delete(item)
            self.devices_by_item.pop(item, None)

        if now - self._last_sort >= SORT_INTERVAL_S:
            self._last_sort = now
            for index, reading in enumerate(readings):
                tree.move(self._tree_items[reading.address], "", index)

    def _show_match(self, reading: DeviceReading, now: float) -> None:
        self.found_name.set(reading.display_name)
        self.signal_text.set(f"Signal: {reading.rssi} dBm")
        self.proximity_text.set(f"Proximity: {reading.proximity}")
        self.trend_text.set(self.trend.update(reading.rssi, now))
        self.history_text.set(
            f"Smoothed over the last {SMOOTHING_WINDOW_S:.0f} s "
            f"from {reading.samples} readings."
        )
        self.last_seen_text.set("Last seen: now")
        self.signal_bar["value"] = signal_percent(reading.rssi)

        if now - self._last_seen_saved >= LAST_SEEN_SAVE_INTERVAL_S:
            self._last_seen_saved = now
            self.config["last_seen"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            self._save_config_safely()

    def _show_not_found(self) -> None:
        self.trend.reset()
        self.found_name.set(self.saved_target_name or "Earbuds not detected")
        self.signal_text.set("Signal: —")
        self.proximity_text.set("Proximity: Not detected")
        self.trend_text.set("Try another room, move closer, or open the charging case.")
        self.history_text.set("")
        self.last_seen_text.set(
            f"Last seen: {format_last_seen(self.config.get('last_seen'))}"
        )
        self.signal_bar["value"] = 0

    # ── target management ─────────────────────────────────────────────────────

    def use_selected_device(self) -> None:
        selection = self.devices_tree.selection()
        reading = self.devices_by_item.get(selection[0]) if selection else None
        if reading is None:
            messagebox.showinfo(APP_TITLE, "Select a device from the list first.")
            return

        self._set_target(reading.name, reading.address)
        self.target_name.set(reading.name)
        self.found_name.set(reading.display_name)
        self.status_text.set(f"Tracking {reading.display_name} as your earbuds.")

    def _set_target(self, name: str, address: str) -> None:
        self.saved_target_name = name.strip()
        self.target_address = address.strip()
        self.trend.reset()
        self.history_text.set("")
        self.config["target_name"] = self.saved_target_name
        self.config["target_address"] = self.target_address
        self.config.pop("last_seen", None)
        self.last_seen_text.set("Last seen: Never")
        self._save_config_safely()

    def _save_config_safely(self) -> None:
        try:
            save_config(self.config)
        except OSError as error:
            self.status_text.set(f"Could not save settings: {error}")

    def _on_close(self) -> None:
        """Cancel the refresh timer and stop scanning before the window goes."""
        self._closing = True
        if self._tick_after_id is not None:
            self.root.after_cancel(self._tick_after_id)
            self._tick_after_id = None
        self.scanner.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    FindMyBudsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
