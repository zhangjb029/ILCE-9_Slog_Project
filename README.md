# ILCE-9_Slog_Project

Put Picture Profile and S-Log Display Assist into the Fn menu of a Sony A9 (ILCE-9, firmware 6.00) — plus 75 other functions the camera ships with but never exposes.

[简体中文](README.zh-CN.md)

---

## What it does

The A9 has Picture Profile and S-Log Display Assist compiled in, but no menu entry to reach them. This tool writes a one-byte saved value into one of the twelve Fn slots through Sony's own service-mode parameter interface. The camera resolves that byte through its own function table, so the entry appears in the Fn menu. **No firmware is modified.**

Two functions have been confirmed on real hardware:

| Function | Saved value | Result on camera |
|---|---|---|
| Picture Profile | `0x3A` | Fn slot shows the entry, the recorded image changes, survives a restart |
| S-Log Display Assist | `0x36` | Fn slot shows the entry, works, survives a restart |

The other 75 values come from the camera's own function table and are selectable in the app. **None of them has been tested on hardware.** One — Pixel Shift Multi Shooting (`0x64`) — is known to hang the camera after the first frame and require a battery pull; the app marks it red and asks twice.

## Requirements

- Sony **ILCE-9** with firmware **6.00**. Nothing else. The app reads the model and version first and refuses everything else before writing.
- Windows 10 or 11.
- [Zadig](https://zadig.akeo.ie/) — free, no install needed. You will use it twice.
- One battery, charged. A USB data cable (not a charge-only cable).

> **The app's interface is in Chinese.** Every step below gives the Chinese button label with its meaning, so you can follow it without reading Chinese.

---

## Step-by-step

This is the whole procedure. If you are an AI agent following it, stop and ask your human before any step marked **⚠ writes to the camera**.

### Step 0 — Check the camera

On the camera: **MENU → Setup → Version**. It must say **6.00**, and the body must be an **ILCE-9** (not ILCE-9M2).

If not: stop. Different firmware keeps parameters at different addresses, and the app will refuse anyway.

### Step 1 — Get the executable

Download `ILCE-9_Slog_Project.exe` from this repository's **Releases** page. Put it somewhere persistent, e.g. `C:\A9Tool\`.

There is no installer and no uninstaller. On first run it creates a `sessions` folder next to the exe — that folder holds the backups, **do not delete it**.

### Step 2 — Get past SmartScreen

Double-click. Windows will say *"Windows protected your PC"*. Click **More info → Run anyway**.

The exe is unsigned (a code-signing certificate costs several hundred dollars a year). Antivirus software may also flag it, because it talks to a USB device directly. The source is in this repository — read it if you want.

### Step 3 — Install the driver for Mass Storage

1. Camera **off** → connect the USB cable → camera **on**.
2. If the camera asks how to connect, choose **Mass Storage**. The memory card should appear in Windows Explorer.
3. Open **Zadig**.
4. **Options → List All Devices**.
5. In the dropdown, select your camera — it may appear as `Sony Digital Still Camera` or similar.
6. Confirm the target driver on the right says **libusb-win32**; use the arrows to change it if it does not.
7. Click **Install Driver** (or **Replace Driver**) and wait for it to finish.

> **Do not pick `USB Input Device` / VID `054C` PID `0994`.** That is the camera's USB *input* interface, not the storage device this tool talks to. Replacing its driver breaks that input device on your PC.

**Expect:** after this, Windows Explorer no longer shows the memory card, and you may get a "you need to format this disk" popup. **That is normal. Do not format.** Section "Restoring the camera to Windows" at the end puts it back.

### Step 4 — Connect

1. Run `ILCE-9_Slog_Project.exe`. A single window opens with four numbered sections and a log at the bottom.
2. Click **连接并检查** (*Connect and check*) in section ① .

**Expect, in the log:**

```
已确认 ILCE-9 / 6.00，正在切换服务模式     ← model confirmed, switching to service mode
服务模式已认证，正在读取机身参数            ← service mode authenticated, reading parameters
```

and section ② fills in with model, firmware, and a serial fingerprint.

**If the log says `Service device not found`:** go to step 5.

**If the log says 没有找到相机 (*no camera found*):** the camera is not in Mass Storage mode, or the driver from step 3 is not installed, or the cable is charge-only.

### Step 5 — Install the driver again (only if step 4 failed)

Service mode is a **different USB device** and needs its own driver install. This is normal and expected.

1. Leave the camera plugged in, exactly as it is.
2. Open **Zadig** again → **Options → List All Devices**.
3. A new Sony device is now listed, usually with `(Interface 1)` in the name.
4. Install **libusb-win32** for it too.
5. Back in the app, click **重试** (*Retry*).

**Expect:** the connection completes and section ② fills in.

> The retry token expires after one hour. If it does, unplug the camera, return it to Mass Storage, and start again from step 4. Nothing has been written at this point, so restarting is safe.

### Step 6 — Enable the PP override  ⚠ writes to the camera

Section ② shows **PP 放行** (*PP override*) as **✗ 未开启** (*off*).

Click **开启 PP 放行** (*Enable PP override*), confirm, and wait for **SAVED_AND_READBACK_VERIFIED** or a success message in the log.

This writes **five bytes** in one 1024-byte property. It does **not** touch any Fn slot.

**Then power the camera off and on.** The camera only re-reads these parameters at boot. Do not skip this.

**If section ② shows ⚠ 状态异常 (*inconsistent state*):** the five bytes are partly set. The app refuses to write. Use **恢复全部原厂** (*Restore factory*) in section ④, or start over.

### Step 7 — Write a function into a slot  ⚠ writes to the camera

Run the app again and repeat step 4 (no driver install needed this time).

Section ③ now shows two cards: **Picture Profile** and **SLog 显示辅助**. Each has a slot dropdown (**Fn1** … **Fn12**) and a write button.

1. Pick a slot.
2. Click the write button (写入).
3. Confirm.

For anything else, expand **▸ 全部功能（77 项，多数未验证）** (*all functions, 77 items, mostly untested*), select a row, choose a slot, click **写入所选功能**.

**Expect:** `SAVED_AND_READBACK_VERIFIED` in the log, and **every write button greys out**. That is deliberate — one run of the program performs exactly one change, each with its own backup. To change another slot, close and reopen the app.

**Then power the camera off and on.**

### Step 8 — Confirm on the camera

Press **Fn**. The slot you wrote to should now show the function.

> **"It appears in the menu" is not "it works."** All twelve slots accept a write and the camera displays the entry — but an entry existing only means the entry exists. Picture Profile and S-Log Display Assist are confirmed working. The other 75 have never been tried on hardware; expect greying out, no effect, or a freeze.

### Step 9 — Undo

**One change:** section ④ lists every write with a timestamp. Select a row → **从备份恢复到原状** (*restore from this backup*) → power-cycle.

Each row's "original" value is the value *before that particular write*. If you made several changes, undoing the second returns you to the state after the first, not to factory. The list marks those rows.

**Everything:** **恢复全部原厂** (*restore all*) writes back every position this tool has touched, as it was before first use. It will also overwrite settings you changed by hand on the camera.

### Restoring the camera to Windows

When you are done:

1. Close the app.
2. Right-click Start → **Device Manager**.
3. Find the camera under **libusb-win32 devices** (or similar).
4. Right-click → **Uninstall device**, tick **Delete the driver software for this device**.
5. Unplug and replug the USB cable. Windows reinstalls its own driver; the memory card returns.

Uninstall only the camera entry. Leave every other USB device alone.

---

## If something goes wrong

| Log message | Meaning | What to do |
|---|---|---|
| `Service device not found` | Camera is in service mode, Windows has no driver for that device | Step 5 |
| 没有找到相机 | No camera matched | Check Mass Storage mode, driver from step 3, cable |
| 找到多台相机 | More than one camera plugged in | Unplug the others |
| `Camera busy during identity request` | Camera reported busy | Power-cycle the camera, close Imaging Edge and similar software, reconnect |
| 只支持 ILCE-9 固件 6.00 | Wrong model or firmware | Nothing to do — the app refuses by design |
| `FAILED_REVIEW_REQUIRED` (inside `sessions/…/journal.json`) | A write failed part-way | Keep the `sessions` folder; the camera may have a partial change. Restore from the app before retrying |

Every write records a journal in `sessions/<timestamp>/` next to the exe. If you ask for help, include that file's `state` and `error` fields plus the log from the bottom of the window — **not** the whole `Backup-original.bin`, which contains camera configuration data.

---

## Safety

Every write saves a full backup and a transaction journal next to the executable **before** touching the camera, and every write can be undone from the app.

This is not a Sony tool. Modifying camera parameters may void your warranty. Use it on your own camera, at your own risk.

---

## Building

Build-time only; end users need nothing installed.

```powershell
pip install pyinstaller
powershell -File build/build_exe.ps1
```

Output: `dist/ILCE-9_Slog_Project.exe` (~15 MB, onefile, unsigned).

Verify the bundle without a camera:

```powershell
$env:A9TOOL_CONSOLE=1
python -m PyInstaller build/a9tool.spec --clean --noconfirm
$env:A9TOOL_SELFCHECK=1; .\dist\ILCE-9_Slog_Project.exe
```

A windowed exe has no console, so build with `A9TOOL_CONSOLE=1` to read the output. It checks the JSON tables, the sessions path, the bundled libusb backend, and that the main window constructs with all 77 rows.

## Tests

```powershell
python -m unittest discover -s tests -t .
```

All tests are offline: a `FakeCamera` stands in for the real device, so no camera and no USB backend is needed. 87 tests, including Tk widget-state checks and a subprocess check that the vendored stack imports with site-packages disabled.

## How it works

The saved byte in an Fn slot is resolved by `viewUnified4.so`'s switch table into an internal node id, then looked up in the Fn runtime root array. That path does not consult the main menu tree, which is why Fn entries work while the settings menu still has no Picture Profile node. The resolver rejects any byte above `0x6E` before the lookup.

The PP feature-override property (`0x00880000`, five offsets set to `0x02`) must be enabled first, or the PP-dependent entries resolve to nothing.

## Licence

MIT — see [LICENSE](LICENSE). Third-party components and the origin of the firmware-derived tables are listed in [NOTICE](NOTICE).

A screenshot-illustrated version of this guide is in `docs/` (`docs/index.html`, `docs/zh-CN/index.html`) — open the file directly in a browser; the images are placeholders until someone takes them on a real machine.
