"""Match presets, map catalogue and official server cvars / RCON commands.

Everything in this module produces plain-text console commands for official
engine cvars. Nothing here touches game memory or binaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import WEBSITE

# --------------------------------------------------------------------------- presets
@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    slots: int
    description: str
    wingman: bool = False
    deathmatch: bool = False


PRESETS: dict[str, Preset] = {
    "1vs1": Preset("1vs1", "1vs1", 2, "Duel - 2 players"),
    "2vs2": Preset("2vs2", "2vs2", 4, "Four players"),
    "2vs3": Preset("2vs3", "2vs3", 5, "Uneven teams (autoteambalance disabled)"),
    "3vs3": Preset("3vs3", "3vs3", 6, "Six players"),
    "4vs4": Preset("4vs4", "4vs4", 8, "Eight players"),
    "5vs5": Preset("5vs5", "5vs5", 10, "Full competitive match"),
    "wingman": Preset("wingman", "Wingman (2vs2 half-map)", 4, "2vs2 on a half map", wingman=True),
    "deathmatch": Preset("deathmatch", "Deathmatch / Warmup", 20, "Free-for-all respawn", deathmatch=True),
    "custom": Preset("custom", "Custom", 10, "Custom rules / slot count"),
}
PRESET_ORDER = list(PRESETS.keys())

MAPS_CS2 = [
    "de_dust2", "de_mirage", "de_inferno", "de_nuke",
    "de_anubis", "de_ancient", "de_vertigo", "de_train",
]
MAPS_CS16 = ["de_dust2", "de_aztec", "cs_assault", "fy_snow", "aim_map", "de_inferno", "de_nuke", "de_train"]
DEFAULT_MAP = "de_dust2"


def maps_for(game: str) -> list[str]:
    base = MAPS_CS2 if game == "cs2" else MAPS_CS16
    extras = [m for m in MAPS_CS16 if m not in base] if game == "cs2" else []
    return base + extras


def normalize_map(map_name: str) -> str:
    """Custom map names are allowed but restricted to safe filename characters."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", (map_name or "").strip())
    return cleaned[:64] or DEFAULT_MAP


def preset_slots(preset_key: str, custom_slots: int = 10) -> int:
    preset = PRESETS.get(preset_key, PRESETS["custom"])
    if preset.key == "custom":
        return max(2, min(64, int(custom_slots)))
    return preset.slots


# --------------------------------------------------------------------------- cvars
DEFAULT_RULES: dict[str, str] = {
    "sv_lan": "1",                 # 100% local LAN switch traffic, 1 ms ping
    "mp_freezetime": "3",
    "mp_friendlyfire": "1",
    "mp_autokick": "0",            # never auto-kick teammates after friendly fire
    "mp_autoteambalance": "0",
    "mp_limitteams": "0",          # 2vs3 etc. always works
    "mp_forcecamera": "1",         # cafe anti-ghosting
    "bot_quota": "0",              # no bots stealing player slots
}

RULE_HELP: dict[str, str] = {
    "sv_lan": "LAN-only server (1 ms ping, no Steam friends needed)",
    "mp_freezetime": "Freeze time in seconds",
    "mp_friendlyfire": "Friendly fire (1 = on)",
    "mp_autokick": "0 = disables TK auto-kick / ban protection",
    "mp_autoteambalance": "0 = never move players between teams",
    "mp_limitteams": "0 = allow uneven teams (2vs3)",
    "mp_forcecamera": "1 = dead players spectate teammates only (anti-ghosting)",
    "bot_quota": "0 = no bots unless explicitly enabled",
}

# CS 1.6 equivalents for cvars that differ between engines.
CS16_TRANSLATION = {
    "mp_forcecamera": ("mp_forcechasecam", "2"),
}
CS16_EXTRA = {
    "mp_tkpunish": "0",      # disable team-kill punishment / ban
    "mp_startmoney": "800",
    "mp_buytime": "20",
    "mp_roundtime": "2.5",
    "mp_c4timer": "35",
    "sv_aim": "0",
    "pausable": "1",
}
CS2_EXTRA = {
    "mp_warmuptime": "30",
    "mp_halftime": "1",
    "mp_maxrounds": "24",
    "mp_match_can_clinch": "1",
    "sv_allow_votes": "0",
    "sv_vote_quorum_ratio": "0",
    "mp_weapons_allow_zeus": "0",
}


def build_match_cvars(rules: dict[str, str], game: str, preset_key: str,
                      slots: int, overtime: bool = True,
                      extra: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Return an ordered list of official (cvar, value) pairs for a room."""
    merged = dict(DEFAULT_RULES)
    merged.update({str(k): str(v) for k, v in (rules or {}).items() if k})
    cvars: dict[str, str] = {}
    for name, value in merged.items():
        if game == "cs16" and name in CS16_TRANSLATION:
            alias, mapped = CS16_TRANSLATION[name]
            cvars[alias] = mapped
        else:
            cvars[name] = value
    cvars.update(CS2_EXTRA if game == "cs2" else CS16_EXTRA)
    cvars["maxplayers"] = str(max(2, min(64, int(slots))))
    cvars["hostname"] = f'"LIKAcs ({WEBSITE}) - Room"'
    if overtime:
        if game == "cs2":
            cvars["mp_overtime_enable"] = "1"
            cvars["mp_overtime_maxrounds"] = "6"
        else:
            cvars["mp_overtime"] = "1"     # harmless on vanilla HLDS; AMXX may use it
    else:
        if game == "cs2":
            cvars["mp_overtime_enable"] = "0"
        else:
            cvars["mp_overtime"] = "0"

    preset = PRESETS.get(preset_key, PRESETS["custom"])
    if preset.wingman and game == "cs2":
        cvars["game_mode"] = "2"
        cvars["game_type"] = "0"
    if preset.deathmatch:
        cvars["mp_teammates_are_enemies"] = "1"
        if game == "cs2":
            cvars["mp_respawn_on_death_ct"] = "1"
            cvars["mp_respawn_on_death_t"] = "1"
            cvars["mp_roundtime_defuse"] = "15"
            cvars["mp_maxrounds"] = "0"
            cvars["mp_warmuptime"] = "0"
    if extra:
        cvars.update({str(k): str(v) for k, v in extra.items()})
    return list(cvars.items())


def render_cvars(cvars: list[tuple[str, str]], header: str = "") -> str:
    lines = [header.rstrip()] if header else []
    lines += [f"{name} {value}" for name, value in cvars if name]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- live controls
# Each action is a list of official RCON console commands. `None` means the
# Control Center must build the command from additional parameters first.
COMMAND_SETS: dict[str, dict[str, list[str]]] = {
    "knife_round": {
        "cs2": [
            "mp_warmup_end", "mp_startmoney 0", "mp_buytime 0", "mp_freezetime 10",
            "mp_give_player_c4 0", "mp_weapons_allow_zeus 0", "mp_roundtime 1.92",
            "mp_restartgame 1",
        ],
        "cs16": [
            "mp_startmoney 0", "mp_buytime 0", "mp_freezetime 10",
            "mp_give_player_c4 0", "mp_roundtime 3", "sv_restart 1",
        ],
    },
    "swap_teams": {
        "cs2": ["mp_swapteams 1"],
        "cs16": ["mp_swapteams 1"],
    },
    "live_restart": {
        "cs2": ["exec lika_match.cfg", "mp_warmup_end", "mp_restartgame 1"],
        "cs16": ["exec lika_match.cfg", "sv_restart 1"],
    },
    "pause": {
        "cs2": ["mp_pause_match"],
        "cs16": ["pausable 1", "pause"],
    },
    "unpause": {
        "cs2": ["mp_unpause_match"],
        "cs16": ["unpause"],
    },
    "end_warmup": {
        "cs2": ["mp_warmup_end"],
        "cs16": ["sv_restart 1"],  # GoldSrc has no warmup cvar; restart the round
    },
    "kick_bots": {
        "cs2": ["bot_quota 0", "bot_kick"],
        "cs16": ["bot_quota 0", "bot_kick"],
    },
    "restart_match": {
        "cs2": ["mp_warmup_end", "mp_restartgame 3"],
        "cs16": ["sv_restart 3"],
    },
    "start_warmup": {
        "cs2": ["mp_warmup_start"],
        "cs16": ["sv_restart 1"],
    },
    "apply_rules": {
        "cs2": ["exec lika_match.cfg"],
        "cs16": ["exec lika_match.cfg"],
    },
}

CONTROL_LABELS = {
    "knife_round": "Knife Round",
    "swap_teams": "Swap Teams",
    "live_restart": "LIVE! Restart Match (0-0)",
    "pause": "Pause Match",
    "unpause": "Unpause Match",
    "end_warmup": "End Warmup",
    "kick_bots": "Kick Bots",
    "change_map": "Change Map Live",
    "apply_rules": "Re-apply Room Rules",
    "restart_match": "Restart Round",
    "start_warmup": "Start Warmup",
}

CONTROL_NOTES: dict[str, str] = {
    "swap_teams": "CS 1.6 vanilla HLDS may need AMX Mod X for mp_swapteams.",
    "end_warmup": "GoldSrc has no mp_warmup_end; the round is restarted instead.",
    "pause": "GoldSrc pause requires pausable 1 (set automatically by LIKAcs).",
}


def commands_for(action: str, game: str) -> list[str]:
    group = COMMAND_SETS.get(action, {})
    return list(group.get(game, group.get("cs2", [])))


def change_map_commands(game: str, map_name: str) -> list[str]:
    clean = normalize_map(map_name)
    return ["changelevel " + clean] if game == "cs2" else ["changelevel " + clean]


def rules_as_dict(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return {key: value for key, value in pairs}
