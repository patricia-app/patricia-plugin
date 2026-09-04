#!/usr/bin/env python3
"""Remind the agent to use an existing Patricia integration before a raw API.

This hook does not need a token and never calls a server. The reminder is useful before
the person connects this plugin, and matching local prompt or tool input leaks nothing.

The host catalog stores host names only. A configured host matches itself and its
subdomains. A leading wildcard matches subdomains but not the base host.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import patricia_client

CATALOG_PATH = Path(__file__).with_name("integration_names.json")
SUPPORTED_TOOLS = frozenset({"WebFetch", "WebSearch", "Bash"})
SUPPORTED_EVENTS = frozenset({"UserPromptSubmit", "PreToolUse"})
HOST_SCAN_MAX_CHARS = 8192
HOST_PATTERN = re.compile(
    r"(?i)(?:https?://)?((?:[a-z0-9-]{1,63}\.){1,10}[a-z]{2,63})(?::\d+)?"
)


def _event_name(payload: dict, explicit: str | None = None) -> str:
    """Prefer an explicit event, then use the payload or the prompt lane."""
    if explicit in SUPPORTED_EVENTS:
        return explicit
    payload_event = payload.get("hook_event_name")
    return payload_event if payload_event in SUPPORTED_EVENTS else "UserPromptSubmit"


def _event_argument(arguments: list[str]) -> str | None:
    """Read one supported event from the hook command arguments."""
    if len(arguments) == 2 and arguments[0] == "--event":
        return arguments[1] if arguments[1] in SUPPORTED_EVENTS else None
    return None


def load_apps() -> list[dict[str, object]]:
    """Load valid integration entries from the catalog beside this script."""
    try:
        loaded = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(loaded, dict) or not isinstance(loaded.get("apps"), list):
        return []
    return [entry for entry in loaded["apps"] if isinstance(entry, dict)]


def _term_pattern(term: str) -> re.Pattern[str] | None:
    """Build a case-insensitive whole-word or whole-phrase pattern."""
    words = term.strip().split()
    if not words:
        return None
    phrase = r"\s+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<![A-Za-z0-9]){phrase}(?![A-Za-z0-9])", flags=re.IGNORECASE)


def prompt_apps(prompt: str, apps: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return integrations whose name or a specific alias occurs in the prompt."""
    matches: list[dict[str, object]] = []
    for app in apps:
        if app.get("prompt_match") is False:
            continue
        name = app.get("name")
        aliases = app.get("aliases")
        if not isinstance(name, str) or not isinstance(aliases, list):
            continue
        terms = [name, *(alias for alias in aliases if isinstance(alias, str))]
        if any(pattern.search(prompt) for term in terms if (pattern := _term_pattern(term)) is not None):
            matches.append(app)
    return matches


def extract_hosts(text: str) -> set[str]:
    """Extract lowercase host-looking tokens from a URL, query, or shell command."""
    scanned = text[:HOST_SCAN_MAX_CHARS]
    hosts = {match.group(1).casefold().rstrip(".") for match in HOST_PATTERN.finditer(scanned)}
    try:
        parsed = urlsplit(scanned if "://" in scanned else f"//{scanned}")
    except ValueError:
        return hosts
    if parsed.hostname:
        hosts.add(parsed.hostname.casefold().rstrip("."))
    return hosts


def host_matches(candidate: str, configured: str) -> bool:
    """Return whether a candidate is the configured host or an allowed subdomain."""
    expected = configured.casefold().rstrip(".")
    if expected.startswith("*."):
        base = expected[2:]
        return candidate != base and candidate.endswith(f".{base}")
    return candidate == expected or candidate.endswith(f".{expected}")


def host_apps(hosts: set[str], apps: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return integrations that own at least one candidate API host."""
    matches: list[dict[str, object]] = []
    for app in apps:
        configured_hosts = app.get("hosts")
        if not isinstance(configured_hosts, list):
            continue
        if any(
            host_matches(candidate, configured)
            for candidate in hosts
            for configured in configured_hosts
            if isinstance(configured, str)
        ):
            matches.append(app)
    return matches


def _new_apps(
    payload: dict, matches: list[dict[str, object]], event: str
) -> list[dict[str, object]]:
    """Remove apps already mentioned in this session and record each new match."""
    state_key = {
        "UserPromptSubmit": "prompt_apps",
        "PreToolUse": "tool_apps",
    }[event]
    session_id = payload.get("session_id")
    record = (
        patricia_client.session_state_file(session_id, "integrations-first") if isinstance(session_id, str) else None
    )
    if record is None:
        return []
    state = patricia_client.read_state(record)
    raw_seen = state.get(state_key)
    seen = {slug for slug in raw_seen if isinstance(slug, str)} if isinstance(raw_seen, list) else set()

    fresh = [app for app in matches if isinstance(app.get("slug"), str) and app["slug"] not in seen]
    if not fresh:
        return []
    seen.update(str(app["slug"]) for app in fresh)
    state[state_key] = sorted(seen)
    return fresh if patricia_client.write_state(record, state) else []


def _names(apps: list[dict[str, object]]) -> str:
    """Join unique integration names for one reminder sentence."""
    names = list(dict.fromkeys(str(app["name"]) for app in apps if isinstance(app.get("name"), str)))
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def reminder(apps: list[dict[str, object]]) -> str:
    """Build the integrations-first context for matched apps."""
    return (
        f"Patricia may already have {_names(apps)} connected. Call `list_integrations` first; "
        "if it is there, use `ask_patricia` to work through it instead of a raw API or the web."
    )


def decide(payload: dict, explicit_event: str | None = None) -> str | None:
    """Return a reminder for this hook event, or None."""
    if not patricia_client.hook_enabled("integrations_first"):
        return None
    apps = load_apps()
    event = _event_name(payload, explicit_event)
    matches: list[dict[str, object]] = []
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if isinstance(prompt, str):
            matches = prompt_apps(prompt, apps)
    elif event == "PreToolUse" and payload.get("tool_name") in SUPPORTED_TOOLS:
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return None
        field = {"WebFetch": "url", "WebSearch": "query", "Bash": "command"}[str(payload["tool_name"])]
        value = tool_input.get(field)
        if isinstance(value, str):
            matches = host_apps(extract_hosts(value), apps)
    fresh = _new_apps(payload, matches, event)
    return reminder(fresh) if fresh else None


def main() -> int:
    """Run the hook and always permit the session to continue."""
    try:
        payload = patricia_client.read_payload()
        event = _event_name(payload, _event_argument(sys.argv[1:]))
        context = decide(payload, event)
        if context is not None:
            patricia_client.emit(event, context)
    except Exception:  # noqa: BLE001 - a hook must never break the session it runs in
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
