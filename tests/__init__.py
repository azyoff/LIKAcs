"""Test bootstrap: keep cafe state out of the developer's real config dir."""

from __future__ import annotations

import os
import socket
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="likacs-tests-")
os.environ["XDG_CONFIG_HOME"] = _TEST_HOME
os.environ["APPDATA"] = _TEST_HOME


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port
