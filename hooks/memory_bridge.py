#!/usr/bin/env python3
"""Offer a freshly saved local memory to Patricia. Proposing only, and never writing.

Claude Code stores an agent's own notes as markdown under a memory directory, by default
``~/.claude/projects/<sanitized-cwd>/memory/``. Those notes are written with the ordinary
``Write`` and ``Edit`` tools, so this runs as a ``PostToolUse`` hook on those tools.

It emits one ``hookSpecificOutput.additionalContext`` line telling the agent that the note it
just saved is local only, and that Patricia can hold it for the team. The agent then decides the
memory scope and asks its person. This script decides nothing about scope and calls nothing.

**Why it proposes rather than writes.** A hook is a shell command with no MCP client and no
consent from anybody. Shipping every local note to a shared workspace would put private,
machine-specific and throwaway notes in front of a whole team, silently. The scope choice is a
judgement about the content that only the model, with its person, can make. So the write stays
where the judgement is.

The bridge is on by default. Either its legacy config or the shared plugin config can turn it off
with a literal false value. It ignores every path outside a memory directory. It also ignores one
note that carries ``patricia: skip`` in its front matter.

Exit code is always 0. A hook that breaks a session is worse than a hook that says nothing.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import patricia_client

#: The legacy bridge settings. The enabled key can still turn the bridge off.
CONFIG_ENV_VAR = "PATRICIA_MEMORY_BRIDGE_CONFIG"
DEFAULT_CONFIG = Path.home() / ".claude" / "patricia-memory-bridge.json"

#: The shared plugin settings. Read locally because this module must remain network-free.
PLUGIN_CONFIG_ENV_VAR = "PATRICIA_PLUGIN_CONFIG"
DEFAULT_PLUGIN_CONFIG = Path.home() / ".claude" / "patricia-plugin.json"

#: Where the per-session record of what has already been offered lives.
#:
#: Deliberately NOT ``CLAUDE_PLUGIN_DATA``. That variable is present in a hook's environment, but it
#: is not reliably this plugin's own directory: a project-level hook run on this machine saw it set
#: to ``~/.claude/plugins/data/codex-openai-codex``, an unrelated plugin's data directory. Writing
#: session state into somebody else's plugin data is a bug that nothing would ever report.
STATE_ENV_VAR = "PATRICIA_MEMORY_BRIDGE_STATE"
DEFAULT_STATE = Path.home() / ".claude" / "patricia-memory-bridge-state"

#: The front-matter entry that keeps one note local. Read from the saved file, so a person or an
#: agent can add it to the note itself rather than reaching for a setting.
SKIP_KEY = "patricia"
SKIP_VALUE = "skip"
SKIP_MARKER = f"{SKIP_KEY}: {SKIP_VALUE}"

#: How long a session's already-nudged list survives, so the state directory does not grow forever.
STATE_TTL_SECONDS = 7 * 24 * 60 * 60

#: The suffix every state file carries. Pruning matches on it rather than on ``*``, so a state
#: directory that turns out to hold somebody else's files loses none of them.
STATE_SUFFIX = ".patricia-session"

NUDGE = (
    "Patricia memory bridge: you just saved a local note at {path}. "
    "It lives on this machine only, and Patricia does not have it. "
    "If the team should keep it, call the Patricia MCP tool `remember` and pass `scope` yourself: "
    'pass "workspace" for a fact about the team, and "personal" for a fact about one person. '
    'Pass "personal" when you are unsure, because a workspace memory is readable by every '
    "teammate and cannot be un-read. Ask your person before you save it, and say what scope you "
    "will use. If this note is machine-specific, throwaway or private, save nothing and add a "
    "`patricia: skip` line to its front matter so this stops asking about it."
)


def load_config(path: Path) -> dict[str, object] | None:
    """Return settings, an empty mapping for absence, or None for a corrupt file."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def is_enabled(bridge_config: dict[str, object] | None, plugin_config: dict[str, object] | None) -> bool:
    """Return whether both readable configs permit the bridge."""
    if bridge_config is None or plugin_config is None:
        return False
    if bridge_config.get("enabled") is False:
        return False
    hooks = plugin_config.get("hooks")
    if not isinstance(hooks, dict):
        return True
    settings = hooks.get("memory_bridge")
    return not isinstance(settings, dict) or settings.get("enabled") is not False


def written_path(payload: dict[str, object]) -> Path | None:
    """The file the tool just wrote, from the hook payload.

    ``tool_response.filePath`` is what Claude Code's own documented example reads first, and
    ``tool_input.file_path`` is the fallback for a tool that does not report one back.
    """
    response = payload.get("tool_response")
    if isinstance(response, dict):
        reported = response.get("filePath")
        if isinstance(reported, str) and reported:
            return Path(reported)
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        requested = tool_input.get("file_path")
        if isinstance(requested, str) and requested:
            return Path(requested)
    return None


def bounded_extra_dirs(raw: object) -> list[Path]:
    """The configured extra memory directories, minus every entry that would widen too far.

    This key is the one control that lets the hook offer a path it would otherwise ignore, so it
    is bounded rather than trusted. ``"/"``, ``"~"``, ``""`` and anything outside the person's home
    would each turn the hook into an offer on every write anywhere, which is the failure this
    design exists to avoid.
    """
    if not isinstance(raw, list):
        return []
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return []
    bounded: list[Path] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            continue
        try:
            candidate = Path(entry).expanduser().resolve()
            if not candidate.is_dir():
                continue
            candidate.relative_to(home)
        except (OSError, ValueError):
            continue
        if candidate == home:
            continue
        bounded.append(candidate)
    return bounded


def in_memory_directory(path: Path, extra_dirs: list[Path]) -> bool:
    """Whether ``path`` is a note in an agent memory directory.

    The default shape is ``.../.claude/projects/<slug>/memory/...``, which is where Claude Code
    puts memory when nothing overrides it. A person who moved their memory directory lists it
    under ``memory_dirs`` in the config, because this script cannot read Claude Code's own
    setting and guessing wider would sweep in ordinary source files.
    """
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
        # Exactly .claude/projects/<one folder>/memory. The shared ~/.claude/projects/memory/
        # sits beside the per-project folders rather than inside one, and fails this for free: it
        # would need one component to be both the parent and the grandparent of this "memory".
        if parts[index - 3] == ".claude" and parts[index - 2] == "projects":
            return True
    return False


def front_matter_lines(text: str) -> list[str]:
    """The lines between the opening and closing ``---`` of a note's front matter.

    A byte-order mark and leading blank lines are stepped over, because an editor adds either
    without asking. Front matter that is never closed is not front matter, and returns nothing.
    """
    lines = text.lstrip("\ufeff").splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        return []
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() == "---":
            return block
        block.append(line)
    return []


def carries_skip_marker(path: Path) -> bool:
    """Whether the saved note asks to stay local, in its own front matter.

    Read forgivingly on purpose. This is the only per-note opt-out, and every spelling it fails to
    recognise sends a note that the person asked to keep local. ``Patricia: skip``,
    ``patricia:skip``, ``patricia: "skip"`` and a trailing ``# comment`` all count.

    Only the front matter is read. A note that merely quotes the marker in its body, which any note
    about this hook does, must not silence itself.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in front_matter_lines(text):
        key, separator, value = line.partition(":")
        if not separator or key.strip().casefold() != SKIP_KEY:
            continue
        stated = value.split("#", 1)[0].strip().strip("\"'").strip()
        if stated.casefold() == SKIP_VALUE:
            return True
    return False


def state_file(session_id: str) -> Path | None:
    """The per-session record of what has already been offered, or ``None`` if it has nowhere.

    The session id becomes a file name, so it is reduced to characters that cannot leave the
    directory. A ``..`` or a ``/`` in that field would otherwise choose the path.
    """
    base = patricia_client._configured_path(STATE_ENV_VAR, str(DEFAULT_STATE))
    safe = "".join(character for character in session_id if character.isalnum() or character in "-_")
    if not safe:
        return None
    try:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    return base / f"{safe}{STATE_SUFFIX}"


def prune(directory: Path) -> None:
    """Drop session records nothing will read again."""
    cutoff = time.time() - STATE_TTL_SECONDS
    try:
        stale = [entry for entry in directory.glob(f"*{STATE_SUFFIX}") if entry.stat().st_mtime < cutoff]
    except OSError:
        return
    for entry in stale:
        entry.unlink(missing_ok=True)


def already_offered(record: Path | None, path: Path) -> bool:
    """Whether this session has already offered this note, recording it when it has not.

    Saving a note is often a ``Write`` followed by a run of ``Edit`` calls on the same file. One
    offer per note per session is the whole point; four is nagging that costs context.
    """
    if record is None:
        return False
    key = str(path.resolve())
    try:
        seen = record.read_text(encoding="utf-8").splitlines()
    except OSError:
        seen = []
    if key in seen:
        return True
    try:
        prune(record.parent)
        encoded = "".join(f"{entry}\n" for entry in [*seen, key]).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        descriptor = os.open(record, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
    except OSError:
        pass
    return False


def decide(payload: dict[str, object]) -> str | None:
    """The context line to inject, or ``None`` to stay silent."""
    config_path = patricia_client._configured_path(CONFIG_ENV_VAR, str(DEFAULT_CONFIG))
    config = load_config(config_path)
    plugin_config_path = patricia_client._configured_path(PLUGIN_CONFIG_ENV_VAR, str(DEFAULT_PLUGIN_CONFIG))
    plugin_config = load_config(plugin_config_path)
    if config is None or not is_enabled(config, plugin_config):
        return None

    path = written_path(payload)
    if path is None:
        return None

    if not in_memory_directory(path, bounded_extra_dirs(config.get("memory_dirs"))):
        return None

    # A write that did not land leaves nothing to offer, and this is also how a failed tool call
    # is filtered without depending on the shape of an error response.
    if not path.is_file() or path.stat().st_size == 0:
        return None

    if carries_skip_marker(path):
        return None

    session_id = payload.get("session_id")
    record = state_file(session_id) if isinstance(session_id, str) else None
    if already_offered(record, path):
        return None

    return NUDGE.format(path=path)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        context = decide(payload)
        if context is None:
            return 0
        json.dump(
            {
                "suppressOutput": True,
                "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context},
            },
            sys.stdout,
        )
    except Exception:  # noqa: BLE001 - a hook must never break the session it runs in
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
