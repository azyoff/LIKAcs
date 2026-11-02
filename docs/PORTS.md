# Ports, firewall and LAN security

Website: <http://likaapps.com>

| Port | Protocol | Direction | Used by |
|---|---|---|---|
| `27055` (configurable) | UDP broadcast | in/out | Signed discovery heartbeats & probes |
| `27056` (configurable) | TCP | in | Signed Control Center → Station Agent JSON API |
| `27015` (configurable base) | UDP + TCP | in | Official CS2 / CS 1.6 game server + RCON |
| `27016`, `27017`, ... | UDP + TCP | in | Room 2, Room 3, ... game servers |

Different host PCs can technically share the same game port (different IPs),
but LIKAcs allocates a unique port per room to keep `lika1..3` and RCON
unambiguous. Ports are configurable in **Settings → First game port**.

## Discovery addresses

`util.broadcast_addresses()` returns:

1. the global limited broadcast `255.255.255.255`,
2. every directed broadcast computed from `ipconfig /all` IPv4 + subnet mask
   pairs (works for `/16`, `/20`, ... not just `/24`),
3. a `/24` fallback broadcast per detected local IPv4.

Heartbeats are sent every 2 seconds; the Control Center also probes every 3
seconds. The **source IP** of the heartbeat is used as the agent's address, so
DHCP changes require zero configuration.

## Authentication

Every discovery packet and every HTTP request is signed:

```
signature = HMAC_SHA256(lan_key, timestamp + "\n" + nonce + "\n" + raw_body)
```

Headers: `X-LIKACS-Timestamp`, `X-LIKACS-Nonce`, `X-LIKACS-Signature`,
`X-LIKACS-Key-Hint`. Verification checks a ±90 s window, constant-time digest
comparison and a bounded nonce cache that rejects replays. A wrong key yields
HTTP 401 with `bad signature (LAN key mismatch?)`. PC clocks should be roughly
in sync. Change the key in **Settings → Save & Sync to All Station PCs**.

## Windows Defender Firewall

`setup_windows.apply_firewall_rules()` creates idempotent, **LAN-only**
(`remoteip=localsubnet`) rules:

* UDP in: `27055,27056,27015-27035`
* TCP in: `27056,27015-27035`
* out: any protocol to `localsubnet`
* program allow rules for `cs2.exe`, `hl.exe`, `hlds.exe` and `LIKAcs.exe`

`netsh` needs administrator rights. The UI offers **Firewall Rules (UAC)**,
which re-launches the executable elevated with the internal
`--elevated-firewall` switch; the result is saved to
`%APPDATA%\LIKAcs\firewall-report.json`. Rules never expose the cafe PCs to
the public internet.
