"""Signed HTTP/JSON control channel between laptop and Station Agents."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import VERSION, WEBSITE
from .protocol import HTTP_TIMEOUT, MAX_REQUEST_BYTES
from .security import AuthError, LanAuth

Dispatch = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]
Logger = Callable[[str], None]


class ApiError(Exception):
    """A station returned an error or could not be reached."""


class SignedClient:
    """Small urllib-based client; every request body is HMAC signed."""

    def __init__(self, lan_key: str, timeout: float = HTTP_TIMEOUT,
                 logger: Logger | None = None) -> None:
        self.auth = LanAuth(lan_key)
        self.timeout = timeout
        self.logger = logger or (lambda _msg: None)

    def request(self, host: str, port: int, path: str,
                payload: dict[str, Any] | None = None,
                timeout: float | None = None) -> dict[str, Any]:
        body = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        url = f"http://{host}:{int(port)}{path}"
        headers = {"Content-Type": "application/json", "User-Agent": f"LIKAcs/{VERSION}"}
        headers.update(self.auth.headers_for(body))
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                detail = {"error": raw.decode("utf-8", "replace")[:200]}
            raise ApiError(f"{host}: {detail.get('error', exc.reason)}") from exc
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            raise ApiError(f"{host}: station unreachable ({exc})") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ApiError(f"{host}: invalid station response") from exc
        if isinstance(result, dict) and result.get("error"):
            raise ApiError(f"{host}: {result['error']}")
        return result

    def status(self, host: str, port: int, timeout: float = 2.5) -> dict[str, Any]:
        return self.request(host, port, "/status", {}, timeout=timeout)


def _make_handler(auth: LanAuth, dispatch: Dispatch, logger: Logger):
    class AgentHandler(BaseHTTPRequestHandler):
        server_version = f"LIKAcs/{VERSION}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the log ours
            logger("http " + (fmt % args))

        def _send(self, code: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self) -> None:  # read-only identity page for manual LAN checks
            if self.path.split("?", 1)[0] in ("/", "/ping"):
                self._send(200, {
                    "app": "LIKAcs Station Agent", "version": VERSION,
                    "website": WEBSITE, "ok": True,
                })
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._send(413 if length > MAX_REQUEST_BYTES else 400,
                           {"error": "invalid request size"})
                return
            body = self.rfile.read(length)
            headers = {str(k).lower(): str(v) for k, v in self.headers.items()}
            try:
                auth.verify(headers, body)
            except AuthError as exc:
                self._send(401, {"error": str(exc)})
                return
            try:
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
            except (ValueError, UnicodeError) as exc:
                self._send(400, {"error": f"bad JSON: {exc}"})
                return
            try:
                code, result = dispatch(self.path.split("?", 1)[0], payload)
            except Exception as exc:  # never crash the agent on a bad command
                logger(f"api error on {self.path}: {exc!r}")
                self._send(500, {"error": str(exc)})
                return
            self._send(code, result)

    return AgentHandler


class AgentHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], auth: LanAuth,
                 dispatch: Dispatch, logger: Logger | None = None) -> None:
        log = logger or (lambda _msg: None)
        handler = _make_handler(auth, dispatch, log)
        super().__init__(address, handler)
        self._thread = threading.Thread(target=self.serve_forever, name="likacs-http", daemon=True)
        self._poll = 0.4

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=2.0)
