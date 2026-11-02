"""Wire protocol constants shared by the Control Center and Station Agents."""

from __future__ import annotations

MAGIC = "LIKACS/1"

# UDP LAN discovery (broadcast / heartbeat). Both sides bind this port.
DISCOVERY_PORT = 27055
# Signed HTTP/JSON control channel exposed by every Station Agent.
AGENT_PORT = 27056
# First game server port; Room 1 = 27015, Room 2 = 27016, etc.
GAME_PORT_BASE = 27015

HEARTBEAT_INTERVAL = 2.0          # seconds
PROBE_INTERVAL = 3.0              # control center re-probes quiet LANs
STATION_TIMEOUT = 9.0             # drop a station after 4 missed heartbeats
HTTP_TIMEOUT = 6.0                # LAN request timeout
HTTP_TIMEOUT_LONG = 30.0          # game launch / firewall / update requests
UPDATE_CHUNK_SIZE = 512 * 1024    # per-request binary chunk for LAN push
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_TOOLTIP_CHARS = 127

# Discovery message kinds
MSG_HELLO = "hello"        # station agent heartbeat
MSG_PROBE = "probe"        # control center asks stations to announce
MSG_BYE = "bye"            # station agent shutting down cleanly
MSG_CONTROLLER = "controller"  # control center announces itself (informational)

# HTTP endpoints on a Station Agent (all HMAC-signed, see security.py)
EP_STATUS = "/status"
EP_SETUP = "/setup"
EP_FIREWALL = "/firewall"
EP_AUTOSTART = "/autostart"
EP_CONFIGURE_JOIN = "/configure-join"
EP_WRITE_CONFIG = "/write-config"
EP_LAUNCH_SERVER = "/launch-server"
EP_STOP_SERVER = "/stop-server"
EP_RCON = "/rcon"
EP_STEAM_CONNECT = "/steam-connect"
EP_CLOSE_GAME = "/close-game"
EP_SET_LABEL = "/set-label"
EP_SYNC_SETTINGS = "/sync-settings"
EP_UPDATE_BEGIN = "/update-begin"
EP_UPDATE_CHUNK = "/update-chunk"
EP_UPDATE_FINISH = "/update-finish"
EP_UPDATE_STATUS = "/update-status"

# Steam application ids (official steam:// protocol)
STEAM_APP_CS2 = 730
STEAM_APP_CS16 = 10

HEADERS = {
    "ts": "X-LIKACS-Timestamp",
    "nonce": "X-LIKACS-Nonce",
    "signature": "X-LIKACS-Signature",
    "keyhint": "X-LIKACS-Key-Hint",
}
