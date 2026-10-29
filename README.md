# ILCE-9_Slog_Project

Put Picture Profile and S-Log Display Assist into the Fn menu of a Sony A9 (ILCE-9, firmware 6.00) — plus 75 other functions the camera ships with but never exposes.

[简体中文](README.zh-CN.md) · [**Tutorial**](https://example.github.io/ILCE-9_Slog_Project/) · [**Download**](https://github.com/example/ILCE-9_Slog_Project/releases)

---

## What it does

The A9 has Picture Profile and S-Log Display Assist compiled in, but no menu entry to reach them. This tool writes a one-byte saved value into one of the twelve Fn slots through Sony's own service-mode parameter interface. The camera resolves that byte through its own function table, so the entry appears in the Fn menu — no firmware is modified.

Two functions have been confirmed on real hardware:

| Function | Saved value | Result on camera |
|---|---|---|
| Picture Profile | `0x3A` | Fn1 shows the entry, the recorded image changes, survives a restart |
| S-Log Display Assist | `0x36` | Fn7 shows the entry, works, survives a restart |

The other 75 values come from the camera's own function table and are selectable in the app. **None of them has been tested on hardware.** One of them — Pixel Shift Multi Shooting (`0x64`) — is known to hang the camera after the first frame and require a battery pull; it is marked in the interface.

## Requirements

- Sony **ILCE-9** with firmware **6.00**. Nothing else. The app refuses every other model and version before writing.
- Windows 10 or 11.
- [Zadig](https://zadig.akeo.ie/) for the USB driver. The tutorial walks through it.

## Using it

Read the [tutorial](https://example.github.io/ILCE-9_Slog_Project/). It covers the two separate driver installs, the SmartScreen prompt, why the memory card disappears, and how to undo everything.

The short version: put the camera in Mass Storage mode, replace its USB driver with libusb-win32, run the app, enable the PP override, restart, write a function into a slot, restart again, press Fn.

## Safety

Every write saves a full backup and a transaction journal next to the executable before touching the camera, and every write can be undone from the app. "Restore all" returns the camera to the state it was in before the tool was first used.

This is not a Sony tool. Modifying camera parameters may void your warranty. Use it on your own camera, at your own risk.

## Building

Build-time only; end users need nothing installed.

```powershell
pip install pyinstaller
powershell -File build/build_exe.ps1
```

Output: `dist/ILCE-9_Slog_Project.exe` (~20 MB, onefile, unsigned).

## Tests

```powershell
python -m unittest discover -s tests -t .
```

All tests are offline: a `FakeCamera` stands in for the real device, so no camera and no USB backend is needed. 70 tests, including Tk widget-state checks.

## How it works

The saved byte in an Fn slot is resolved by `viewUnified4.so`'s switch table into an internal node id, then looked up in the Fn runtime root array. That path does not consult the main menu tree, which is why Fn entries work while the settings menu still has no Picture Profile node. The resolver rejects any byte above `0x6E` before the lookup.

The PP feature-override property (`0x00880000`, five offsets set to `0x02`) must be enabled first, or the PP-dependent entries resolve to nothing.

## Licence

MIT — see [LICENSE](LICENSE). Third-party components and the origin of the firmware-derived tables are listed in [NOTICE](NOTICE).
