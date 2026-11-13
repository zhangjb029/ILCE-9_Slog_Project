# ILCE-9_Slog_Project

Put Picture Profile and S-Log Display Assist into the Fn menu of a Sony A9 (ILCE-9, firmware 6.00) — plus 75 other functions the camera ships with but never exposes.

[简体中文](README.zh-CN.md)

**The window now has an "electronic-shutter flash" tab**: read the current state, open the upper-layer rule and the AV eligibility gate as two separate steps, and restore from either journal. The same operations remain available as `python -m a9tool.flash` and `python -m a9tool.flash_av` (read-only by default). As of 2026-11-11 the user confirmed that with both settings open, single-frame electronic shutter actually fires a flash; electronic burst still fires only the first frame, and hardware safety is not verified. Procedure, restore and limits: [delivery notes](docs/FLASH_DELIVERY.zh-CN.md) (Chinese).

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

## Electronic-shutter flash  ⚠ writes to the camera

This is a second tab in the same window. It lets an electronic shutter fire a flash on the A9. **Nothing here is verified beyond what is written below, and hardware safety has not been established.**

**Do this with the camera and the flash both switched off. Take the hot-shoe flash off before connecting.** Put it back only after the app has exited and the camera has been power-cycled and disconnected.

### What is known

| Situation | Result |
|---|---|
| Electronic shutter, single shot, both settings open | Fires the flash |
| Electronic shutter faster than 1/160 s | Black band in the frame |
| Electronic shutter at 1/125 s or slower | Full-frame illumination reported by the user |
| Mechanical shutter continuous | Fires every frame |
| Electronic shutter continuous | **First frame only**; the flash icon then greys out |
| Hardware safety, TTL accuracy, HSS, wireless | Not verified |

### Step 1 — Read, which also saves the baseline

Switch to the **电子快门引闪** tab and click **连接并读取状态**.

Two values appear: the upper-layer rule (`45`) and the AV eligibility byte (`AD`). **The first successful read also writes a baseline into `sessions\flash_baseline\`.** That baseline is what the restore button puts back. Until it exists, both write buttons stay grey on purpose — you cannot reach a state you have no way to undo from the same window.

### Step 2 — Open the upper-layer rule  ⚠

With `45 = 1`, click **① 开放上层规则（45：1 → 0）**. Confirm the dialog. Wait for `SAVED_AND_READBACK_VERIFIED` in the log.

**Power-cycle the camera.** This step alone does not make the flash fire — it only makes the menu item selectable again.

### Step 3 — Open the AV eligibility  ⚠

Reconnect, read the state again (it should show `45 = 0`), then click **② 开放 AV 资格（AD：0 → 1）**. Confirm. Wait for the same success line, then **power-cycle again**.

With both open, single-frame electronic shutter fires the flash.

### Step 4 — Undo

Open the tab and click **恢复到初始备份**. It writes both properties back to the values captured on the first read and tells you which ones actually needed restoring. If the baseline was recorded on a different camera body, it refuses.

### Why it takes two connections

Each of the two settings is guarded by its own packet allowlist, and neither guard permits the other's property. The tab therefore opens a fresh connection per step, and closes the Fn session first. A read or a write takes about as long as the connect step in the Fn tab.

## Menu transplant  ⚠ replaces a 300 MiB partition

The third tab replaces the whole `/dev/nflasha15` partition. **This is not a parameter change.** It replaces the partition that holds `/usr`, and a previous attempt with a different layout left the camera cold-starting with no menu at all (that build is withdrawn).

**No image is shipped or downloaded.** The tool reads the camera's own partition, checks it is byte-identical to the factory build, applies the 677 bytes that were confirmed on hardware, and verifies the result against the candidate SHA256 — all locally, before anything is written. Two hashes pin both ends: `ed835ff9…` going in, `4fa7bbe5…` coming out. A partition in any other state is refused, not overwritten.

What that change contains: a creative-style entry, Picture Profile, S-Log Display Assist, and four aspect ratios.

### What the image does and does not carry

The partition holds firmware, not camera identity. On the machine this was verified on, the live partition's first 221,609,984 bytes were **byte-identical to the official firmware's `nflasha15`** — no serial, no calibration, no per-body data lives there.

So the image is portable across ILCE-9 bodies at 6.00. **The features are not.** Opening 4:3 and saving it also needs the companion parameters in `/setting/Backup.bin` (`nflasha2`), which are per-body. A transplanted menu on a body without those parameters will show the entries but not complete the save chain.

### Step 1 — Read, patch, write

**Camera on, battery charged, USB stable. Close every other program that talks to the camera.**

1. Open the **菜单移植** tab and click **读取分区并写入菜单修改…**.
2. Confirm both dialogs.

There is nothing to download or pick. The tab reads the partition first, and only if it matches the factory hash does it build the candidate and write.

The tab then: reads the whole live partition to `sessions\menu\deploy_…\preimage.bin` (300 MiB, several minutes), refuses to continue if that read is short, patches it in memory, writes it once, and reads the partition back to verify. The first backup is also copied to `sessions\menu\baseline\` — that is what the restore button writes later.

**Budget 1.2 GB of free space** per operation: one archive of the current partition, one readback.

### Step 2 — Power cycle

Normal shutdown, full power removal, cold start. A warm restart is not enough — the partition is re-read at boot.

### Step 3 — Confirm

Reconnect, press **MENU**. You should see Picture Profile and S-Log Display Assist where the old entries were, and four aspect ratios.

### Undo

**恢复到初始备份** writes the partition captured before the first deploy back to the camera. It refuses if that backup is missing or damaged.

### Known limits

- The menu entries are confirmed. **Per-item PP parameters, actual S-Log recording, and the display-assist curve are not separately verified.**
- 4:3 RAW saves after the companion parameter set is applied; **4:3 JPEG does not** — the size submenu has no options and the free-frame count reads 0.
- The ratio prototype is shared between the `0x4B` and `0x4C` menu trees; other consumers were not exhaustively checked.

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

## Publishing a release

**The exe is not in git.** `.gitignore` excludes it, so a Release built from the repository alone has no download. `build/entry.py` is what the workflow runs.

Push a tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

`.github/workflows/release.yml` then runs the tests, builds, self-checks the bundle, and attaches `ILCE-9_Slog_Project.exe` plus `SHA256SUMS.txt` to the Release. Re-running the workflow for the same tag replaces the attached files.

To publish a build you made locally instead: GitHub → **Releases** → **Draft a new release** → upload `dist/ILCE-9_Slog_Project.exe`.

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
