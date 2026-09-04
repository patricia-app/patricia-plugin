#!/usr/bin/env python3
"""Offer to save durable session facts before the agent finishes.

The hook reads a bounded local transcript. It looks for a local memory write or a long
tool-using session that did not already call a Patricia memory tool. It proposes a save,
but it never sends a fact or writes a Patricia memory.
"""

from __future__ import annotations

import json
from pathlib import Path

import patricia_client

MIN_TOOL_CALLS = 12
MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
MEMORY_TOOLS = frozenset({"remember", "remember_many"})

REMINDER = (
    "Patricia plugin: this session may have produced facts worth keeping for the team. Before you finish, list what "
    "you learned that outlives this session (a decision, a convention, a preference, a fact about a system) and "
    "offer to save each one with `remember` (or `remember_many` for a batch), passing `scope` as `workspace` for a "
    "team fact or `personal` for a fact about one person. Ask before saving. Skip this if nothing durable was learned."
)

LOCAL_NOTE_CONTEXT = " You wrote a local memory note this session; Patricia does not have it."


def in_memory_directory(path: Path, extra_dirs: list[Path]) -> bool:
    """Return whether a path is inside a standard or configured agent memory directory."""
    resolved = path.resolve()
    for candidate in extra_dirs:
        try:
            resolved.relative_to(candidate)
        except ValueError:
            continue
        return True
    parts = resolved.parts
    for index, part in enumerate(parts):
        if part != "memory" or index < 3:
            continue
        if parts[index - 3] == ".claude" and parts[index - 2] == "projects":
            return True
    return False


def _tool_uses(transcript_path: str) -> list[dict[str, object]] | None:
    """Read tool-use blocks from at most 5 MB of a JSON Lines transcript."""
    try:
        with Path(transcript_path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - MAX_TRANSCRIPT_BYTES)
            starts_at_line_boundary = True
            if start:
                handle.seek(start - 1)
                starts_at_line_boundary = handle.read(1) == b"\n"
            handle.seek(start)
            body = handle.read(MAX_TRANSCRIPT_BYTES)
    except OSError:
        return None
    if start and not starts_at_line_boundary:
        _partial, separator, body = body.partition(b"\n")
        if not separator:
            body = b""

    uses: list[dict[str, object]] = []
    for raw_line in body.splitlines():
        try:
            entry = json.loads(raw_line)
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        uses.extend(item for item in message["content"] if isinstance(item, dict) and item.get("type") == "tool_use")
    return uses


def _summary(tool_uses: list[dict[str, object]]) -> tuple[bool, bool]:
    """Return whether the session wrote local memory and already used Patricia memory."""
    local_memory_write = False
    used_patricia_memory = False
    for tool_use in tool_uses:
        name = tool_use.get("name")
        if not isinstance(name, str):
            continue
        if name.rsplit("__", 1)[-1] in MEMORY_TOOLS:
            used_patricia_memory = True
        if name not in WRITE_TOOLS:
            continue
        tool_input = tool_use.get("input")
        if not isinstance(tool_input, dict):
            continue
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        try:
            if in_memory_directory(Path(file_path), []):
                local_memory_write = True
        except (OSError, RuntimeError):
            continue
    return local_memory_write, used_patricia_memory


def decide(payload: dict) -> str | None:
    """Return the durable-fact reminder for this session, or None."""
    if not patricia_client.hook_enabled("push_reminder"):
        return None
    if payload.get("stop_hook_active") is True or not patricia_client.has_token():
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return None
    record = patricia_client.session_state_file(session_id, "push-reminder")
    if record is None or patricia_client.read_state(record).get("reminded") is True:
        return None
    transcript_path = payload.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    tool_uses = _tool_uses(transcript_path)
    if tool_uses is None:
        return None
    local_memory_write, used_patricia_memory = _summary(tool_uses)
    long_session_without_memory = len(tool_uses) >= MIN_TOOL_CALLS and not used_patricia_memory
    if not local_memory_write and not long_session_without_memory:
        return None

    if not patricia_client.write_state(record, {"reminded": True}):
        return None
    return f"{REMINDER}{LOCAL_NOTE_CONTEXT if local_memory_write else ''}"


def main() -> int:
    """Run the stop hook and always permit the session to continue."""
    try:
        context = decide(patricia_client.read_payload())
        if context is not None:
            patricia_client.emit("Stop", context)
    except Exception:  # noqa: BLE001 - a hook must never break the session it runs in
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
