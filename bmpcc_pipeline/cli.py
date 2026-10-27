"""Command-line interface for the BMPCC OG firmware patcher."""

import argparse
import os
import sys

from . import CameraSetup, PATCHES, build_patched, inspect


def _cmd_list(_args):
    for key, p in PATCHES.items():
        flag = " [experimental]" if p.experimental else ""
        print(f"{key:14s}{flag}\n    {p.name}\n    {p.description}\n")


def _cmd_build(args):
    data = open(args.stock, "rb").read()
    patch = PATCHES[args.patch]
    kwargs = {}
    if args.patch == "version-bump":
        kwargs["version"] = args.version
    out = build_patched(data, patch, **kwargs)
    open(args.output, "wb").write(out)
    info = inspect(out)
    print(f"patch    : {patch.name}")
    print(f"output   : {args.output} ({len(out)} bytes)")
    print(f"version  : {info['version']}")
    print(f"integrity: digest_ok={info['digest_ok']} "
          f"section_checksums_ok={info['sections_ok']}")
    print("\nNext: use the GUI, or copy this over the data-bd73.bin next to")
    print("CameraSetup.exe and run it (use 'camsetup-patch' for same-version images).")


def _cmd_verify(args):
    info = inspect(open(args.image, "rb").read())
    for k, v in info.items():
        print(f"{k}: {v}")
    return 0 if (info["digest_ok"] and info["sections_ok"]) else 2


def _cmd_camsetup_patch(args):
    print(CameraSetup.patch(args.exe))


def _cmd_camsetup_restore(args):
    print(CameraSetup.restore(args.exe))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bmpcc-pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list available patches")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("build", help="build a patched data-bd73.bin")
    p.add_argument("stock", help="stock data-bd73.bin (from Camera Setup 2.8.1)")
    p.add_argument("output", help="output file")
    p.add_argument("--patch", default="version-bump", choices=list(PATCHES))
    p.add_argument("--version", default="2.2", help="version string for version-bump")
    p.set_defaults(func=_cmd_build)

    p = sub.add_parser("verify", help="verify an image's integrity")
    p.add_argument("image")
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("camsetup-patch", help="allow CameraSetup to re-flash same version")
    p.add_argument("exe", help="path to CameraSetup.exe (2.8.1)")
    p.set_defaults(func=_cmd_camsetup_patch)

    p = sub.add_parser("camsetup-restore", help="restore CameraSetup from backup")
    p.add_argument("exe", help="path to CameraSetup.exe")
    p.set_defaults(func=_cmd_camsetup_restore)

    ns = ap.parse_args(argv)
    return ns.func(ns) or 0


if __name__ == "__main__":
    sys.exit(main())
