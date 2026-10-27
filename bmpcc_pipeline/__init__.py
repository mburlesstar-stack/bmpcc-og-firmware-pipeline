"""BMPCC OG (original Pocket Cinema Camera) firmware patching pipeline."""

from .patcher import (
    STOCK_SHA256,
    FirmwareImage,
    CameraSetup,
    build_patched,
    inspect,
    verify,
)
from .patches import PATCHES, get_patch

__all__ = [
    "STOCK_SHA256",
    "FirmwareImage",
    "CameraSetup",
    "build_patched",
    "inspect",
    "verify",
    "PATCHES",
    "get_patch",
]

__version__ = "1.0.0"
