#!/usr/bin/env python3
"""Repackage a Blackmagic BMPCC-OG firmware payload (data-bd73.bin).

Container (all integers big-endian):
  0x00  digest[32]            SHA-256( PFX20 || data[0x20:] )
  --- section header (0x30 bytes) at the magic ---
  +0x00 magic 'BDBD' (2)  +0x02 version(2)=1  +0x04 zero(4)
  +0x08 rem(4)   = 0x30 + len(compressed body)
  +0x0c flags(4) +0x10 usize(4) = len(decompressed)
  +0x14 checksum(4) = first4( SHA-256( PFX20 || decompressed ) )
  +0x18 const 0x00010018  +0x1c reserved
  +0x20 target class(2)+index(2)  +0x24 vid(2)+pid(2)  +0x28 reserved[8]
  0x30  compressed body (zlib)

Sections follow each other back-to-back; the outer 32-byte digest is first.
"""
import hashlib
import struct
import sys
import zlib

PFX20 = bytes.fromhex("e6141730dd0a0c465941255d110f030545504239")
MAGIC = b"\xbd\xbd"


def parse(data):
    pos = 0x20
    secs = []
    while pos + 0x30 <= len(data) and data[pos:pos + 2] == MAGIC:
        hdr = data[pos:pos + 0x30]
        rem, flags, usize, chk, const = struct.unpack(">IIIII", hdr[0x08:0x1c])
        body = data[pos + 0x30:pos + rem]
        dec = zlib.decompress(body)
        secs.append({"off": pos, "hdr": hdr, "rem": rem, "flags": flags,
                     "usize": usize, "chk": chk, "body": body, "dec": dec})
        pos += rem
    return secs


def build(sections, orig):
    """sections: list of dicts with 'hdr' (template) and 'dec' (decompressed bytes).
    Reuses each section's original compressed body if the decompressed bytes are unchanged."""
    out_sections = []
    for i, s in enumerate(sections):
        hdr = bytearray(s["hdr"])
        dec = s["dec"]
        o = orig[i]
        if dec == o["dec"]:
            body = o["body"]
        else:
            body = zlib.compress(dec, 9)
        chk = struct.unpack(">I", hashlib.sha256(PFX20 + dec).digest()[:4])[0]
        rem = 0x30 + len(body)
        struct.pack_into(">I", hdr, 0x08, rem)
        struct.pack_into(">I", hdr, 0x10, len(dec))
        struct.pack_into(">I", hdr, 0x14, chk)
        out_sections.append(bytes(hdr) + body)
    blob = b"".join(out_sections)
    digest = hashlib.sha256(PFX20 + blob).digest()
    return digest + blob


def main():
    if len(sys.argv) < 3:
        print("usage: repack.py <original.bin> <out.bin> [sec_index=newfile ...]")
        return 1
    orig_path, out_path = sys.argv[1], sys.argv[2]
    data = open(orig_path, "rb").read()
    orig = parse(data)
    secs = [{"hdr": s["hdr"], "dec": s["dec"]} for s in orig]
    for arg in sys.argv[3:]:
        idx, path = arg.split("=", 1)
        secs[int(idx)]["dec"] = open(path, "rb").read()
    rebuilt = build(secs, orig)
    open(out_path, "wb").write(rebuilt)
    ok = rebuilt[:32] == hashlib.sha256(PFX20 + rebuilt[32:]).digest()
    print(f"wrote {out_path} ({len(rebuilt)} bytes) digest_ok={ok}")
    for i, s in enumerate(parse(rebuilt)):
        good = struct.unpack(">I", hashlib.sha256(PFX20 + s["dec"]).digest()[:4])[0] == s["chk"]
        print(f"  sec{i}: rem={s['rem']:#x} usize={s['usize']:#x} chk={s['chk']:#010x} chk_ok={good}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
