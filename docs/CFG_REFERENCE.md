# Official config-file reference

Website: <http://likaapps.com>

All files below live in the game's **official cfg folder**:

* CS2: `...\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\`
* CS 1.6: `...\steamapps\common\Half-Life\cstrike\cfg\`

LIKAcs never writes anywhere else in the game installation.

## Installed once (1-Click Station Setup)

**`autoexec.cfg` (CS2) / `userconfig.cfg` (CS 1.6)** — existing content preserved:

```
bind "MOUSE1" "+attack"          <-- player's own lines, untouched
sensitivity "2.1"
...
// >>> LIKAcs (likaapps.com) managed block - START
exec lika_autoexec.cfg
// <<< LIKAcs (likaapps.com) managed block - END
```

A backup `autoexec.cfg.likacs-backup-YYYYMMDD-HHMMSS` is created before the
first edit. Re-running setup removes and re-adds the block (never duplicates).

**`lika_autoexec.cfg`** (generated, safe to regenerate):

```
con_enable 1                                  // CS2 (console 1 on CS 1.6)
alias "lika" "exec lika_join.cfg"             // default word always kept
alias "myword" "exec lika_join.cfg"           // optional custom word
alias "lika1" "exec lika_room1.cfg"
alias "lika2" "exec lika_room2.cfg"
alias "lika3" "exec lika_room3.cfg"
unbind "F10"
bind "F10" "lika"
echo "LIKAcs ready - http://likaapps.com - type lika or press F10 to join"
```

## Rewritten in real time (per-PC routing)

**`lika_join.cfg`** — the PC's assigned room:

```
password "..."                // only if the room has a join password
connect 192.168.1.5:27015
echo "LIKAcs: joining Room 1 (192.168.1.5:27015)"
```

If the PC has no live assigned room, the file contains only an `echo` hint.
Because the alias does `exec lika_join.cfg`, the engine reads this file **at
the moment the player types `lika` or presses F10** — so the Station Agent can
change a PC's room instantly while the game is open.

**`lika_room1.cfg`, `lika_room2.cfg`, `lika_room3.cfg`** — same format, for
the `lika1` / `lika2` / `lika3` aliases (Room 1, 2, 3 respectively). Push to
all PCs, so any player can also join a specific room explicitly.

## Match rules (per room, on the host)

**`lika_match.cfg`** — official cvars, exec'd at launch and by RCON:

```
sv_lan 1
mp_freezetime 3
mp_friendlyfire 1
mp_autokick 0
mp_autoteambalance 0
mp_limitteams 0
mp_forcecamera 1
bot_quota 0
maxplayers 10
hostname "LIKAcs (http://likaapps.com) - Room 1"
mp_overtime_enable 1
mp_overtime_maxrounds 6
...
mp_warmup_end                 // CS2: warmup ends automatically (CS1.6: sv_restart 1)
```

CS 1.6 translation: `mp_forcecamera` → `mp_forcechasecam 2`, plus
`mp_tkpunish 0`, `mp_startmoney 800`, `mp_buytime 20`, `mp_roundtime 2.5`,
`mp_c4timer 35`, `pausable 1`. Wingman adds `game_mode 2 / game_type 0` on
CS2; Deathmatch adds `mp_teammates_are_enemies 1` and respawn cvars.

**`lika_knife.cfg`** — Knife Round sequence (`mp_startmoney 0`,
`mp_buytime 0`, `mp_freezetime 10`, `mp_give_player_c4 0`, restart).
Written to the host and exec'd through official RCON.

## Why this is VAC-safe

Only official engine console commands and cvars are used. Nothing here reads
or writes game memory, injects code, patches binaries or disables VAC. See
[VAC_SAFETY.md](VAC_SAFETY.md).
