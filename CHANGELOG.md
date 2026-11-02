# Changelog

All notable changes to LIKAcs are documented here. Releases are built by
[`.github/workflows/release.yml`](.github/workflows/release.yml) and published at
<https://github.com/azyoff/LIKAcs/releases>. Website: <http://likaapps.com>.

## v1.0.0 - 2026-11-02

First production release.

- **Core:** Python 3.11 standard-library-only runtime; standalone Windows 10/11
  `.exe` builds via PyInstaller (unified `LIKAcs.exe`, `LIKAcs-ControlCenter.exe`,
  `LIKAcs-StationAgent.exe`). No Python/Node/SteamCMD needed on cafe PCs.
- **Safety:** 100% VAC-safe by design — official `.cfg` files, official launch
  parameters, official RCON (Source TCP for CS2, GoldSrc UDP challenge for
  CS 1.6), `steam://connect/`. No process memory access, no DLL injection,
  no binary patching, VAC never disabled. CI static guard enforces it.
- **Discovery:** HMAC-signed UDP broadcast heartbeats + directed broadcasts,
  stable station UUIDs, automatic DHCP-proof IP discovery, replay protection.
- **Multi-room:** unlimited simultaneous rooms with per-room host, port,
  RCON password, map, preset, editable rules, overtime toggle, and PC
  assignment (a PC belongs to exactly one room).
- **Smart join:** `lika`, `lika1`, `lika2`, `lika3` aliases, customizable join
  word, real-time `lika_join.cfg` rewriting while the game is open, `F10`
  one-key join that cleanly overrides CS 1.6's `quit prompt` bind.
- **Launch:** host matches with the already installed CS2 / CS 1.6 files,
  listen server by default (host PC plays), optional HLDS dedicated mode with
  an auto-launched local client. `Start & Connect Selected PCs` via official
  Steam URLs.
- **Rules:** `sv_lan 1`, `mp_freezetime 3`, `mp_friendlyfire 1`,
  `mp_autokick 0`, TK-ban protection off, `mp_autoteambalance 0`,
  `mp_limitteams 0`, `mp_forcecamera 1`, `bot_quota 0`, automatic warmup end,
  Wingman / Deathmatch / overtime handling.
- **Live controls:** Start/Stop Room, Knife Round, Swap Teams, LIVE! Restart,
  Pause/Unpause, End Warmup, Kick Bots, Change Map Live, Re-apply Rules,
  Disconnect / Return Selected PCs to Main Menu, Close Game.
- **Windows:** 1-Click Station Setup (drive-wide Steam detection, console
  enable, safe idempotent autoexec/userconfig hook with backup), LAN-only
  Defender Firewall rules with UAC elevation, silent auto-start, system tray
  icon with 127-char-safe live tooltip and full live status menu.
- **Updates:** GitHub Releases check, SHA-256 verified download, signed
  chunked LAN push to all stations, safe staged `.exe` swap + silent restart.
- **Branding:** clickable <http://likaapps.com> in header, footer, About, tray
  menu and README. MIT licensed, free & open-source worldwide.
