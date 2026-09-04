#!/usr/bin/env python3
"""Provide quiet, standard-library plumbing for the Patricia plugin hooks.

The client sends one stateless JSON-RPC request for each call. It accepts JSON and
server-sent event responses. The PATRICIA_MCP_URL override exists only for tests.

Every public helper fails quietly. A hook must not interrupt the session when a local
file, malformed response, or network call fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

TOKEN_ENV_VAR = "PATRICIA_MCP_TOKEN"
TOKEN_FILE_ENV_VAR = "PATRICIA_TOKEN_FILE"
DEFAULT_TOKEN_FILE = "~/.claude/patricia.json"

MCP_URL = "https://api.patricia.app/v1/mcp"
MCP_URL_ENV_VAR = "PATRICIA_MCP_URL"
TIMEOUT_SECONDS = 3.0
RESPONSE_MAX_BYTES = 1024 * 1024

CONFIG_ENV_VAR = "PATRICIA_PLUGIN_CONFIG"
DEFAULT_CONFIG_FILE = "~/.claude/patricia-plugin.json"

STATE_ENV_VAR = "PATRICIA_PLUGIN_STATE"
DEFAULT_STATE_DIRECTORY = "~/.claude/patricia-plugin-state"
SESSION_STATE_SUFFIX = ".patricia-session.json"
SESSION_STATE_TTL_SECONDS = 7 * 24 * 60 * 60


def _configured_path(variable: str, default: str) -> Path:
    """Return an overridden path, or the default path under the current home directory."""
    return Path(os.environ.get(variable) or default).expanduser()


def _workspace_text(text: str) -> str:
    """Neutralize framing characters and collapse whitespace in workspace data."""
    collapsed = " ".join(
        text.replace("`", "").replace("[", "").replace("]", "").split()
    )
    return collapsed.removeprefix("- ")


def _shorten(text: str, length: int) -> str:
    """Shorten one display value at a word boundary and mark every cut."""
    if len(text) <= length:
        return text
    if length <= 3:
        return "." * length
    prefix = text[: length - 3].rstrip()
    boundary = prefix.rfind(" ")
    if boundary >= 0:
        prefix = prefix[:boundary].rstrip()
    return f"{prefix}..."


def read_token() -> str | None:
    """Return the configured bearer token, without exposing or changing it."""
    if TOKEN_ENV_VAR in os.environ:
        token = os.environ[TOKEN_ENV_VAR].strip()
        return token or None

    path = _configured_path(TOKEN_FILE_ENV_VAR, DEFAULT_TOKEN_FILE)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    token = loaded.get("token")
    if not isinstance(token, str):
        return None
    stripped = token.strip()
    return stripped or None


def has_token() -> bool:
    """Return whether a non-empty bearer token is configured."""
    return read_token() is not None


def _response_message(
    body: bytes, content_type: str, request_id: object
) -> dict[str, object] | None:
    """Decode one JSON-RPC message from a JSON or server-sent event response."""
    text = body.decode("utf-8", errors="replace")
    if content_type.split(";", 1)[0].strip().casefold() == "text/event-stream":
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                message = json.loads(line[5:].strip())
            except ValueError:
                continue
            if (
                isinstance(message, dict)
                and message.get("jsonrpc") == "2.0"
                and message.get("id") == request_id
                and ("result" in message or "error" in message)
            ):
                return message
        return None
    try:
        message = json.loads(text)
    except ValueError:
        return None
    if not isinstance(message, dict) or message.get("id") != request_id:
        return None
    return message


def _result_content(message: dict[str, object]) -> dict | list | None:
    """Extract the useful tool result from one JSON-RPC response."""
    if message.get("error") is not None:
        return None
    result = message.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return None

    if "structuredContent" in result:
        structured = result["structuredContent"]
        return structured if isinstance(structured, (dict, list)) else None

    content = result.get("content")
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    if not isinstance(text, str):
        return None
    try:
        decoded = json.loads(text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, (dict, list)) else None


def _request_url() -> str | None:
    """Return the fixed endpoint or a safe explicit override."""
    import urllib.parse

    value = os.environ.get(MCP_URL_ENV_VAR) or MCP_URL
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if hostname is None:
        return None
    scheme = parsed.scheme.casefold()
    host = hostname.casefold()
    if scheme == "https" and (host == "patricia.app" or host.endswith(".patricia.app")):
        return value
    if scheme in {"http", "https"} and host in {"127.0.0.1", "::1", "localhost"}:
        return value
    return None


def _open_request(url: str, body: bytes, token: str):  # type: ignore[no-untyped-def]
    """Open one request without following a redirect."""
    import urllib.request

    class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            return None

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=TIMEOUT_SECONDS)


def call(tool: str, arguments: dict | None = None) -> dict | list | None:
    """Call one Patricia tool and return its structured value, or None after any failure."""
    try:
        url = _request_url()
        if url is None:
            return None
        token = read_token()
        if token is None:
            return None

        request_id = 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
        body = json.dumps(payload).encode("utf-8")
        with _open_request(url, body, token) as response:
            status = response.getcode()
            if status is None or not 200 <= status < 300:
                return None
            content_type = response.headers.get("Content-Type", "")
            body = response.read(RESPONSE_MAX_BYTES + 1)
            if len(body) > RESPONSE_MAX_BYTES:
                return None
            message = _response_message(body, content_type, request_id)
        return _result_content(message) if message is not None else None
    except Exception:  # noqa: BLE001 - a hook client must stay silent after every failure
        return None


def hook_enabled(name: str) -> bool:
    """Return whether a readable config permits this hook."""
    path = _configured_path(CONFIG_ENV_VAR, DEFAULT_CONFIG_FILE)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    if not isinstance(loaded, dict):
        return True
    hooks = loaded.get("hooks")
    if not isinstance(hooks, dict):
        return True
    settings = hooks.get(name)
    if not isinstance(settings, dict):
        return True
    return settings.get("enabled") is not False


def _state_directory(kind: str) -> Path | None:
    """Create and return one plugin state directory."""
    root = _configured_path(STATE_ENV_VAR, DEFAULT_STATE_DIRECTORY)
    directory = root / kind
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    return directory


def _safe_name(value: str) -> str:
    """Remove every character that is not safe in a plugin state file name."""
    return re.sub(r"[^A-Za-z0-9_-]", "", value)


def session_state_file(session_id: str, hook: str) -> Path | None:
    """Return the state file for one hook in one session."""
    safe_session = _safe_name(session_id)
    safe_hook = _safe_name(hook)
    if not safe_session or not safe_hook:
        return None
    directory = _state_directory("sessions")
    if directory is None:
        return None
    return directory / f"{safe_session}.{safe_hook}{SESSION_STATE_SUFFIX}"


def project_state_file(cwd: str) -> Path | None:
    """Return the state file for one project directory."""
    if not cwd:
        return None
    directory = _state_directory("projects")
    if directory is None:
        return None
    key = hashlib.sha256(cwd.encode("utf-8")).hexdigest()[:16]
    return directory / f"{key}.json"


def read_state(path: Path | None) -> dict[str, object]:
    """Read a state mapping, or return an empty mapping when it is unavailable."""
    if path is None:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _prune_session_state(directory: Path) -> None:
    """Remove expired session files that use this plugin's private suffix."""
    cutoff = time.time() - SESSION_STATE_TTL_SECONDS
    try:
        stale = [
            entry
            for entry in directory.glob(f"*{SESSION_STATE_SUFFIX}")
            if entry.stat().st_mtime < cutoff
        ]
    except OSError:
        return
    for entry in stale:
        try:
            entry.unlink()
        except OSError:
            continue


def write_state(path: Path | None, state: dict[str, object]) -> bool:
    """Write a state mapping and return whether the write succeeded."""
    if path is None:
        return False
    try:
        encoded = json.dumps(state, sort_keys=True).encode("utf-8")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.name.endswith(SESSION_STATE_SUFFIX):
            _prune_session_state(path.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
    except (OSError, TypeError, ValueError):
        return False
    return True


def emit(event: str, context: str) -> None:
    """Write exactly one additional-context JSON object to standard output."""
    json.dump(
        {
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            },
        },
        sys.stdout,
    )


def read_payload() -> dict:
    """Read a hook payload from standard input, or return an empty mapping."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001 - every unusable hook input becomes an empty mapping
        return {}
    return payload if isinstance(payload, dict) else {}
