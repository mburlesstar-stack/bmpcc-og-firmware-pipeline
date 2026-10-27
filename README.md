# BMPCC OG Firmware Patcher

A small, documented pipeline for **patching and flashing modified firmware on the
original Blackmagic Pocket Cinema Camera (PID `bd73`)** using Blackmagic's own
Camera Setup updater.

It rebuilds the `BDBD` firmware container with correct (keyless) integrity, gives
you a one-click GUI to build/verify/stage an image, and optionally flips the
updater's "your firmware is current" check so that same-version images can be
re-flashed.

> **This is an experimental homebrew tool.** Modified firmware can brick the
> camera. Use a **spare body**, keep the stock image and backups, and read
> [docs/SAFETY.md](docs/SAFETY.md). Not affiliated with Blackmagic Design.

---

## Status

| Item | Status |
|------|--------|
| Patch → repack → verify → flash → boot | **Working** (proven on hardware) |
| Version bump (2.1 → 2.2) | **Working** (safe pipeline test) |
| 1080p60 descriptor | **Experimental** — appears in the menu and records ProRes, but the OG's FPGA video pipeline has no 60p timing, so the image is broken (purple bars / alternating exposure). |
| Global shutter | **Not working.** The sensor supports it, but the OG firmware/FPGA does not expose the required readout mode. |
| SD-card compatibility | **Diagnosis only.** Novel cards fail inside the FPGA SD-host init; not fixable from BlamOS. |

The pipeline itself is the deliverable. Feature patches depend on the hardware
and are provided as examples of how to add your own.

---

## Requirements

* Windows (the flashing step uses Blackmagic's Windows updater).
* Python **3.10+** with Tkinter (bundled with the python.org installer).
* **Blackmagic Camera Setup 2.8.1** installed or extracted (for
  `CameraSetup.exe` and the stock `data-bd73.bin`).
* Runtime has **no third-party Python dependencies**.

### Get the stock image

The stock `data-bd73.bin` is part of the official installer:

```
Blackmagic Camera Setup 2.8.1/
  CameraSetup.exe
  data-bd73.bin      <-- this is the stock image
  ...
```

Its SHA-256 is:

```
652f9da909706cace1ca24b4eb14b7ce4504c2cabce5999ebc54ffc6dc7f162c
```

The repository does **not** include Blackmagic firmware. Extract it yourself.

---

## Quick start (GUI)

```powershell
python main.py
```

1. **Stock firmware** — browse to your stock `data-bd73.bin`.
2. **Patch** — choose *Version bump (safe test)* (recommended first run) or
   *Enable 1080p60 (experimental)*.
3. **Output** — where to save the patched image.
4. **Build patched image** — rebuilds and verifies the container.
5. **Flash**
   * point at `CameraSetup.exe` (or press **Detect**),
   * keep **Allow re-flashing the same version** ticked,
   * press **Stage & launch updater**.

The tool backs up the current `data-bd73.bin` as `data-bd73.stock.bin` and
`CameraSetup.exe` as `CameraSetup.exe.stock.exe`. Use the **Restore** buttons to
undo.

> The updater may report **“Updating the camera software failed”** even when the
> flash actually succeeded (it can mis-handle a forced same-version update).
> Verify by the camera's reported version or behaviour.

### Folder permissions

`CameraSetup.exe` is usually under `C:\Program Files\…`, which is **not
writable** without elevation. Either run the patcher **as administrator**, or use
a writable extracted copy of Camera Setup. The UI refuses to stage into a
non-writable folder.

---

## Command line

```powershell
# list patches
python -m bmpcc_pipeline.cli list

# build a safe test image (version 2.1 -> 2.2)
python -m bmpcc_pipeline.cli build data-bd73.bin out.bin --patch version-bump --version 2.2

# build the experimental 60p image
python -m bmpcc_pipeline.cli build data-bd73.bin out60.bin --patch enable-60p

# verify any image
python -m bmpcc_pipeline.cli verify out.bin

# allow the updater to re-flash the same version (backup kept)
python -m bmpcc_pipeline.cli camsetup-patch "C:\path\to\CameraSetup.exe"
python -m bmpcc_pipeline.cli camsetup-restore "C:\path\to\CameraSetup.exe"
```

---

## Build a standalone .exe

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# -> dist\BMPCC-Firmware-Patcher.exe
```

Requires `pyinstaller` (`python -m pip install pyinstaller`).

---

## How it works

`data-bd73.bin` is a `BDBD` container with two zlib-compressed sections:

| Section | Content |
|---------|---------|
| 0 | Xilinx Spartan-6 FPGA bitstream |
| 1 | BlamOS — big-endian MicroBlaze ELF |

Integrity is **keyless**:

* file digest (`bytes 0x00..0x1F`) = `SHA-256(PFX20 || file[0x20:])`
* per-section checksum = first 4 bytes of `SHA-256(PFX20 || decompressed_section)`

`bmpcc_pipeline/repack.py` parses/rebuilds this container; `mbdis.py` maps ELF
virtual addresses to file offsets. A patch edits the decompressed BlamOS blob,
then the container is repacked and re-verified. Blackmagic's updater does the
actual USB flashing.

See [docs/FORMAT.md](docs/FORMAT.md) for the full byte layout and
[docs/PATCHES.md](docs/PATCHES.md) for writing your own patch.

---

## Safety and recovery

* Use a **spare camera**. Keep the stock `data-bd73.bin` and the
  `*.stock.*` backups.
* If the camera does not boot, re-flash the stock image with the updater.
* Worst case, the SPI NOR can be reprogrammed with a CH341A/SOP-8 clip.
* Do not leave experimental images on a camera you rely on.

More in [docs/SAFETY.md](docs/SAFETY.md).

---

## Project layout

```
main.py                      GUI entry point
bmpcc_pipeline/
  patcher.py                 container + ELF editing, integrity, CameraSetup helper
  patches.py                 built-in patches (version bump, 1080p60)
  repack.py                  BDBD container parser/rebuilder
  mbdis.py                   MicroBlaze disassembler / VA mapping
  gui.py                     Tkinter UI
  cli.py                     command line
docs/
  FORMAT.md                  container format & integrity
  PATCHES.md                 how to write a patch
  SAFETY.md                  brick recovery
```

## Credits / licence

Built from reverse-engineering of the Blackmagic Camera Setup 2.8.1 package.
Blackmagic firmware and Camera Setup are © Blackmagic Design; this repository
contains no Blackmagic binaries. The tooling is released under the MIT licence —
see [LICENSE](LICENSE).
