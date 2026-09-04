---
name: memory-bridge
description: >-
  Use, configure, or disable the Patricia memory bridge. The default-on PostToolUse hook notices
  when a local memory note is saved and reminds the agent to offer the same fact to Patricia. It
  never writes to Patricia by itself. Triggers on memory bridge, Patricia hook, post save memory
  hook, ship memory to Patricia, memory bridge settings, disable the memory bridge,
  patricia-memory-bridge.json, patricia-plugin.json, and patricia skip.
allowed-tools: Read, Write, Bash
---

# Patricia memory bridge

The bridge is a `PostToolUse` hook on `Write`, `Edit` and `MultiEdit`. When one of them saves a
file inside an agent memory directory, the hook injects one line back into the agent's context:
this note is local only, Patricia does not have it, and if the team should keep it then call
`remember` and choose the scope.

**The hook proposes. It never writes.** It holds no Patricia credential, it opens no connection,
and it cannot decide whether a note is a team fact or a private one. The agent makes that call with
its person, and the agent makes the `remember` call.

## What the bridge already does

The bridge is on by default. An absent config file or an absent key leaves it on. A malformed or
unreadable config turns it off. In a readable config, a literal `false` value turns it off.

The hook reads the saved note locally to confirm that it is a non-empty memory note without the
skip marker. It sends nothing anywhere. Its reminder tells the agent to state the proposed scope
and ask the person before any `remember` call.

## Turn it off

Choose either off switch. The hook reads both files on every matching write.

Write the legacy bridge config to `~/.claude/patricia-memory-bridge.json`:

```json
{
  "enabled": false
}
```

Or write the shared plugin config to `~/.claude/patricia-plugin.json`:

```json
{
  "hooks": {
    "memory_bridge": {
      "enabled": false
    }
  }
}
```

Remove the literal `false` value to turn the bridge on again. Repair or remove a malformed or
unreadable config before you turn the bridge on.

## Configure a moved memory directory

Add `memory_dirs` only when the memory directory has been moved off its default of
`~/.claude/projects/<sanitized-cwd>/memory/`, or when it is a **symlink** into somewhere else. The
hook resolves a path before judging it, so a symlinked `memory/` resolves out of the default shape
and the bridge goes quiet with no error. The hook cannot read Claude Code's own setting, and
matching wider would sweep in ordinary source files:

```json
{
  "memory_dirs": ["/home/example/notes/agent-memory"]
}
```

Each entry must be an existing directory inside your home, and it may not be your home itself.
`"/"`, `"~"` and `""` are ignored: an entry that matches every path would turn the bridge into an
offer on every write anywhere, which is the one thing it must never do.

The hook only exists if the plugin was **installed**, not loaded with `--plugin-dir`. A
directory-loaded plugin gets its skills and not its hooks. Check with `claude plugin details
patricia`: the component inventory must report
`Hooks (5)  SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop`.

## Skip one note

Add a `patricia: skip` line to the note's front matter:

```markdown
---
name: local-only-note
patricia: skip
---
```

The hook reads the front matter only, so a note that merely mentions the marker in its body still
gets offered.

## Check the state

```bash
cat ~/.claude/patricia-memory-bridge.json 2>/dev/null || echo "legacy config absent: bridge remains on"
cat ~/.claude/patricia-plugin.json 2>/dev/null || echo "plugin config absent: bridge remains on"
```

## What it deliberately does not do

- It does not block, delay or change the local write. `PostToolUse` runs after the tool, and the
  hook returns no `decision`.
- It does not choose a memory scope. `remember` takes `scope` and the agent passes it.
- It does not fire twice for the same note in one session, so a `Write` followed by a run of
  `Edit` calls produces one reminder.
- It does not fire for a write outside a memory directory, for a write that did not land, or for a
  note carrying `patricia: skip`.
- It exits quietly on any error. A hook that breaks a session is worse than a hook that says
  nothing.
