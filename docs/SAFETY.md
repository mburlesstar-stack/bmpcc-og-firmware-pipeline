# Safety and recovery

## Before you start

* Use a **spare camera**. Do not experiment on a body you rely on.
* Keep the **stock `data-bd73.bin`** and the tool's backups:
  * `data-bd73.stock.bin` (next to `CameraSetup.exe`)
  * `CameraSetup.exe.stock.exe`
* The camera should be on a good battery / mains and connected directly (no hub).

## What the tool changes

1. The patched `data-bd73.bin` (BlamOS / optionally the FPGA bitstream section).
2. Optionally, `CameraSetup.exe` (one instruction) so it will re-flash a
   same-version image.

Neither is irreversible: **Restore** buttons copy the backups back.

## Flashing

* Use Blackmagic Camera **Setup 2.8.1** (the version this tool targets).
* The updater may say **“Updating the camera software failed” even when the
  flash worked** (a forced same-version update can confuse its completion
  check). Verify by the camera's version or behaviour.
* If the camera black-screens or hangs after an experimental patch, restore the
  stock image and re-flash.

## Recovery ladder

1. **Restore stock** with the updater (`Restore stock data-bd73.bin` →
   `Stage & launch`).
2. If USB is unresponsive, try a different cable/port and the official installer
   from a clean machine.
3. **SPI NOR recovery:** the flash chip can be read/written with a CH341A-class
   programmer and a SOP-8 clip. Dump the stock chip *before* experimenting if
   you want a guaranteed recovery image.
4. The FPGA is configured from the same flash; a full stock dump restores both
   the bitstream and BlamOS.

## Folder permissions

The updater is normally installed under `C:\Program Files`, which is not
writable without elevation. Run the patcher **as administrator**, or use a
writable extracted copy of Camera Setup. The UI refuses to stage into a
non-writable folder.

## Legal

Blackmagic firmware and Camera Setup are © Blackmagic Design. This project ships
no Blackmagic binaries; you supply the stock image from your own installation.
Modifying firmware may affect warranty and is done at your own risk.
