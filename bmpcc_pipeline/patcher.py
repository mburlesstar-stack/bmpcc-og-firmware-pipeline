"""Core patching pipeline for the original Pocket Cinema Camera (PID bd73).

The official Blackmagic Camera Setup ships ``data-bd73.bin``: a ``BDBD``
container with two zlib sections (the Spartan-6 FPGA bitstream and the BlamOS
MicroBlaze ELF).  The container integrity is a keyless SHA-256 digest plus
per-section checksums, so a modified image can be rebuilt and flashed by the
official updater.

This module provides:

* :class:`FirmwareImage` - parse the container, find/read/write the BlamOS ELF
  by virtual address, and rebuild a byte-exact container.
* :func:`verify`, :func:`inspect` - integrity and identity helpers.
* :func:`build_patched` - apply a patch object and re-verify.
* :class:`CameraSetup` - optional helper that toggles the updater's
  "firmware is current" check so a same-version image can be re-flashed.
"""

import hashlib
import os
import re
import shutil
import struct

from . import mbdis, repack

#: SHA-256 of the stock ``data-bd73.bin`` from Blackmagic Camera Setup 2.8.1.
STOCK_SHA256 = "652f9da909706cace1ca24b4eb14b7ce4504c2cabce5999ebc54ffc6dc7f162c"

_VERSION_RE = re.compile(rb"2\.\d\x00")


class FirmwareImage:
    """A parsed ``data-bd73.bin`` image with an editable BlamOS blob."""

    def __init__(self, data):
        self.raw = data
        self.orig = repack.parse(data)
        self.secs = [{"hdr": s["hdr"], "dec": bytes(s["dec"])} for s in self.orig]
        self.si, self.elf = self._find_blamos()
        self.blob = bytearray(self.secs[self.si]["dec"])

    def _find_blamos(self):
        best = None
        for i, s in enumerate(self.secs):
            img = mbdis.Image(bytes(s["dec"]))
            if not img.segs:
                continue
            size = sum(sz for _, _, sz in img.segs)
            if best is None or size > best[0]:
                best = (size, i, img)
        if best is None:
            raise ValueError("no BlamOS ELF segment found in this image")
        return best[1], best[2]

    # -- address helpers -------------------------------------------------
    def va2fo(self, va):
        fo = self.elf.va2fo(va)
        if fo is None:
            raise ValueError(f"VA {va:#x} is not mapped in BlamOS")
        return fo

    def read_u32(self, va):
        fo = self.va2fo(va)
        return struct.unpack(self.elf.end + "I", self.blob[fo:fo + 4])[0]

    def write_u32(self, va, value):
        fo = self.va2fo(va)
        struct.pack_into(self.elf.end + "I", self.blob, fo, value)

    def write_bytes(self, va, raw):
        fo = self.va2fo(va)
        self.blob[fo:fo + len(raw)] = raw

    def replace(self, old, new, limit=1):
        """Replace an exact byte string in BlamOS (default: require one hit)."""
        n = self.blob.count(old)
        if n != limit:
            raise ValueError(f"expected {limit} occurrence(s) of {old!r}, found {n}")
        off = self.blob.find(old)
        self.blob[off:off + len(old)] = new

    def version(self):
        m = _VERSION_RE.search(self.blob)
        return m.group()[:-1].decode() if m else None

    def rebuild(self):
        self.secs[self.si]["dec"] = bytes(self.blob)
        return repack.build(self.secs, self.orig)


def verify(data):
    """Return ``{digest_ok, sections_ok}`` for a container."""
    try:
        secs = repack.parse(data)
    except Exception:
        return {"digest_ok": False, "sections_ok": False}
    return {
        "digest_ok": data[:32] == hashlib.sha256(repack.PFX20 + data[32:]).digest(),
        "sections_ok": all(
            struct.unpack(">I", hashlib.sha256(repack.PFX20 + s["dec"]).digest()[:4])[0]
            == s["chk"]
            for s in secs
        ),
    }


def inspect(data):
    """Return identity/integrity information about an image."""
    info = {
        "stock": hashlib.sha256(data).hexdigest() == STOCK_SHA256,
        "version": None,
        "error": None,
    }
    info.update(verify(data))
    try:
        info["version"] = FirmwareImage(data).version()
    except Exception as e:  # noqa: BLE001 - surfaced to the UI
        info["error"] = str(e)
    return info


def build_patched(data, patch, **kwargs):
    """Apply a patch object to stock bytes and return verified container bytes."""
    if hashlib.sha256(data).hexdigest() != STOCK_SHA256:
        raise ValueError(
            "This is not the known stock Blackmagic Camera Setup 2.8.1 "
            "data-bd73.bin.\n\nExpected SHA-256:\n  " + STOCK_SHA256
        )
    img = FirmwareImage(data)
    patch.apply(img, **kwargs)
    out = img.rebuild()
    v = verify(out)
    if not (v["digest_ok"] and v["sections_ok"]):
        raise RuntimeError("rebuilt image failed integrity verification")
    return out


class CameraSetup:
    """Optional helper for the official updater executable.

    CameraSetup refuses to flash when the camera and package versions match.
    The patch flips the ``VisibleUSBCamera::isFirmwareCurrent`` result so the
    updater always offers/flashes the image.  A backup ``*.stock.exe`` is kept.
    """

    #: VA 0x4300C0 in Camera Setup 2.8.1, RVA = VA - image base (0x400000).
    FORCE_RVA = 0x300C0
    FORCE_OLD = bytes.fromhex("83790400 741a")  # cmp [ecx+4],0 ; je
    FORCE_NEW = bytes.fromhex("b801000000 c3")   # mov eax,1 ; ret

    @staticmethod
    def _rva_to_fo(data, rva):
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a valid PE executable")
        num = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        sec = opt + opt_size
        for i in range(num):
            o = sec + i * 40
            va = struct.unpack_from("<I", data, o + 12)[0]
            vsz = struct.unpack_from("<I", data, o + 8)[0]
            rsz = struct.unpack_from("<I", data, o + 16)[0]
            praw = struct.unpack_from("<I", data, o + 20)[0]
            if va <= rva < va + max(vsz, rsz):
                return praw + (rva - va)
        raise ValueError(f"RVA {rva:#x} is not mapped in the executable")

    @classmethod
    def is_patched(cls, path):
        data = open(path, "rb").read()
        fo = cls._rva_to_fo(data, cls.FORCE_RVA)
        return data[fo:fo + 6] == cls.FORCE_NEW

    @classmethod
    def patch(cls, path):
        data = bytearray(open(path, "rb").read())
        fo = cls._rva_to_fo(data, cls.FORCE_RVA)
        cur = bytes(data[fo:fo + 6])
        backup = path + ".stock.exe"
        if cur == cls.FORCE_NEW:
            return "already patched"
        if cur != cls.FORCE_OLD:
            raise ValueError(
                f"unexpected bytes at the update check ({cur.hex()}).\\n"
                "This helper targets Camera Setup 2.8.1.")
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        data[fo:fo + 6] = cls.FORCE_NEW
        open(path, "wb").write(data)
        return "patched"

    @classmethod
    def restore(cls, path):
        backup = path + ".stock.exe"
        if not os.path.exists(backup):
            raise ValueError(f"no backup found at {backup}")
        shutil.copy2(backup, path)
        return "restored"
