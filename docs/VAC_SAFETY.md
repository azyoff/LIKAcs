# 100% VAC-safe design

<http://likaapps.com> · LIKAcs contains zero cheats.

## Allowed (and used)

| Mechanism | Where in the code |
|---|---|
| Official config files: `autoexec.cfg` / `userconfig.cfg` hook, `lika_autoexec.cfg`, `lika_join.cfg`, `lika_room1..3.cfg`, `lika_match.cfg`, `lika_knife.cfg` | `cfgs.py`, `agent._api_configure_join`, `agent._api_write_config` |
| Official launch parameters: `-usercon`, `+rcon_password`, `+sv_lan 1`, `+map`, `+maxplayers`, `-port`, `+exec`, `+ip`, `+connect` | `games.build_server_argv`, `steam.connect_fallback_argv` |
| Official RCON: Source RCON TCP (`SERVERDATA_AUTH` / `EXECCOMMAND`) for CS2, GoldSrc UDP `challenge rcon` for CS 1.6, fallback to Source RCON for modern HLDS | `rcon.py` |
| Steam's official `steam://connect/<ip>:<port>` and `steam://rungameid/<id>` | `steam.py` |
| Operating-system process start / graceful stop (`WM_CLOSE`, then `taskkill`) | `games.py` |
| Windows Defender Firewall rules, registry auto-start, developer-console cvar | `setup_windows.py`, `cfgs.py` |

## Forbidden (and enforced)

- `ReadProcessMemory`, `WriteProcessMemory`, `OpenProcess` for game access,
  `VirtualAllocEx`, `CreateRemoteThread`, `NtWriteVirtualMemory`, `SetWindowsHookEx`
- Any DLL injection, hook, signature scan, engine patch or game binary edit
- `-insecure`, `-allow_no_steam_ticket` or any flag that disables VAC/ticket auth
- Simulated keystroke injection into a game window
- Reading crosshair/sensitivity/binds from memory; overwriting existing binds
  other than the explicitly configured 1-key join key

`scripts/verify_vac_safety.py` strips comments and string literals with
`tokenize`, then scans only real code tokens for these APIs. It also asserts
at runtime that `build_server_argv()` produces `+sv_lan 1` and `-usercon` and
no VAC-disabling flag. This runs in **CI and in the release workflow before
any .exe is published**.

## Config-file safety details

* The `autoexec.cfg` / `userconfig.cfg` hook is a 3-line, clearly delimited
  managed block. It is removed and re-appended idempotently, so it can never
  duplicate. A timestamped backup is created before the first edit.
* The rest of the player's file — crosshair, sensitivity, binds, rates — is
  byte-for-byte preserved (aside from line-ending normalization on rewrite).
* In CS 1.6, `config.cfg` execs `userconfig.cfg` **last**, so
  `unbind "F10"; bind "F10" "lika"` cleanly replaces the default
  `bind "F10" "quit prompt"` without touching any other key.
* Only official console commands/cvars are written. `lika_join.cfg` contains
  `connect <ip>:<port>` and (optionally) `password` — nothing else.
* `exec` reads the target file from disk when the alias runs, which is why
  retargeting a PC does not require restarting the game or injecting input.

## Network safety

Discovery packets and every HTTP control request are HMAC-SHA256 signed with
the cafe LAN key, carry a timestamp (±90 s) and a nonce cached to reject
replays. Firewall rules are restricted to `remoteip=localsubnet`. RCON
passwords are per-room and redacted from logs.
