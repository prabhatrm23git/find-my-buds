"""Find My Buds desktop application."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from finder_core import (
    DeviceReading,
    describe_trend,
    discover_devices,
    reading_matches,
    signal_percent,
)

APP_TITLE = "Find My Buds"
CONFIG_PATH = Path.home() / ".find_my_buds.json"
SCAN_SECONDS = 5.0


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary_path.replace(path)


class FindMyBudsApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x650")
        self.root.minsize(720, 560)

        self.config = load_config()
        self.target_address = str(self.config.get("target_address", ""))
        self.saved_target_name = str(self.config.get("target_name", ""))
        self.previous_rssi: int | None = None
        self.devices_by_item: dict[str, DeviceReading] = {}
        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.scan_in_progress = False

        self.target_name = tk.StringVar(value=self.saved_target_name)
        self.status_text = tk.StringVar(value="Ready to scan for nearby Bluetooth devices.")
        self.found_name = tk.StringVar(value="No earbud selected")
        self.signal_text = tk.StringVar(value="Signal: —")
        self.proximity_text = tk.StringVar(value="Proximity: —")
        self.trend_text = tk.StringVar(value="Select your earbuds from a scan to begin.")
        last_seen = str(self.config.get("last_seen", "Never"))
        self.last_seen_text = tk.StringVar(value=f"Last seen: {last_seen}")

        self._build_ui()
        self.root.after(150, self._process_results)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Result.TLabel", font=("Segoe UI", 16, "bold"))

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
            text="Use Bluetooth signal strength to search for nearby earbuds.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 16))

        target_frame = ttk.LabelFrame(main, text="Your earbuds", padding=12)
        target_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        target_frame.columnconfigure(1, weight=1)

        ttk.Label(target_frame, text="Name:").grid(row=0, column=0, padx=(0, 8))
        target_entry = ttk.Entry(target_frame, textvariable=self.target_name)
        target_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        target_entry.bind("<Return>", lambda _event: self.start_scan())

        self.scan_button = ttk.Button(
            target_frame,
            text="Scan nearby",
            command=self.start_scan,
        )
        self.scan_button.grid(row=0, column=2, padx=(0, 8))

        self.use_button = ttk.Button(
            target_frame,
            text="Use selected device",
            command=self.use_selected_device,
        )
        self.use_button.grid(row=0, column=3)

        result_frame = ttk.LabelFrame(main, text="Finder", padding=14)
        result_frame.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        result_frame.columnconfigure(0, weight=1)

        ttk.Label(result_frame, textvariable=self.found_name, style="Result.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.signal_bar = ttk.Progressbar(
            result_frame,
            maximum=100,
            mode="determinate",
        )
        self.signal_bar.grid(row=1, column=0, sticky="ew", pady=(10, 6))

        details = ttk.Frame(result_frame)
        details.grid(row=2, column=0, sticky="ew")
        details.columnconfigure(0, weight=1)
        details.columnconfigure(1, weight=1)
        ttk.Label(details, textvariable=self.signal_text).grid(row=0, column=0, sticky="w")
        ttk.Label(details, textvariable=self.proximity_text).grid(row=0, column=1, sticky="e")
        ttk.Label(result_frame, textvariable=self.trend_text).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(result_frame, textvariable=self.last_seen_text).grid(
            row=4, column=0, sticky="w", pady=(4, 0)
        )

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
            devices_frame,
            orient="vertical",
            command=self.devices_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.devices_tree.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(main)
        footer.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_text).grid(row=0, column=0, sticky="w")
        self.activity = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.activity.grid(row=0, column=1, sticky="e")

    def start_scan(self) -> None:
        if self.scan_in_progress:
            return

        entered_name = self.target_name.get().strip()
        if entered_name != self.saved_target_name:
            self._set_target(entered_name, "")

        self.scan_in_progress = True
        self.scan_button.configure(state="disabled")
        self.activity.start(12)
        self.status_text.set(f"Scanning for {SCAN_SECONDS:.0f} seconds…")

        worker = threading.Thread(target=self._scan_worker, daemon=True)
        worker.start()

    def _scan_worker(self) -> None:
        try:
            readings = asyncio.run(discover_devices(timeout=SCAN_SECONDS))
        except Exception as error:  # noqa: BLE001 - scanner errors cross thread boundary.
            self.result_queue.put(("error", error))
        else:
            self.result_queue.put(("readings", readings))
        finally:
            self.result_queue.put(("finished", None))

    def _process_results(self) -> None:
        try:
            while True:
                event, payload = self.result_queue.get_nowait()
                if event == "readings":
                    self._show_readings(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._show_error(payload)  # type: ignore[arg-type]
                elif event == "finished":
                    self.scan_in_progress = False
                    self.scan_button.configure(state="normal")
                    self.activity.stop()
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._process_results)

    def _show_readings(self, readings: list[DeviceReading]) -> None:
        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)
        self.devices_by_item.clear()

        for reading in readings:
            item = self.devices_tree.insert(
                "",
                "end",
                values=(
                    reading.name,
                    reading.address,
                    f"{reading.rssi} dBm",
                    reading.proximity,
                ),
            )
            self.devices_by_item[item] = reading

        if not readings:
            self.status_text.set(
                "No BLE devices found. Check Bluetooth and open the earbud case."
            )
            self._show_not_found()
            return

        if not (self.saved_target_name or self.target_address):
            self.status_text.set(
                f"Found {len(readings)} devices. Select your earbuds from the list."
            )
            return

        match = next(
            (
                reading
                for reading in readings
                if reading_matches(
                    reading,
                    target_name=self.saved_target_name,
                    target_address=self.target_address,
                )
            ),
            None,
        )
        if match is None:
            self.status_text.set(
                f"{self.saved_target_name or 'Saved earbuds'} not detected. "
                "Move closer or open the case."
            )
            self._show_not_found()
            return

        self._show_match(match)
        self.status_text.set(f"Found {match.name} among {len(readings)} devices.")

    def _show_match(self, reading: DeviceReading) -> None:
        trend = describe_trend(self.previous_rssi, reading.rssi)
        self.previous_rssi = reading.rssi
        seen_at = datetime.now().astimezone().isoformat(timespec="seconds")

        self.found_name.set(reading.name)
        self.signal_text.set(f"Signal: {reading.rssi} dBm")
        self.proximity_text.set(f"Proximity: {reading.proximity}")
        self.trend_text.set(trend)
        self.last_seen_text.set(f"Last seen: {seen_at}")
        self.signal_bar["value"] = signal_percent(reading.rssi)

        self.config["last_seen"] = seen_at
        self._save_config_safely()

    def _show_not_found(self) -> None:
        self.found_name.set(self.saved_target_name or "Earbuds not detected")
        self.signal_text.set("Signal: —")
        self.proximity_text.set("Proximity: Not detected")
        self.trend_text.set("Try another room, move closer, or open the charging case.")
        self.signal_bar["value"] = 0

    def use_selected_device(self) -> None:
        selection = self.devices_tree.selection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "Select a device from the list first.")
            return

        reading = self.devices_by_item[selection[0]]
        target_name = "" if reading.name == "Unknown device" else reading.name
        self._set_target(target_name, reading.address)
        self.target_name.set(target_name)
        self.found_name.set(reading.name)
        self.status_text.set(f"Saved {reading.name} as your earbuds. Scan again to find them.")

    def _set_target(self, name: str, address: str) -> None:
        self.saved_target_name = name.strip()
        self.target_address = address.strip()
        self.previous_rssi = None
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

    def _show_error(self, error: object) -> None:
        text = str(error) or error.__class__.__name__
        self.status_text.set(f"Bluetooth scan failed: {text}")
        messagebox.showerror(
            "Bluetooth scan failed",
            f"{text}\n\nCheck that Bluetooth is enabled and this app has permission to use it.",
        )


def main() -> None:
    root = tk.Tk()
    FindMyBudsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
