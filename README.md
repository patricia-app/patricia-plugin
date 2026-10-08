> [!NOTE]
> This repository is generated from `bettergroupinc/patricia-monorepo` at `plugins/patricia/`.
> Automation syncs this public mirror.
> Source commit: `e9d13b74d4ca5def66b005ebeb7ea06f1a6a091a`.
> Open pull requests and issues in the monorepo.

# `patricia` Claude Code plugin

Install this once and an agent uses Patricia's MCP server properly without being told again.

It carries three things.

1. **Guidance.** Five skills cover Patricia basics, onboarding, delegated work, integrations, and the memory bridge.
2. **An MCP connection.** The install configures Patricia's Streamable HTTP server for OAuth sign-in.
3. **Five local hooks.** They onboard projects, recall memory, check integrations first, and propose
   memory pushes. They never write to Patricia.

This is a distributable Claude Code plugin. A person installs it on their own machine, and it runs
in that person's Claude Code session. It is not Patricia's product skill catalogue, and nothing in
it runs inside Patricia.

## Install

```bash
claude plugin marketplace add patricia-app/patricia-plugin
claude plugin install patricia@patricia
```

Then start a new session, or run `/reload-plugins`.

That marketplace is https://github.com/patricia-app/patricia-plugin. Automation generates every
file in it from Patricia's monorepo.

Contributor note: the monorepo is private. A contributor with access can add the monorepo itself as
a marketplace, because its root `.claude-plugin/marketplace.json` points the `patricia` plugin at
`./plugins/patricia`.

**Install it. Do not load it with `--plugin-dir`.** A directory-loaded plugin gets its skills and
not its hooks, so the guidance would work and the memory bridge would never fire. That was measured
rather than assumed: a probe hook loaded through `--plugin-dir` never ran, while the same hook
declared in project settings ran on the same write in the same headless mode. Claude Code registers
a plugin's `hooks/hooks.json` only for an installed, enabled plugin.

`claude plugin details patricia` reports what landed:

```
Component inventory
  Skills (5)  delegating-work, integrations, memory-bridge, onboard, using-patricia
  MCP servers (1)  patricia
  Hooks (5)  SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop
```

## Sign in to the MCP server

The plugin configures the MCP server without a stored header. On first use, run `/mcp` and select
Patricia. You can also start the OAuth flow from a terminal:

```bash
claude mcp login plugin:patricia:patricia
```

The MCP OAuth sign-in and the hooks' `pat_mcp_` personal token are separate credentials.
OAuth alone does not activate the token-dependent hooks.

Use a token as an alternative when OAuth is not suitable:

```bash
claude mcp add --transport http patricia https://api.patricia.app/v1/mcp \
  --header "Authorization: Bearer $PATRICIA_MCP_TOKEN"
```

A `pat_mcp_` personal token names the accountable person and can write. A `pat_live_` tenant API
key names nobody, so it reads only, and it cannot answer `list_skills` or `list_integrations`.

## Give the local hooks a personal token

Python 3 must be available through the python3 command for the local hooks.

Create a `pat_mcp_` personal key in Patricia under Settings > Developer > Personal keys. Then
choose one setup:

```bash
export PATRICIA_MCP_TOKEN="pat_mcp_..."
```

Or write this file at `~/.claude/patricia.json`:

```json
{
  "token": "pat_mcp_..."
}
```

`PATRICIA_MCP_TOKEN` wins over the file. An empty `PATRICIA_MCP_TOKEN` disables the file fallback.
This behavior is deliberate. It lets a person suspend authenticated hooks without moving the file.

## Local hooks

All five hooks are on by default. An absent config file or an absent hook key leaves them on. A
malformed or unreadable config turns them off. Set a hook's listed key to the literal value `false`
in `~/.claude/patricia-plugin.json` to turn only that hook off.

### Onboarding

- **When and action:** `SessionStart` runs for a new or resumed session. It greets the connected
  person and offers the onboard skill once per project.
- **Cost:** With a token, it makes one `whoami` call. The network timeout is 3 seconds, and the hook
  timeout is 10 seconds.
- **Off switch:** `hooks.onboarding.enabled` set to `false`.
- **Privacy:** With a token, only the authenticated `whoami` request leaves the machine. No prompt,
  transcript, or project content leaves through this hook.

### Recall

- **When and action:** `UserPromptSubmit` runs before each submitted prompt. It skips commands,
  short replies, confirmations, and code-only input. It adds relevant memory to eligible prompts.
- **Cost:** With a token and an eligible prompt, it makes one `search_memory` call. The network
  timeout is 3 seconds, and the hook timeout is 8 seconds.
- **Off switch:** `hooks.recall.enabled` set to `false`.
- **Privacy:** It sends up to 300 characters of the collapsed prompt to Patricia. It sends that text
  only when a token is configured.

### Integrations first

- **When and action:** `UserPromptSubmit` checks a prompt. `PreToolUse` checks `WebFetch`,
  `WebSearch`, and `Bash` input before the tool runs. A local catalog identifies known providers.
- **Cost:** It makes no MCP or network call and needs no token. The hook timeout is 8 seconds for a
  prompt and 5 seconds before a tool call.
- **Off switch:** `hooks.integrations_first.enabled` set to `false`.
- **Privacy:** Nothing leaves the machine. The hook checks the prompt or tool input locally.

### Memory bridge

- **When and action:** `PostToolUse` runs after `Write`, `Edit`, or `MultiEdit`. It notices a saved
  local memory note and proposes `remember` with an explicit scope.
- **Cost:** It makes no MCP or network call. The hook timeout is 5 seconds.
- **Off switch:** `hooks.memory_bridge.enabled` set to `false`. The legacy
  `~/.claude/patricia-memory-bridge.json` file can also set `enabled` to `false`.
- **Privacy:** The script reads the saved note locally and sends nothing over the network. It
  returns the note path and reminder text to Claude Code, without the note content.

### Push reminder

- **When and action:** `Stop` runs when the agent finishes. It proposes `remember` after a local
  memory write or a substantial tool-using session without a memory write to Patricia.
- **Cost:** It makes no MCP or network call. The hook timeout is 8 seconds.
- **Off switch:** `hooks.push_reminder.enabled` set to `false`.
- **Privacy:** It reads at most 5 MB of the local transcript and sends nothing. It only runs when a
  token is configured, so the proposed memory call can succeed after the person agrees.

## Network and credentials

This plugin connects to https://api.patricia.app/v1/mcp over Streamable HTTP.

Patricia uses OAuth 2.1 with PKCE S256. A completed OAuth flow gives the client a personal `pat_mcp_` bearer token.

The plugin manifest contains no credential. The client sends the bearer token to `api.patricia.app` after sign-in.

## Other marketplaces

- Cursor reads `plugin.json` and `mcp.json` from this package.
- OpenAI Codex and ChatGPT read `.codex-plugin/plugin.json`.
- A remote-source entry needs no manifest. xAI reads `.claude-plugin/plugin.json` when present.

All marketplace packages point at the one `skills/` tree in this package.

`assets/icon.png` is a first-party Patricia brand asset.

## The memory bridge proposes; it never writes

A hook is a shell command. It holds no MCP client, it has consent from nobody, and it cannot read
a note and tell a team fact from a private one. A hook that shipped every local note to a shared
workspace would put machine-specific, throwaway and private notes in front of the whole team,
silently. That is the failure mode the bridge is built to avoid, not a feature it postponed.

So the hook does one thing: it injects `hookSpecificOutput.additionalContext` telling the agent
that the note is local only and that `remember` needs a `scope`. The agent decides the scope, asks
its person, and makes the call. The judgement and the write stay in the same place.

Four gates keep it quiet:

| Gate | Effect |
|---|---|
| Either supported config sets the bridge's `enabled` value to `false` | Silent. Without that value, the bridge is on. |
| The written path is outside a memory directory | Silent. |
| The write did not land, or the file is empty | Silent. |
| The note's front matter carries `patricia: skip` | Silent. |

It also offers a given note at most once per session, so a `Write` followed by a run of `Edit`
calls produces one reminder rather than four. That record lives in
`~/.claude/patricia-memory-bridge-state/`, one file per session, pruned after seven days.

It does not use `CLAUDE_PLUGIN_DATA` for it. That variable is present in a hook's environment but
it is not reliably the running plugin's own directory: a project-level hook on this machine saw it
set to `~/.claude/plugins/data/codex-openai-codex`, an unrelated plugin's data directory.

## Which tool a memory write actually uses

Claude Code 2.1.238 declares tools named `memory_list`, `memory_read` and `memory_write`. On the
machines this was built against, memory notes are not written with them: a sweep of the 120 most
recent session transcripts found 49 `Write` and 35 `Edit` calls into
`~/.claude/projects/*/memory/`, and zero `memory_write` calls.

The matcher is therefore `Write|Edit|MultiEdit`. `memory_write` is left out on purpose. Adding a
matcher for a tool whose payload shape has not been verified buys a hook that silently never fires
and reads exactly like one that works. Add it when a real `memory_write` payload has been read.

## Guidance and the server's standing rule are one copy, not two

`start_onboarding_import` may return a `standing_rule_to_offer` carrying `ask_first`, `instruction`
and a `markdown` block sized to fit in somebody else's `CLAUDE.md`. The skill does not restate that
block. It tells the agent to call the tool and use what comes back, so the server stays the single
owner of that wording.

Fetching it at install time was the alternative, and it does not work. A plugin's `SKILL.md` is
static text in a content-addressed cache, there is no install-time step that could rewrite it, and
a plugin whose job includes setting Patricia up cannot depend on a working authenticated Patricia
connection to render its own instructions. Reading the tool at use time gives the same single copy
with none of that.

## Every tool name here is a real tool

Every backticked tool identifier in this plugin is held against the server's own tool registry,
the list the server builds `tools/list` from. The same check asserts that it found a non-empty set
of identifiers, so a broken extractor cannot pass by finding nothing.

Contributor note: that check is `backend/api/tests/test_patricia_claude_plugin.py` in Patricia's
monorepo, and it runs on every change to this plugin.

## Settings and file discovery

| Tool | Use |
|---|---|
| `get_settings` | List settings, or read selected keys or groups with meanings, values, and permissions. Either credential can read workspace groups. |
| `update_settings` | Change one permitted group through the dashboard operation. A personal token is required. |
| `list_files` | List files. The first page includes folders and visibility-filtered counts. |
| `get_brand_kit` | Read brand colors, typography, and logos. |

Use `get_settings(keys=["company_profile"])` for the company profile.
The settings tools share the catalog and operations Patricia uses in chat.
Chat settings changes require a click from the requesting person.
An approval-policy change affects console runs; critical and provider-required actions retain their approval floor, and the audience and click-only floors retain theirs on any action Patricia already asks about.

Integration reads wait while another task runs for the same person.
Poll that task with `get_task_status`, or wait for it to finish.
After a direct integration approval, follow the `next` sentence returned by `decide_approval`.
It names the tool to call again with the same tool_ref and arguments.
