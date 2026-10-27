#!/usr/bin/env python3
"""Minimal MicroBlaze disassembler for Blackmagic BlamOS images.

Built from the project's Ghidra SLEIGH spec (microblaze/data/languages/mb_be.sinc).
Supports big- and little-endian ELF images (including the 12-byte prefix used in
the data-*.bin section payloads) and resolves the IMM-prefix idiom used to build
32-bit constants.

Usage:
    python tools/mbdis.py <data-XXXX.bin|blamos.elf> <va> <count> [--le]
    python tools/mbdis.py <image> --find <hex32> [--le]     # locate a constant load
    python tools/mbdis.py <image> --func <va> [--le]        # linear function dump

Examples:
    python tools/mbdis.py data-bd73.bin 0x48836b20 40
    python tools/mbdis.py data-bd89.bin --find 0xC4400C84
"""
import argparse
import struct
import sys
import zlib

MAGIC = b"\xbd\xbd"
REGS = [f"r{i}" for i in range(32)]


# --------------------------------------------------------------------------- #
# image handling
# --------------------------------------------------------------------------- #
def parse_sections(data):
    pos, secs = 0x20, []
    while pos + 0x30 <= len(data) and data[pos:pos + 2] == MAGIC:
        hdr = data[pos:pos + 0x30]
        rem = struct.unpack(">I", hdr[0x08:0x0c])[0]
        try:
            dec = zlib.decompress(data[pos + 0x30:pos + rem])
        except Exception:
            dec = b""
        secs.append(dec)
        pos += rem
    return secs


class Image:
    def __init__(self, blob):
        self.b = blob
        self.segs = []
        self.end = None
        e = blob.find(b"\x7fELF")
        if e >= 0:
            try:
                end = "<" if blob[e + 5] == 1 else ">"
                phoff = struct.unpack(end + "I", blob[e + 0x1c:e + 0x20])[0]
                phentsize, phnum = struct.unpack(end + "HH", blob[e + 0x2a:e + 0x2e])
                if phnum > 16 or phentsize != 32:
                    return
                segs = []
                for i in range(phnum):
                    o = e + phoff + i * phentsize
                    if o + 24 > len(blob):
                        return
                    p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz = \
                        struct.unpack(end + "IIIIII", blob[o:o + 24])
                    if p_type == 1 and p_filesz and e + p_offset + p_filesz <= len(blob):
                        segs.append((e + p_offset, p_vaddr, p_filesz))
                if segs:
                    self.segs = segs
                    self.end = end
            except Exception:
                self.segs = []
                self.end = None

    def va2fo(self, va):
        for off, v, sz in self.segs:
            if v <= va < v + sz:
                return off + (va - v)
        return None

    def fo2va(self, fo):
        for off, v, sz in self.segs:
            if off <= fo < off + sz:
                return v + (fo - off)
        return None

    def read32(self, va, end):
        fo = self.va2fo(va)
        if fo is None or fo + 4 > len(self.b):
            return None
        return struct.unpack(end + "I", self.b[fo:fo + 4])[0]


def load_image(path, want_le=False):
    data = open(path, "rb").read()
    if b"\x7fELF" in data[:16]:
        blobs = [data]
    else:
        blobs = parse_sections(data)
    best = None
    for bl in blobs:
        img = Image(bl)
        if img.segs:
            # prefer the largest mapped image (BlamOS), skip tiny stub ELFs
            size = sum(sz for _, _, sz in img.segs)
            if best is None or size > best[0]:
                best = (size, img)
    if best is None:
        raise SystemExit("no ELF image found")
    img = best[1]
    end = "<" if want_le else (img.end or ">")
    return img, end


# --------------------------------------------------------------------------- #
# decoder
# --------------------------------------------------------------------------- #
def sx16(v):
    return v - 0x10000 if v & 0x8000 else v


def decode(word, immhi, pc):
    """Return dict(text, kind, target, sets_imm). kind: 'imm','branch','call','ret','other'."""
    op = (word >> 26) & 0x3F
    rD = (word >> 21) & 0x1F
    rA = (word >> 16) & 0x1F
    rB = (word >> 11) & 0x1F
    imm = word & 0xFFFF
    cd10 = word & 0x7FF
    cd1620 = (word >> 16) & 0x1F
    cd2125 = (word >> 21) & 0x1F
    immval = ((immhi << 16) | imm) & 0xFFFFFFFF if immhi is not None else (sx16(imm) & 0xFFFFFFFF)
    rd, ra, rb = REGS[rD], REGS[rA], REGS[rB]
    d = {"kind": "other", "target": None, "sets_imm": None, "text": ""}

    def imm3():
        return f"0x{immval:x}" if immhi is not None else f"{sx16(imm)}"

    if op == 0x2C:                                   # imm
        d["text"] = f"imm     0x{imm:x}"
        d["sets_imm"] = imm                          # raw; decode() shifts once
        d["kind"] = "imm"
        return d
    if op == 0x00: d["text"] = f"add     {rd}, {ra}, {rb}"
    elif op == 0x01: d["text"] = f"rsub    {rd}, {ra}, {rb}"
    elif op == 0x04: d["text"] = f"addk    {rd}, {ra}, {rb}"
    elif op == 0x05:
        if cd10 == 0: d["text"] = f"rsubk   {rd}, {ra}, {rb}"
        elif cd10 == 1: d["text"] = f"cmp     {rd}, {ra}, {rb}"
        elif cd10 == 3: d["text"] = f"cmpu    {rd}, {ra}, {rb}"
        else: d["text"] = f"rsubk   {rd}, {ra}, {rb}"
    elif op == 0x08: d["text"] = f"addi    {rd}, {ra}, {imm3()}"
    elif op == 0x09: d["text"] = f"rsubi   {rd}, {ra}, {imm3()}"
    elif op == 0x0C: d["text"] = f"addik   {rd}, {ra}, {imm3()}"
    elif op == 0x0D: d["text"] = f"rsubik  {rd}, {ra}, {imm3()}"
    elif op == 0x10: d["text"] = f"mul     {rd}, {ra}, {rb}"
    elif op == 0x11:
        if cd10 == 0: d["text"] = f"bsrl    {rd}, {ra}, {rb}"
        elif cd10 == 0x400: d["text"] = f"bsra    {rd}, {ra}, {rb}"
        elif cd10 == 0x800: d["text"] = f"bsll    {rd}, {ra}, {rb}"
        else: d["text"] = f"bsr?    {rd}, {ra}, {rb}"
    elif op == 0x18: d["text"] = f"muli    {rd}, {ra}, {imm3()}"
    elif op == 0x19:
        sub = (word >> 5) & 0x3F
        sh = word & 0x1F
        if sub == 0x00: d["text"] = f"bsrli   {rd}, {ra}, {sh}"
        elif sub == 0x10: d["text"] = f"bsrai   {rd}, {ra}, {sh}"
        elif sub == 0x20: d["text"] = f"bslli   {rd}, {ra}, {sh}"
        else: d["text"] = f"bs?i    {rd}, {ra}, {sh}"
    elif op == 0x20: d["text"] = f"or      {rd}, {ra}, {rb}"
    elif op == 0x21: d["text"] = f"and     {rd}, {ra}, {rb}"
    elif op == 0x22: d["text"] = f"xor     {rd}, {ra}, {rb}"
    elif op == 0x23: d["text"] = f"andn    {rd}, {ra}, {rb}"
    elif op == 0x28: d["text"] = f"ori     {rd}, {ra}, {imm3()}"
    elif op == 0x29: d["text"] = f"andi    {rd}, {ra}, {imm3()}"
    elif op == 0x2A: d["text"] = f"xori    {rd}, {ra}, {imm3()}"
    elif op == 0x2B: d["text"] = f"andni   {rd}, {ra}, {imm3()}"
    elif op == 0x30: d["text"] = f"lbu     {rd}, {ra}, {rb}"
    elif op == 0x31: d["text"] = f"lhu     {rd}, {ra}, {rb}"
    elif op == 0x32: d["text"] = f"lw      {rd}, {ra}, {rb}"
    elif op == 0x34: d["text"] = f"sb      {rd}, {ra}, {rb}"
    elif op == 0x35: d["text"] = f"sh      {rd}, {ra}, {rb}"
    elif op == 0x36: d["text"] = f"sw      {rd}, {ra}, {rb}"
    elif op == 0x38: d["text"] = f"lbui    {rd}, {ra}, {imm3()}"
    elif op == 0x39: d["text"] = f"lhui    {rd}, {ra}, {imm3()}"
    elif op == 0x3A: d["text"] = f"lwi     {rd}, {ra}, {imm3()}"
    elif op == 0x3C: d["text"] = f"sbi     {rd}, {ra}, {imm3()}"
    elif op == 0x3D: d["text"] = f"shi     {rd}, {ra}, {imm3()}"
    elif op == 0x3E: d["text"] = f"swi     {rd}, {ra}, {imm3()}"
    elif op == 0x2D:                                 # rtsd/rtid/rtbd/rted
        kind = {0x10: "rtsd", 0x11: "rtid", 0x12: "rtbd", 0x14: "rted"}.get(cd2125, "rt?d")
        d["text"] = f"{kind}    {ra}, {imm3()}"
        d["kind"] = "ret"
    elif op == 0x2E:                                 # bri family
        if cd2125 == 0 and cd1620 == 0x02:
            d["text"] = f"mbar    {cd2125}"
        elif cd2125 == 0 and cd1620 == 0x00:
            tgt = (pc + immval) & 0xFFFFFFFF
            d["text"] = f"bri     0x{tgt:08x}"
            d["kind"], d["target"] = "branch", tgt
        elif cd1620 == 0x10:
            tgt = (pc + immval) & 0xFFFFFFFF
            d["text"] = f"brid    0x{tgt:08x}"
            d["kind"], d["target"] = "branch", tgt
        elif cd1620 == 0x14:
            tgt = (pc + immval) & 0xFFFFFFFF
            d["text"] = f"brlid   {rd}, 0x{tgt:08x}"
            d["kind"], d["target"] = "call", tgt
        elif cd1620 == 0x08:
            tgt = immval
            d["text"] = f"brai    0x{tgt:08x}"
            d["kind"], d["target"] = "branch", tgt
        elif cd1620 == 0x18:
            tgt = immval
            d["text"] = f"braid   0x{tgt:08x}"
            d["kind"], d["target"] = "branch", tgt
        elif cd1620 == 0x1C:
            tgt = immval
            d["text"] = f"bralid  {rd}, 0x{tgt:08x}"
            d["kind"], d["target"] = "call", tgt
        elif cd1620 == 0x0C:
            tgt = immval
            d["text"] = f"brki    {rd}, 0x{tgt:08x}"
            d["kind"], d["target"] = "branch", tgt
        else:
            d["text"] = f"br?     {word:08x}"
    elif op == 0x2F:                                 # beqi family
        names = {0x00: "beqi", 0x01: "bnei", 0x02: "blti", 0x03: "blei",
                 0x04: "bgti", 0x05: "bgei", 0x10: "beqid", 0x11: "bneid",
                 0x12: "bltid", 0x13: "bleid", 0x14: "bgtid", 0x15: "bgeid"}
        nm = names.get(cd2125, "b??i")
        tgt = (pc + immval) & 0xFFFFFFFF
        d["text"] = f"{nm:<7} {ra}, 0x{tgt:08x}"
        d["kind"], d["target"] = "branch", tgt
    elif op == 0x26:                                 # br/bra register
        d["text"] = f"br*     {rb} / {rd}"
        d["kind"] = "branch"
    elif op == 0x27:                                 # beq/bne register
        d["text"] = f"bcc     {ra}, {rb}"
        d["kind"] = "branch"
    elif op == 0x25:
        d["text"] = f"mfs/mts {rd}, {ra}"
    elif op == 0x24:
        d["text"] = f"alu     {rd}, {ra}"
    else:
        d["text"] = f".word   0x{word:08x}"
    return d


def disasm(img, end, start, count, stop_at=None):
    va = start
    immhi = None
    out = []
    for _ in range(count):
        word = img.read32(va, end)
        if word is None:
            out.append((va, None, "<out of range>", None, None))
            break
        d = decode(word, immhi, va)
        out.append((va, word, d["text"], d["kind"], d["target"]))
        if d["sets_imm"] is not None:
            immhi = d["sets_imm"]
        else:
            immhi = None
        va += 4
        if stop_at is not None and d["kind"] == "ret" and va >= stop_at:
            break
    return out


def find_constant(img, end, value):
    """Find instruction sites that materialise `value` via imm + ori/addik/addi/muli."""
    hi = (value >> 16) & 0xFFFF
    lo = value & 0xFFFF
    hits = []
    for off, va, sz in img.segs:
        endfo = off + sz
        for fo in range(off, endfo - 8, 4):
            w1 = struct.unpack(end + "I", img.b[fo:fo + 4])[0]
            if ((w1 >> 26) & 0x3F) != 0x2C or (w1 & 0xFFFF) != hi:
                continue
            w2 = struct.unpack(end + "I", img.b[fo + 4:fo + 8])[0]
            op = (w2 >> 26) & 0x3F
            if op in (0x28, 0x0C, 0x08, 0x18) and (w2 & 0xFFFF) == lo:
                hits.append(img.fo2va(fo))
    return hits


def func_cfg(img, end, start, window=0x8000, maxins=3000):
    """Recursive traversal of a function; returns {va: (word, decoded)}."""
    seen = {}
    work = [start]
    hi_bound = start + window
    while work and len(seen) < maxins:
        va = work.pop()
        immhi = None
        while True:
            if va in seen or len(seen) >= maxins:
                break
            if va < start or va > hi_bound:
                break
            word = img.read32(va, end)
            if word is None:
                break
            d = decode(word, immhi, va)
            seen[va] = (word, d)
            nxt = va + 4
            if d["sets_imm"] is not None:
                immhi = d["sets_imm"]
                va = nxt
                continue
            immhi = None
            if d["kind"] == "ret":
                break
            if d["kind"] == "branch":
                if d["target"] is not None and start <= d["target"] <= hi_bound:
                    work.append(d["target"])
                work.append(nxt)
                break
            if d["kind"] == "call":
                work.append(nxt)
                break
            va = nxt
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--le", action="store_true")
    ap.add_argument("--find")
    ap.add_argument("--func")
    ap.add_argument("--window", default="0x8000")
    ns = ap.parse_args()

    img, end = load_image(ns.image, ns.le)
    if ns.find:
        val = int(ns.find, 0)
        print(f"# constant 0x{val:08x} load sites:")
        for va in find_constant(img, end, val):
            print(f"  {va:#010x}")
        return 0

    if ns.func:
        start = int(ns.func, 0)
        seen = func_cfg(img, end, start, window=int(ns.window, 0))
        for va in sorted(seen):
            word, d = seen[va]
            print(f"{va:08x}  {word:08x}  {d['text']}")
        return 0

    if len(ns.args) < 2:
        ap.error("need <va> <count>")
    start = int(ns.args[0], 0)
    count = int(ns.args[1], 0)
    for va, word, text, kind, target in disasm(img, end, start, count):
        w = f"{word:08x}" if word is not None else "????????"
        print(f"{va:08x}  {w}  {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
