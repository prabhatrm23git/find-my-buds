# Changelog

## 1.2.0

### Changed: continuous scanning
- The app now listens continuously (Start/Stop scanning) instead of running
  fixed-length scans on a timer. The **Scan duration** and **Auto-rescan**
  settings are removed; old values in the settings file are discarded.
- Each device's signal is the median of its readings over the last 5 seconds,
  and the Finder panel and device list refresh twice a second.
- Warmer/colder compares the current smoothed signal with the one from up to
  6 seconds earlier. Devices not heard for 12 seconds are dropped.
- The device list updates in place, keeping your selection.

### Fixed
- A failed scan no longer opens an error dialog repeatedly. Errors appear in
  the status bar and scanning stops.
- Closing the window stops scanning and cancels the refresh timer, so no
  callback runs after the window is destroyed.
- Warmer/colder guidance no longer uses a stale baseline from another room.
- Devices without a name are tracked as an empty name, so a device literally
  called "Unknown device" is no longer confused with an unnamed one.

### Changed
- Target matching is ranked: saved address, then exact name, then partial
  name. When an address is saved, partial name matches are ignored so a
  neighbour's similarly named device is not picked up. An exact name still
  matches if the earbuds rotated their BLE address.

- Scan errors are translated into plain messages (Bluetooth off, no adapter,
  permission denied).

- A corrupt settings file is kept as `.find_my_buds.json.corrupt` instead of
  being silently overwritten.
- "Last seen" is shown in a readable format. The window title shows the version.

### Internal
- Bluetooth scanning lives in `scanner.py` (`LiveScanner`), settings in
  `settings.py`, and smoothing/trend logic in `finder_core` (`DeviceBook`,
  `TrendTracker`). None of the logic imports `tkinter`, and all are unit
  tested with fake scanners and clocks.

## 1.1

- Auto-rescan with configurable interval and scan duration.
- Recent RSSI history and average.
- CI workflow and unit tests.

## 1.0

- Initial release.
