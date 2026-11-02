# LIKAcs

**100% free & open-source • 100% VAC-safe • Windows 10 / Windows 11 • CS2 + Counter-Strike 1.6 LAN Server & Match Management Suite for internet cafes of any size**

> Official website: **[likaapps.com](http://likaapps.com)** — <http://likaapps.com>  
> Source & releases: <https://github.com/azyoff/LIKAcs>

LIKAcs turns any LAN switch (2 PCs → 50+ PCs) into a cafe match-management system. Run several rooms at the same time, route every PC to *its own* room with one word or one key, and control live matches from the owner's laptop — **without SteamCMD, without a 60 GB extra download, and without touching game memory**.

| | |
|---|---|
| Games | Counter-Strike 2 (`cs2.exe`) and Counter-Strike 1.6 (`hl.exe` / `hlds.exe`) |
| Presets | `1vs1`, `2vs2`, `2vs3`, `3vs3`, `4vs4`, `5vs5`, `Wingman (2vs2 half-map)`, `Deathmatch / Warmup`, `Custom` |
| Maps | `de_dust2` (default), `de_mirage`, `de_inferno`, `de_nuke`, `de_anubis`, `de_ancient`, `de_vertigo`, `de_train` + CS 1.6 classics `fy_snow`, `aim_map`, `de_aztec`, `cs_assault` + any custom map name |
| Host | The **already installed** Steam game on a gaming PC. The player sitting at the host PC can play too. |
| Laptop | Lightweight remote Control Center — a few MB, **no Steam, no CS2 install, no Python, no Node** required. The same Control Panel can also be opened directly on PC 1 / PC 2 / any gaming PC. |
| Updates | GitHub Releases → laptop downloads & SHA-256 verifies → one-click push to every LAN Station PC |

---

## Contents

1. [The 100% VAC-safe promise](#the-100-vac-safe-promise)
2. [Architecture](#architecture)
3. [Quick start for a cafe](#quick-start-for-a-cafe)
4. [1-Click Station Setup](#1-click-station-setup)
5. [Multiple simultaneous rooms](#multiple-simultaneous-rooms)
6. [Smart `lika` join and F10](#smart-lika-join-and-f10)
7. [Cafe rules & live controls](#cafe-rules--live-controls)
8. [System tray, tooltip and auto-start](#system-tray-tooltip-and-auto-start)
9. [Start & Connect Selected PCs](#start--connect-selected-pcs)
10. [Updates: GitHub → laptop → all cafe PCs](#updates-github--laptop--all-cafe-pcs)
11. [Standalone .exe and GitHub Actions](#standalone-exe-and-github-actions)
12. [Ports, firewall & LAN keys](#ports-firewall--lan-keys)
13. [Troubleshooting](#troubleshooting)
14. [Development](#development)
15. [License](#license)

---

## The 100% VAC-safe promise

LIKAcs contains **zero cheats** and uses **only first-party mechanisms**:

✅ official config files (`autoexec.cfg` + `exec lika_autoexec.cfg` for CS2, `userconfig.cfg` for CS 1.6, plus dynamically rewritten `lika_join.cfg` / `lika_room1..3.cfg` / `lika_match.cfg`)  
✅ official launch parameters (`-usercon`, `+rcon_password`, `+sv_lan 1`, `+map`, `+maxplayers`, `-port`, `+exec`)  
✅ official RCON (Source RCON over TCP for CS2, GoldSrc UDP challenge RCON for CS 1.6)  
✅ official `steam://connect/<host_ip>:<port>` and `steam://rungameid/...` protocol  
✅ ordinary OS process start/stop (graceful `WM_CLOSE`, then `taskkill`)

❌ **never** reads or writes game process memory  
❌ **never** injects a DLL, hooks the engine or simulates cheats  
❌ **never** modifies game binaries, and **never disables VAC** (no `-insecure`)  
❌ **never** overwrites a player's crosshair, mouse sensitivity or other keybinds — only an explicitly-visible `exec` hook line and the `F10` bind are added

A CI guard ([`scripts/verify_vac_safety.py`](scripts/verify_vac_safety.py)) scans the real code tokens (comments/strings stripped) and **fails any build** if memory APIs, injection or binary patching appear. See [`docs/VAC_SAFETY.md`](docs/VAC_SAFETY.md).

---

## Architecture

```mermaid
flowchart LR
  L["Owner's workspace laptop<br/>LIKAcs.exe --mode=control<br/>Tkinter dashboard + tray"]
  subgraph LAN["One LAN switch (DHCP IPs may change daily)"]
    A1["PC 1 - Station Agent<br/>HOST Room 1 (2vs2)"]
    A2["PC 2 - Station Agent"]
    A3["PC 3 - Station Agent"]
    A4["PC 4 - Station Agent"]
    A5["PC 5 - Station Agent<br/>HOST Room 2 (1vs1)"]
    A6["PC 6 - Station Agent"]
  end
  L -. "UDP broadcast discovery (signed)" .-> LAN
  LAN -. "heartbeats: id, IP, rooms, servers" .-> L
  L == "signed HTTPS-like JSON over LAN TCP" ==> A1
  L == "signed JSON: setup / join cfg / launch / RCON / update" ==> A5
  A1 -->|"cs2.exe +sv_lan 1 -usercon"| S1["CS2 listen server<br/>27015"]
  A5 -->|"cs2.exe +sv_lan 1 -usercon"| S2["CS2 listen server<br/>27016"]
  A2 & A3 & A4 -->|"steam://connect/PC1:27015"| S1
  A6 -->|"steam://connect/PC5:27016"| S2
```

| Layer | Implementation |
|---|---|
| Runtime | **Python 3.11 standard library only** (`tkinter`, `socket`, `http.server`, `urllib`, `ctypes`, `winreg`). Zero third-party runtime dependencies. |
| Discovery | UDP broadcast / directed-broadcast heartbeats on port `27055`, every 2 s. HMAC-signed, replay-protected. Station IDs are stable UUIDs — DHCP changes are irrelevant. |
| Control | Signed HTTP/JSON API on each Station Agent (`27056`). Every request has a timestamp, nonce and HMAC-SHA256 signature over the body. |
| Rooms | Persisted in `%APPDATA%\LIKAcs\rooms.json`; per-room host, PCs, preset, map, rules, port, RCON password, state. |
| Join routing | `alias lika "exec lika_join.cfg"` — `exec` reads the tiny target file **from disk at the moment the alias is used**, so retargeting works **even while CS2 / CS 1.6 is open**. |
| Tray | `Shell_NotifyIconW` via `ctypes` — no `pystray`/Pillow dependency; the icon is generated in memory. |
| Build | PyInstaller in GitHub Actions → `LIKAcs.exe`, `LIKAcs-ControlCenter.exe`, `LIKAcs-StationAgent.exe` + `SHA256SUMS.txt` attached to every Release. |

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CFG_REFERENCE.md`](docs/CFG_REFERENCE.md), [`docs/PORTS.md`](docs/PORTS.md).

---

## Quick start for a cafe

1. **Download [`LIKAcs.exe`](https://github.com/azyoff/LIKAcs/releases/latest)** — the one file for everything (or build it yourself, see below). No installer, no Python, no SteamCMD.
2. **Laptop / owner desk:** run `LIKAcs.exe` → **"Open Control Center"**. No Steam or CS installation is needed here.
3. **Every gaming PC:** copy the *same* `LIKAcs.exe`, run it → **"Start Station Agent"**. It minimizes to the tray.
4. On each gaming PC click **1-Click Station Setup**. Then click **Firewall Rules (UAC)** once and accept the Windows UAC prompt (or use the laptop's **Station PCs** tab to do all of them). Optionally enable **Auto-start ON** so the agent starts silently with Windows.
5. In the Control Center, wait a few seconds — PCs appear automatically in **Station PCs** with their current DHCP IPs. Rename them to `PC 1`, `PC 2`, ... if you like.
6. In **Rooms & Matches**, create a room, choose game / preset / map / Host PC, tick the PCs in the checklist, click **Apply PC assignment**, then **Start Room**.
7. On each assigned PC: press <code>`</code> → type `lika` → Enter, **or just press `F10`**. Alternatively tick the PCs on the laptop and click **Start & Connect Selected PCs**.

> Want the Control Panel on a gaming PC instead of a laptop? Just run `LIKAcs.exe` there too and pick **Open Control Center** — both roles can run on the same machine.

---

## 1-Click Station Setup

`LIKAcs` auto-detects Steam libraries on **C:, D:, E:, ...** by parsing the official `steamapps/libraryfolders.vdf`, plus common install locations. It locates:

* CS2: `...\Counter-Strike Global Offensive\game\bin\win64\cs2.exe` and `game\csgo\cfg\`
* CS 1.6: `...\Half-Life\hl.exe`, `hlds.exe` and `cstrike\cfg\`

Then it:

1. Enables the developer console with the official cvar (`con_enable 1` for CS2, `console 1` for CS 1.6).
2. Creates a timestamped backup of `autoexec.cfg` / `userconfig.cfg` before the **first** modification.
3. Appends a clearly delimited 3-line managed block containing `exec lika_autoexec.cfg` — **idempotently** (running setup again never duplicates it) and without deleting any existing line.
4. Writes `lika_autoexec.cfg` (aliases + F10 bind), `lika_join.cfg`, `lika_room1..3.cfg` and `lika_match.cfg`.
5. Optionally adds **LAN-only** Windows Defender Firewall allow rules (`remoteip=localsubnet`) for CS2, CS 1.6, the agent and the LIKAcs ports, and optionally registers silent auto-start in `HKCU\...\Run`.

Manual paths (non-Steam installs, unusual drives) can be set in `settings.json` → `game_paths`.

---

## Multiple simultaneous rooms

Rooms are independent: each has its own host PC, port, RCON password, rules, map and PC assignment. Different hosts can even use the same game port (different IPs); LIKAcs still allocates `27015`, `27016`, ... to keep everything unambiguous.

**Example** — Room 1: `2vs2` on PC 1–4 hosted by PC 1, Room 2: `1vs1` on PC 5–6 hosted by PC 5, at the same time on the same switch:

| PC | `lika_join.cfg` | `lika1` | `lika2` |
|---|---|---|---|
| PC 1 (host 1) | `connect <PC1-IP>:27015` | Room 1 | Room 2 |
| PC 2, 3, 4 | `connect <PC1-IP>:27015` | Room 1 | Room 2 |
| PC 5 (host 2) | `connect <PC5-IP>:27016` | Room 1 | Room 2 |
| PC 6 | `connect <PC5-IP>:27016` | Room 1 | Room 2 |

A PC can only be assigned to one room; assigning it elsewhere removes it from the old room and immediately rewrites its cfg files. The host PC is always included in its own room (the host can play).

---

## Smart `lika` join and F10

```
autoexec.cfg (CS2) / userconfig.cfg (CS 1.6)
  └─ exec lika_autoexec.cfg
       ├─ alias "lika"  "exec lika_join.cfg"       ← typed word / F10
       ├─ alias "lika1" "exec lika_room1.cfg"      ← specific rooms
       ├─ alias "lika2" "exec lika_room2.cfg"
       ├─ alias "lika3" "exec lika_room3.cfg"
       ├─ unbind "F10" ; bind "F10" "lika"
       └─ con_enable 1 / console 1
lika_join.cfg  →  connect <assigned_host_ip>:<port>
```

Because `exec` reads the file **at invocation time**, the agent only rewrites `lika_join.cfg` (or `lika_roomN.cfg`) on disk — no game restart, no console command injection, no input simulation. CS 1.6's default `F10` is simply `bind "F10" "quit prompt"` in `config.cfg`, and `userconfig.cfg` is exec'd last, so our rebind cleanly replaces it. Change the join word or the key in **Settings** → **Save & Sync to All Station PCs**; `lika` always stays available as the default.

---

## Cafe rules & live controls

Pre-loaded, editable **per room** in the **Cafe Rules** tab:

| cvar | Value | Why |
|---|---|---|
| `sv_lan` | `1` | 100% local LAN switch traffic, ~1 ms ping, no Steam friends needed |
| `mp_freezetime` | `3` | short freeze |
| `mp_friendlyfire` | `1` | classic cafe rules |
| `mp_autokick` / `mp_tkpunish` | `0` | teammates never get auto-kicked / TK-banned |
| `mp_autoteambalance` | `0` | no forced team moves |
| `mp_limitteams` | `0` | uneven `2vs3` always works |
| `mp_forcecamera` | `1` | anti-ghosting: dead players spectate teammates only |
| `bot_quota` | `0` | no bots steal player slots |
| — | `mp_warmup_end` | automatic once the room is ready |
| — | Overtime ON/OFF | `mp_overtime_enable` / `mp_maxrounds` on CS2 |

Extra game-specific cvars (buy time, round time, halftime, max rounds, `mp_forcechasecam 2` on CS 1.6, Wingman `game_mode 2`, Deathmatch respawns...) are generated automatically. You can add any official cvar in the Rules tab.

**Live remote controls from the laptop** (official RCON through the host agent):

`Start Room` · `Stop Room` · **Knife Round → Swap Teams → LIVE! Restart Match (0-0)** · `Pause Match` / `Unpause Match` · `End Warmup` · `Kick Bots` · `Change Map Live` · `Re-apply Room Rules` · `Restart Round` · `Disconnect / Return Selected PCs to Main Menu` (RCON `kickid` / `kick #` by LAN IP parsed from `status`) · `Close Game` (graceful process shutdown).

> CS 1.6 notes: vanilla HLDS may need AMX Mod X for `mp_swapteams`; there is no `mp_warmup_end`, so "End Warmup" restarts the round. LIKAcs reports any unknown RCON command back in the UI instead of pretending it worked.

---

## System tray, tooltip and auto-start

Both the Control Center and the Station Agent minimize cleanly to the Windows 10/11 notification area (closing the window = minimize; **Exit** is in the tray menu). Hovering shows a **live** tooltip, e.g.:

```
LIKAcs (likaapps.com) | Room 1: 2vs2 playing | Room 2: 1vs1 playing | click for full status
```

Windows caps `NOTIFYICONDATA.szTip` at **127 characters**; `fit_tray_tooltip()` truncates gracefully and adds `+N more`. A **right-click** (or left-click for the window) shows the full live status menu with every active room, station count, a clickable **[likaapps.com](http://likaapps.com)** item, About, Check for Updates and Exit. Enable **Auto-start ON** for silent boot (`--mode=station --silent`).

---

## Start & Connect Selected PCs

Tick `[x] PC 1  [x] PC 2 ...` and click **Start & Connect Selected PCs**. The laptop sends a signed command to each selected Station Agent, which locally opens the official Steam URLs:

```
steam://rungameid/730            (CS2)      steam://rungameid/10   (CS 1.6)
steam://connect/<host_ip>:<port>
```

For CS 1.6 there is also an optional fallback using the official `hl.exe -game cstrike +connect <ip>:<port>` launch parameter if the Steam URL handler is unavailable. No keystrokes are simulated and no game process memory is touched.

---

## Updates: GitHub → laptop → all cafe PCs

1. Tag a release (`v1.0.2`) — [`.github/workflows/release.yml`](.github/workflows/release.yml) builds the `.exe`s, renders all four windows against a real Tk root (from source **and** inside the built `.exe`), and publishes `LIKAcs.exe` + `SHA256SUMS.txt`.
2. In the laptop's **Updates** tab click **Check for Updates** (GitHub Releases API), then **Download & Verify .exe** (SHA-256 checked against the release digest / `SHA256SUMS.txt`).
3. Click **Push Update to ALL Station PCs**. The binary is streamed in signed 512 KiB chunks to every discovered agent; each agent re-verifies the hash and size before staging.
4. Windows cannot overwrite a running `.exe`, so the agent writes a small `.cmd` helper that waits for the process to exit, swaps the file and restarts the agent silently (tick **Restart Station Agents after push**). Games keep running; nothing is interrupted mid-match.

See [`docs/UPDATE_FLOW.md`](docs/UPDATE_FLOW.md).

---

## Standalone .exe and GitHub Actions

**GitHub Releases publish only `LIKAcs.exe`** — one file for everything. Windows 10/11, 64-bit, no Python/Node needed, no installer wizard.

| File | Purpose |
|---|---|
| `LIKAcs.exe` | **The one you download.** Unified build — first-run chooser, or `--mode=control` / `--mode=station` via shortcut |
| `LIKAcs-ControlCenter.exe` | Optional one-click shortcut (= `LIKAcs.exe --mode=control`), available in the workflow build artifact |
| `LIKAcs-StationAgent.exe` | Optional one-click shortcut (= `LIKAcs.exe --mode=station`), available in the workflow build artifact |
| `SHA256SUMS.txt` | Verified by the in-app updater |

Useful switches: `--silent` (tray only), `--mode=setup` (headless first-time setup), `--self-test` (headless protocol/safety smoke test), `--smoke-gui` (construct every window against real Tk, then exit), `--version`.

> Older tags **`v1`** and **`v1.0.1`** contain broken Windows builds. Use the latest release.

To build locally on Windows:

```powershell
git clone https://github.com/azyoff/LIKAcs.git
cd LIKAcs
python -m pip install -r requirements-build.txt   # PyInstaller, build-time only
python scripts\build.py                            # -> dist\*.exe + SHA256SUMS.txt
```

`release.yml` runs on `v*` tags (and `workflow_dispatch` with a tag input), executes the VAC-safety guard + unit tests + in-exe self-test, then publishes the Release. `ci.yml` runs the same checks plus a quick PyInstaller smoke build on every push/PR.

---

## Ports, firewall & LAN keys

| Port | Protocol | Use |
|---|---|---|
| `27055` | UDP broadcast | Signed discovery heartbeats / probes |
| `27056` | TCP | Signed Control Center → Station Agent JSON API |
| `27015`+ | UDP/TCP | Official game server ports (Room 1 = 27015, Room 2 = 27016, ...) |

All ports are configurable in **Settings**. Firewall rules are scoped to `remoteip=localsubnet` (LAN only). Every discovery packet and HTTP request is HMAC-SHA256 signed with the **LAN shared key** (default `lika-lan`) plus timestamp + nonce replay protection. Change the key in Settings and **Save & Sync to All Station PCs** — the agents hot-swap the key without restarting. For a shared/public network, set a strong key and make sure PC clocks are within ~90 seconds.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No PCs appear in the laptop | Same LAN switch / same subnet, allow UDP 27055 + TCP 27056 (run **Firewall Rules (UAC)**), check both apps use the same LAN key, allow private-network discovery in Windows. |
| "bad signature" / "stale timestamp" | LAN keys differ or PC clocks drift. Sync clocks, then Settings → Save & Sync. |
| `lika` does nothing | Run 1-Click Setup on that PC, confirm `exec lika_autoexec.cfg` is in `autoexec.cfg`, check the console is enabled, and make sure the room is **live**. `lika_join.cfg` should contain `connect <ip>:<port>`. |
| F10 still shows the CS 1.6 quit prompt | `userconfig.cfg` must be exec'd last by `config.cfg` (Steam default). Re-run 1-Click Setup; optionally pick another key in Settings. |
| RCON commands fail | Start the room first, confirm the host PC is online, check that `-usercon` + `rcon_password` were passed and that no other server owns the port. Unknown CS 1.6 commands are reported in the log. |
| Host PC can't play | Use `Server mode = listen` (default). CS 1.6 `dedicated` mode also auto-launches a local `hl.exe` client connected to `127.0.0.1`. |
| Steam URL does nothing | Steam must be installed on the gaming PC (it already is — that's where CS2/1.6 came from). For CS 1.6 enable the `+connect` fallback. |
| Update did not apply | Tick "Restart Station Agents after push" or restart the agent; check `%APPDATA%\LIKAcs\pending-update.json` and the agent log. |

Logs live in the UI log panel; setup / firewall reports are saved in `%APPDATA%\LIKAcs\`.

---

## Development

```bash
export PYTHONPATH=src                     # Windows: set PYTHONPATH=src
python -m likacs --self-test              # headless checks (no GUI/Steam needed)
python -m unittest discover -s tests -v  # full unit + integration suite
python scripts/verify_vac_safety.py      # CI VAC-safety guard
python -m likacs --mode=control          # run the dashboard from source
```

Layout: `src/likacs/` → `agent.py`, `control.py`, `cfgs.py`, `network.py`, `http_api.py`, `rcon.py`, `games.py`, `rules.py`, `paths.py`, `setup_windows.py`, `update.py`, `tray.py`, `state.py`, `security.py`, `ui/`. Tests in `tests/`, docs in `docs/`, release automation in `.github/workflows/`. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

[MIT](LICENSE) — free and open-source for every internet cafe owner worldwide.  
© 2026 azyoff / LIKAcs — <http://likaapps.com>

*Counter-Strike and Steam are trademarks of Valve Corporation. LIKAcs is an independent, unofficial, open-source tool and is not affiliated with Valve.*
