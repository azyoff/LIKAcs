# LIKAcs architecture

Website: <http://likaapps.com>

## Processes

| Process | Where | Responsibility |
|---|---|---|
| `LIKAcs-ControlCenter.exe` | Owner's laptop (few MB, no Steam) | Tkinter dashboard, room state, discovery listener, orchestration, updates, tray |
| `LIKAcs-StationAgent.exe` | Every gaming PC (few MB) | Heartbeats, signed HTTP API, cfg writer, official game launcher/RCON bridge, setup, tray, staged updates |
| `LIKAcs.exe` | Anywhere | **The only published exe.** First run: Setup wizard installs it per-user. Later runs: `--mode=control|station` or the chooser; one-click self-update via GitHub |
| `cs2.exe` / `hl.exe` / `hlds.exe` | Host gaming PC(s) | **Already installed** Steam game; acts as official LAN listen/dedicated server |

Both Control Center and Station Agent can run on the same PC. The laptop never
needs Steam, CS2 or CS 1.6 installed, and never downloads anything via
SteamCMD (zero extra 60 GB).

## Module map (`src/likacs/`)

```
__main__.py        CLI / mode chooser / headless setup & self-test
branding.py        likaapps.com strings, 127-char tray tooltip formatter
protocol.py        ports, message kinds, endpoint constants
config.py          Settings + thread-safe JSON store
state.py           Room model + RoomManager + StationLabels
security.py        HMAC-SHA256 signing, timestamp/nonce replay protection
util.py            paths, atomic writes, hashing, IP/broadcast discovery, versions
network.py         UDP broadcast DiscoveryService + StationTable
http_api.py        SignedClient + AgentHTTPServer (ThreadingHTTPServer)
cfgs.py            official .cfg writer (the smart lika join trick)
rules.py           presets, maps, official cvars, RCON command sets
paths.py           Steam library / drive / game path auto-detection
games.py           official launch argv, process registry, graceful shutdown
rcon.py            Source RCON (TCP) + GoldSrc RCON (UDP challenge) + status parser
steam.py           steam://connect/ and steam://rungameid/ helpers
setup_windows.py   one-click setup, netsh firewall, HKCU auto-start, UAC
installer.py       per-user Setup wizard engine, shortcuts, HKCU uninstall, manifest
runtime.py         DPI awareness, single-instance mutex, friendly logged errors
update.py          GitHub Releases check, verified download, LAN push, staged swap
selfupdate.py      latest.json manifest, verified one-click self-update, rollback swap
tray.py            Shell_NotifyIconW with ctypes (+ non-Windows NullTray)
agent.py           StationAgent service and API dispatch
control.py         ControlCenter orchestration and live controls
ui/                Tkinter theme, widgets, About, mode chooser, Setup wizard,
                   one-click update panel, both apps, GUI render smoke test
icon.py            generates a valid 32x32 .ico in memory (no Pillow)
selftest.py        headless protocol/safety smoke test
```

## Data flow

1. **Discovery** — every agent broadcasts a signed `hello` every 2 s to
   `255.255.255.255:27055` and every detected directed-broadcast address. The
   Control Center also broadcasts signed `probe` packets so quiet stations
   answer immediately. Source IP (not a configured static IP) is used to reach
   the agent. Stations expire after 9 s.
2. **Room start** — `ControlCenter.start_room()` sends `POST /launch-server` to
   the host agent. The agent writes `lika_match.cfg` and launches the installed
   game with official params (`-usercon`, `+rcon_password`, `+sv_lan 1`,
   `+map`, `+maxplayers`, `-port`, `+exec lika_match.cfg`). VAC stays enabled.
3. **Routing** — `refresh_join_configs()` sends `POST /configure-join` to every
   online agent with the PC's primary target plus up to 3 room targets. The
   agent rewrites `lika_join.cfg` / `lika_room1..3.cfg` atomically. Aliases use
   `exec`, which reads from disk at invocation time → real-time retargeting,
   even with the game already open.
4. **Live controls** — the laptop sends signed `POST /rcon` to the host agent;
   the agent executes official RCON against `127.0.0.1:<port>`. `status`
   output is parsed to kick players by LAN IP.
5. **Connect** — `POST /steam-connect` makes each selected agent open the
   official `steam://connect/<host>:<port>` URL locally.
6. **Updates** — one click: `latest.json` from GitHub Releases → SHA-256
   verify against manifest + `SHA256SUMS.txt` → boot-checked `.cmd` swap with
   automatic rollback → relaunch. Optionally the same verified exe is streamed
   to stations over the signed LAN (`/update-begin`, `/update-chunk`,
   `/update-finish`) and staged there with a `.cmd` helper.

## State files (`%APPDATA%\LIKAcs\` on Windows)

`settings.json`, `rooms.json`, `station-labels.json`, `station.json`,
`setup-report.json`, `firewall-report.json`, `pending-update.json`,
`updates/`. All writes are atomic (temp file + `os.replace`).

## Why no static IPs and no 60 GB download

Station IDs are stable random UUIDs stored on each PC; IPs come from the UDP
source address and are refreshed on every heartbeat. DHCP can change daily.
The server is the CS2/CS1.6 client already installed on a gaming PC — no
SteamCMD, no dedicated-server download, and the host PC's player can still
play (listen server, or HLDS + local client).
