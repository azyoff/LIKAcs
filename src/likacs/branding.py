"""Shared branding strings used by the UI, tray, configs and docs."""

from __future__ import annotations

from . import APP_NAME, VAC_PLEDGE, VERSION, WEBSITE, WEBSITE_LABEL

HEADER_TITLE = f"{APP_NAME}  |  LAN Server & Match Management Suite"
HEADER_SUBTITLE = "100% free & open-source  -  100% VAC-safe  -  CS2 + CS 1.6"
FOOTER = f"{APP_NAME} v{VERSION}  -  {WEBSITE}  -  Free & open-source for every internet cafe"
TRAY_PREFIX = f"{APP_NAME} ({WEBSITE_LABEL})"
CFG_HEADER = (
    f"// {APP_NAME} managed file - {WEBSITE}\n"
    f"// Generated automatically. Edit via the {APP_NAME} Control Center.\n"
    "// 100% VAC-safe: official config commands only. No cheats, no injection.\n"
)
ABOUT_TEXT = (
    f"{APP_NAME} v{VERSION}\n\n"
    f"{WEBSITE}\n\n"
    "A 100% free, open-source LAN Server & Match Management Suite built for\n"
    "Counter-Strike 2 and Counter-Strike 1.6 internet cafes of any size.\n\n"
    "Multiple simultaneous rooms, automatic LAN discovery, one-key join,\n"
    "live RCON cafe controls and one-click updates for all stations.\n\n"
    f"{VAC_PLEDGE}\n\n"
    "Windows 10 / Windows 11. No SteamCMD, no extra 60 GB download,\n"
    "no Steam installation required on the owner's laptop."
)


def fit_tray_tooltip(statuses: list[str], limit: int = 127) -> str:
    """Build a Windows tray tooltip while respecting the 127-character limit.

    Windows NOTIFYICONDATA.szTip holds 127 characters plus the NUL terminator.
    We keep the brand first, then append as many room statuses as fit, and
    always leave room for a hint that the full status is available on click.
    """
    hint = " | click for full status"
    base = TRAY_PREFIX
    if not statuses:
        text = base + " | idle"
        return text[:limit]
    out = base
    for index, status in enumerate(statuses):
        candidate = f"{out} | {status}" if out == base and index == 0 else f"{out} | {status}"
        if len(candidate) + len(hint) > limit:
            remaining = limit - len(out) - len(hint)
            if remaining > 4:
                out = out + " | +" + str(len(statuses) - index) + " more"
            return (out + hint)[:limit]
        out = candidate
    return out[:limit]
