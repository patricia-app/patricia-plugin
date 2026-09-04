"""Shared fixtures for the Patricia plugin hook tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

import integrations_first
import memory_bridge
import onboarding
import push_reminder
import recall

HOOKS_DIRECTORY = Path(__file__).resolve().parents[1]
HOOK_MODULES = {
    "onboarding": onboarding,
    "recall": recall,
    "integrations_first": integrations_first,
    "memory_bridge": memory_bridge,
    "push_reminder": push_reminder,
}


class FakeClient:
    """Record tool calls and return a configured response."""

    def __init__(self, response: dict | list | None) -> None:
        self.response = response
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, tool: str, arguments: dict | None = None) -> dict | list | None:
        self.calls.append((tool, arguments))
        return self.response


class _Server(ThreadingHTTPServer):
    requests: list[dict[str, object]]
    response_body: bytes
    response_headers: dict[str, str]
    response_type: str
    response_status: int


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler defines this name
        self.server.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
            }
        )
        self._send_response()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler defines this name
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "json": json.loads(body),
            }
        )
        self._send_response()

    def _send_response(self) -> None:
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", self.server.response_type)
        for name, value in self.server.response_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(self.server.response_body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class FakeMCPServer:
    """Serve one fixed JSON-RPC response and record incoming requests."""

    def __init__(
        self,
        response: dict[str, object],
        *,
        sse: bool = False,
        status: int = 200,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        server = _Server(("127.0.0.1", 0), _Handler)
        encoded = json.dumps(response).encode("utf-8")
        server.response_body = (
            body
            if body is not None
            else (
                b"data: ignored\n\n" + b"data: " + encoded + b"\n\n" if sse else encoded
            )
        )
        server.response_headers = headers or {}
        server.response_type = (
            "text/event-stream; charset=utf-8" if sse else "application/json"
        )
        server.response_status = status
        server.requests = []
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1/mcp"

    @property
    def requests(self) -> list[dict[str, object]]:
        return self.server.requests

    def __enter__(self) -> FakeMCPServer:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class HookTestCase(unittest.TestCase):
    """Give each hook test an isolated home, config, token, and state directory."""

    def setUp(self) -> None:
        super().setUp()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        values = {
            "HOME": str(self.root / "home"),
            "PATRICIA_PLUGIN_CONFIG": str(self.root / "patricia-plugin.json"),
            "PATRICIA_PLUGIN_STATE": str(self.root / "plugin-state"),
            "PATRICIA_TOKEN_FILE": str(self.root / "patricia.json"),
            "PATRICIA_MEMORY_BRIDGE_CONFIG": str(
                self.root / "patricia-memory-bridge.json"
            ),
            "PATRICIA_MEMORY_BRIDGE_STATE": str(self.root / "memory-bridge-state"),
        }
        self.environment = mock.patch.dict(os.environ, values, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("PATRICIA_MCP_TOKEN", None)
        os.environ.pop("PATRICIA_MCP_URL", None)

    def write_token(self, token: str = "secret-test-token") -> None:
        Path(os.environ["PATRICIA_TOKEN_FILE"]).write_text(
            json.dumps({"token": token}), encoding="utf-8"
        )

    def run_hook(
        self, module_name: str, payload: object, *, arguments: list[str] | None = None
    ) -> str:
        if module_name not in HOOK_MODULES:
            raise KeyError(f"Unknown hook module: {module_name}")
        module = HOOK_MODULES[module_name]
        stdin = io.StringIO(json.dumps(payload))
        stdout = io.StringIO()
        argv = [str(HOOKS_DIRECTORY / f"{module_name}.py"), *(arguments or [])]
        with (
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(sys, "argv", argv),
        ):
            result = module.main()
        self.assertEqual(result, 0)
        return stdout.getvalue()

    def run_script(
        self,
        script_name: str,
        payload: object,
        *,
        extra_environment: dict[str, str] | None = None,
        arguments: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(extra_environment or {})
        return subprocess.run(  # noqa: S603 - fixed interpreter and script paths, without a shell
            [sys.executable, str(HOOKS_DIRECTORY / script_name), *(arguments or [])],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            cwd=HOOKS_DIRECTORY,
            env=environment,
        )

    def parse_output(self, output: str) -> dict[str, Any] | None:
        if not output.strip():
            return None
        return json.loads(output)


@contextlib.contextmanager
def patched_stdio() -> Any:
    """Capture both output streams for a direct client call."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield stdout, stderr
