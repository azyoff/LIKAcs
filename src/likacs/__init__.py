"""LIKAcs - free, open-source, VAC-safe LAN match management for CS2 / CS 1.6 cafes.

Website: http://likaapps.com

Design contract (see docs/ARCHITECTURE.md):
  * NO game process memory reads/writes, NO DLL injection, NO binary patching.
  * ONLY official .cfg files, official launch parameters, official RCON and
    Steam's official steam://connect/ protocol are used.
  * The runtime depends on the Python standard library ONLY. PyInstaller is
    used exclusively at build time to produce standalone Windows .exe files.
"""

from __future__ import annotations

APP_NAME = "LIKAcs"
PRODUCT_NAME = "LIKAcs - LAN Server & Match Management Suite"
WEBSITE = "http://likaapps.com"
WEBSITE_LABEL = "likaapps.com"
VERSION = "1.1.0"
BUILD_CHANNEL = "stable"

GITHUB_OWNER = "azyoff"
GITHUB_REPO = "LIKAcs"
GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
LICENSE_NAME = "MIT License"

SUPPORTED_GAMES = ("cs2", "cs16")
GAME_LABELS = {"cs2": "Counter-Strike 2", "cs16": "Counter-Strike 1.6"}

# Friendly reminder shown in the UI and in generated config files.
VAC_PLEDGE = (
    "100% VAC-safe: no memory access, no DLL injection, no game binary edits. "
    "Only official configs, launch parameters, RCON and steam://connect/."
)

__all__ = [
    "APP_NAME", "PRODUCT_NAME", "WEBSITE", "WEBSITE_LABEL", "VERSION",
    "BUILD_CHANNEL", "GITHUB_OWNER", "GITHUB_REPO", "GITHUB_URL",
    "LICENSE_NAME", "SUPPORTED_GAMES", "GAME_LABELS", "VAC_PLEDGE",
]
