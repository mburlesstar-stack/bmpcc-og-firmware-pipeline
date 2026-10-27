# `data-bd73.bin` container format

All integers are **big-endian**. The file starts with a 32-byte digest, followed
by one or more section records.

```
0x00  digest[32]                 SHA-256(PFX20 || file[0x20:])
--- section record (header 0x30 bytes + zlib body) ---
+0x00  magic            'BDBD' (0xbd 0xbd)
+0x02  version          0x0001
+0x04  zero             0x00000000
+0x08  rem              0x30 + len(compressed body)   (offset to next record)
+0x0c  flags            0x00300100
+0x10  uncompressed size
+0x14  checksum         first 4 bytes of SHA-256(PFX20 || decompressed)
+0x18  const            0x00010018
+0x1c  reserved
+0x20  target class (2) + index (2)
+0x24  USB VID (2) + PID (2)     e.g. 1edb:bd73
+0x28  reserved[8]
+0x30  body             zlib stream (0x78 0xda ...)
```

The first record's magic sits at file offset `0x20` (after the 32-byte digest).

## Sections in `data-bd73.bin`

| # | class | index | uncompressed | content |
|---|-------|-------|--------------|---------|
| 0 | 0x0001 | 1 | ~10.9 MB | Xilinx Spartan-6 FPGA bitstream |
| 1 | 0x0402 | 1 | ~1.95 MB | BlamOS (big-endian MicroBlaze ELF) |

## Integrity (keyless)

`PFX20` is a constant 20-byte prefix found in `CameraSetup.exe`:

```
PFX20 = e6141730dd0a0c465941255d110f030545504239
```

* **File digest** (`0x00..0x1F`): `SHA-256(PFX20 || file[0x20:])`
* **Section checksum** (`header+0x14`): first 4 bytes of
  `SHA-256(PFX20 || decompressed_section)`

There is no signature, so a rebuilt image with recomputed digest/checksum is
accepted by the updater.

## ELF address mapping

The BlamOS section begins with a small prefix before the ELF magic
(`\x7fELF`). `bmpcc_pipeline.mbdis.Image` locates the ELF in the blob and maps
ELF program-header segments so patches can use **virtual addresses**:

```python
img.va2fo(0x487AB6B0)   # -> file offset in the BlamOS blob
```

The main code segment is `0x4879E400..0x4889B51C`.

## Recompression

`repack.build()` reuses the original compressed body for unchanged sections and
re-compresses only the edited one (`zlib.compress(..., 9)`). This changes the
compressed size/bytes but not the decompressed content, and all checksums are
recomputed.
