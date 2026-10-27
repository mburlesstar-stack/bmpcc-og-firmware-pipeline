# Writing a patch

A patch receives a `FirmwareImage` whose `blob` is the **decompressed BlamOS
ELF**. Edit the blob, and the pipeline repacks + verifies the container.

## Minimal example

```python
from bmpcc_pipeline.patcher import FirmwareImage
from bmpcc_pipeline.patches import Patch


class RenameMode(Patch):
    key = "rename-2k"
    name = "Rename a mode label"
    description = "Example: rename the 2Kp30 menu label."

    def apply(self, image: FirmwareImage, **kwargs):
        # same-length replacement keeps every address stable
        image.replace(b"2Kp30\x00", b"2KTE5\x00")
```

Register it in `bmpcc_pipeline/patches.py`:

```python
PATCHES = {p.key: p for p in (VersionBump(), Enable60p(), RenameMode())}
```

and it appears in the GUI and `--patch` list automatically.

## `FirmwareImage` API

| Method | Purpose |
|--------|---------|
| `image.va2fo(va)` | virtual address → offset in `image.blob` |
| `image.read_u32(va)` | read a big-endian word |
| `image.write_u32(va, value)` | write a big-endian word |
| `image.write_bytes(va, raw)` | write raw bytes at a VA |
| `image.replace(old, new, limit=1)` | exact byte replacement (fails unless count matches) |
| `image.version()` | current BlamOS version string |
| `image.blob` | the editable `bytearray` |

After `apply()`, the framework calls `rebuild()` and verifies the result.

## Rules of thumb

* **Keep string lengths identical** unless you know nothing after the string
  depends on its position (the ELF is position-sensitive).
* Prefer editing a **descriptor or data table** over code. Code patches need
  MicroBlaze encodings; `mbdis.py` can decode instructions for verification.
* A code cave approach is possible but the cave must fit an unused, file-backed
  zero region and the hook must preserve registers.
* Test with the **version-bump** patch first to prove the flash path.

## Testing

```powershell
python -m bmpcc_pipeline.cli build data-bd73.bin out.bin --patch <key>
python -m bmpcc_pipeline.cli verify out.bin
```

Then flash with the GUI (or `camsetup-patch` + the updater).
