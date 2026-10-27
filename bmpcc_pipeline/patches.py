"""Built-in firmware patches.

Each patch receives a :class:`~bmpcc_pipeline.patcher.FirmwareImage` whose
``blob`` is the decompressed BlamOS ELF.  Patches edit the blob (by virtual
address or byte replacement); the container is rebuilt/verified afterwards.

Adding your own patch is easy: subclass :class:`Patch`, implement ``apply``,
and register it in ``PATCHES``.
"""

import struct

from .patcher import FirmwareImage

_TABLE_BASE = 0x48865C6C
_ENTRY_SIZE = 0x48
_NAME_VA = 0x48866228


class Patch:
    key = ""
    name = ""
    description = ""
    experimental = False

    def apply(self, image: FirmwareImage, **kwargs):
        raise NotImplementedError


class VersionBump(Patch):
    key = "version-bump"
    name = "Version bump (safe test)"
    description = (
        "Changes the BlamOS version string (e.g. 2.1 -> 2.2) with no code "
        "changes. Use this to prove the patch/flash pipeline works."
    )

    def apply(self, image, version="2.2", **kwargs):
        if len(version) != 3:
            raise ValueError("version must be exactly 3 characters, e.g. 2.2")
        image.replace(b"2.1\x00", version.encode() + b"\x00")


class Enable60p(Patch):
    key = "enable-60p"
    name = "Enable 1080p60 (experimental)"
    description = (
        "Adds 1080p60 by replacing the 2Kp30 mode descriptor. The menu and "
        "ProRes recording accept it, but on the OG the preview/recording is "
        "broken (purple bars / alternating exposure) because the FPGA "
        "video pipeline has no 60p timing. For research only."
    )
    experimental = True

    def apply(self, image, **kwargs):
        entry_va = _TABLE_BASE + 9 * _ENTRY_SIZE  # replace 2Kp30 (index 9)
        # free zero run used for the name
        name_off = image.va2fo(_NAME_VA)
        if any(image.blob[name_off:name_off + 8]):
            raise ValueError("name slot at 0x48866228 is not empty")
        words = [
            1920, 1080,        # capture w/h
            0x0C, 0x20,        # model flags A/B
            60000, 1000,       # fps num/den
            60000, 60,         # nominal / integer fps
            1, 16, 0, 0,       # standard code (1080p60)
            9,                 # mode index
            _NAME_VA,          # name pointer
            0, 0,              # flags C/D
            1920, 1080,        # output w/h
        ]
        image.write_bytes(_NAME_VA, b"1080p60\x00")
        image.write_bytes(entry_va, b"".join(struct.pack(">I", w) for w in words))


PATCHES = {p.key: p for p in (VersionBump(), Enable60p())}


def get_patch(key):
    try:
        return PATCHES[key]
    except KeyError:
        raise ValueError(f"unknown patch {key!r}; available: {', '.join(PATCHES)}")
