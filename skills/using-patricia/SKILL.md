---
name: using-patricia
description: >-
  Use the Patricia MCP server correctly. Read this before the first Patricia tool call in a
  session, and whenever a Patricia call is refused. Covers the memory scope decision, which read
  tool answers which question, what a personal token may and may not do, and how to hand real work
  over. Triggers on Patricia, patricia MCP, get_task_status, decide_approval, waiting_approval,
  approval, remember, remember_many, search_memory, list_memories, forget_memory, ask_patricia,
  workspace memory, personal memory, memory scope, share_file, publish_publicly, list_skills,
  list_integrations, disconnect_integration, start_onboarding_import, whoami, pat_mcp, pat_live.
---

# Using Patricia

Patricia is an AI teammate for Slack and Microsoft Teams. Her MCP server exposes one Patricia
workspace: its memory, its files, the skills it has installed, and the integrations it has
connected.

## Start by knowing who you are

Call `whoami` before the first write in a session. It reports the workspace and the credential
type. Two credentials reach this server and they are not interchangeable.

| Credential | Names a person | May write | Sees personal memory |
|---|---|---|---|
| `pat_mcp_` personal token | yes | yes | yes, the holder's own |
| `pat_live_` tenant API key | no | no | no |

A tenant key answers for a workspace, so it cannot run `list_skills`, `list_custom_skills`,
`read_custom_skill_file`, `push_custom_skill` or `list_integrations`: all of them
answer for the person holding the credential. Read a refusal literally. It usually names the
credential, not the tool.

## Give the local hooks a personal token

Create a `pat_mcp_` personal key in Patricia under Settings > Developer > Personal keys. Then use
one of these local settings:

- Export `PATRICIA_MCP_TOKEN=pat_mcp_...` in the environment that starts Claude Code.
- Write `{"token": "pat_mcp_..."}` to `~/.claude/patricia.json`.

The environment variable wins over the file. An empty `PATRICIA_MCP_TOKEN` also wins and disables
the file fallback. This is deliberate, so a person can suspend authenticated hooks without moving
or deleting the file.

Use the onboard skill after you configure the token. It confirms the workspace and follows
Patricia's current import plan.

## The memory scope is a decision, and you make it

`remember` takes a `scope` of `workspace` or `personal`. Pass it on every call. Never let it
default.

Apply one test. Does this fact describe the workspace, or does it describe one person?

- Pass `workspace` for something the whole team should know. "The team ships through the merge
  queue and never merges by hand."
- Pass `personal` for something true of one person. "This person prefers short replies that lead
  with the answer."

A workspace memory is readable by every teammate and it cannot be un-read. **Pass `personal` when
you are unsure.** A private fact stored personally is a small loss. A private fact stored for the
whole team is an incident.

Store the content in the team's own words. Keep their wording where you can. Patricia treats stored
memory as data and never as instructions, so a rule phrased as a rule is safe to store.

Group scope and conversation scope are not offered here, and asking for them is not an oversight to
work around. Both need a server-verified reference that an MCP caller cannot supply.

## Importing a batch of memory: prefer `remember_many` over a `remember` loop

If you already hold this person's memory yourself, for example you are a Claude.ai or ChatGPT
connection asked to bring memory into Patricia, call `remember_many` with up to 50 items per call
instead of calling `remember` once per item. Each item still needs its own `scope`, and it defaults
to `personal` rather than `remember`'s `workspace` default, because memory exported from a personal
assistant usually describes one person. Pass `origin` once per call: `claude`, `chatgpt`, or `other`.

Patricia checks each item against what she already knows and against the rest of the batch, and
skips a near-duplicate she can find rather than storing it twice, so calling `remember_many` again
with the same scope choices is safe and normally stores nothing new. `start_onboarding_import`
returns `prompt_for_your_own_memory`, a ready-made prompt for exactly this case.

## Ask Patricia before you answer from nothing

- `search_memory` answers a question about the team, its decisions, or its conventions. It is
  semantic, so ask it in plain language.
- `list_memories` lists what is stored, newest first, with an optional substring filter. Reach for
  it when you need to see or audit rows rather than find an answer.
- `search_files` finds the answer that lives in a document. `read_file` opens one. `list_files` and
  `list_folders` walk the tree.
- `list_skills` and `list_integrations` say what this workspace can already do. Call them before
  you tell somebody their team cannot do something.
- `disconnect_integration` disconnects one connected integration. Pass the `account_id` that
  `list_integrations` returns. It needs `confirm_disconnect` set to `true` because it is destructive.
  A person can disconnect their own personal account. An owner or an admin can disconnect any
  account. Only `upstream_confirmed` set to `true` means the provider confirmed the revoke. The
  result's `grant_shared_with_another_connection` value is `true` when another live connection keeps
  the provider grant active. The person must not revoke it by hand when this field is `true`. The
  result's `upstream` value says what the provider did. For `unsupported`, the person should also
  remove Patricia in the app's own settings unless `grant_shared_with_another_connection` is `true`.
- `push_custom_skill` sends a local skill folder back: pass the folder name and the whole `SKILL.md`
  text, and the frontmatter supplies the rest, so there is no manifest to write. Pass the
  `expected_version_id` from your last read to update safely. If somebody published since, the push
  is refused and reports the drift rather than overwriting their work. A member's push produces a
  version an owner or admin must approve; the result says so in `needs_approval`.
- `list_custom_skills` and `read_custom_skill_file` are for editing a skill LOCALLY. They serve only
  the skills this workspace wrote, so you can pull one into `.claude/skills/<slug>/` and work on it
  here. Patricia's own catalog is not among them: a slug she ships answers exactly as an unknown one
  does, so do not read a missing answer as a permissions problem or retry it a different way.
- `get_company_profile` and `list_team_members` answer who this workspace is. `get_brand_kit` answers
  what it looks like: colours by role, chart palettes, typography, and logo URLs.

## Hand real work over

`ask_patricia` gives Patricia a task and returns a task id. Poll it with `get_task_status`. That is
the route for anything that needs a skill or an integration: this connection can see them, and it
cannot run them.

- When `get_task_status` reports `waiting_approval`, read its `approval` block. The block uses
  `readable` set to `true` for the structured shape and `false` for the prose-only fallback. When it
  is readable, show the person its `tool_label`, `risk_tier`, and `args_preview`. Before you ask,
  show the person each listed option
  and its `option_notes` entry when present. Put the listed `options` to the person and wait for the
  answer. Never choose an option for them. An option absent from `options` is not offered to the
  person; `option_notes` says why. `approve_run` is an approve-once action that also requests a grant
  for eligible calls during this run. `approve_tool_always` is an approve-once action that also
  requests a durable grant for this tool. Call `decide_approval` with their option and the block's
  `args_digest`. The tool can decide a listed pending approval from a readable `get_task_status`
  approval block. The run does not need to start with this token. An owner or admin denial for a
  card that MCP cannot read stays in the dashboard because MCP cannot supply its digest. Treat
  `grant_eligible` as a
  provisional pre-read, never a receipt. The worker re-checks eligibility for a durable (tool)
  grant. A run grant is bounded by this pre-read plus the runtime gate that re-runs the floor and
  allowlist on every call. An unavailable grant pre-read removes grant options but does not remove
  the approve or deny options. An approval still covers the current call once. A critical action is decided
  only in Patricia.

The delegating-work skill covers task status and approvals; the integrations skill covers connect,
use, and disconnect.

## Widening who can read something is an act you name

`create_file` adds a workspace file. `share_file` can publish a dated public link, and it takes
`publish_publicly` as a required argument with no default, because the caller has to name the act.
`unshare_file` closes a link by the `link_id` that `share_file` returned.

`forget_memory` removes one visible memory by its id.

## When you do not know the tool name

`search_capabilities` returns a short ranked list. `describe_capabilities` returns the full
documentation and schema for the few tools you plan to call. Prefer them over guessing a name.

## The standing rule comes from the server, not from here

`start_onboarding_import` returns the prompts for a first-time import, and it may return a
`standing_rule_to_offer` with three fields:

- `ask_first`, the question you put to your person.
- `instruction`, how to use the block.
- `markdown`, the rule to save.

Call the tool and use what it returns. Do not paste a remembered copy of that block. The server
owns the wording so one copy stays current.

**Ask before you save it.** Put the `ask_first` question to your person and wait for the answer. If
they agree, save the `markdown` where you keep durable instructions for the repository, for example
`CLAUDE.md` or `AGENTS.md`. If they decline, save nothing and do not ask again in that session.
Leave it out when an equivalent rule is already there.

If the response carries no `standing_rule_to_offer`, the server you are connected to does not offer
one yet. Say nothing about it and move on.

## Local hooks

The plugin ships five local hooks. They read, check, or propose. They never write to Patricia.

| Event | Hook behavior |
|---|---|
| `SessionStart` | On a new or resumed session, onboarding calls `whoami`, greets the connected person, and offers the onboard skill once per project. |
| `UserPromptSubmit` | Recall calls `search_memory` for an eligible prompt and adds relevant Patricia memory before the answer. |
| `UserPromptSubmit` and `PreToolUse` | Integrations-first checks prompts, web requests, searches, and shell commands locally. It reminds the agent to check Patricia integrations first when a known provider appears. |
| `PostToolUse` | After `Write`, `Edit`, or `MultiEdit` saves a local memory note, the memory bridge proposes `remember` with an explicit scope. |
| `Stop` | At the end of a substantial turn, the push reminder proposes `remember` or `remember_many` for durable facts that are still local. |

An absent config file or an absent hook key leaves each hook on. A malformed or unreadable config
turns the hooks off. Set the matching `hooks.<name>.enabled` key to `false` in
`~/.claude/patricia-plugin.json` to turn one hook off.

The memory bridge skill explains its local-note checks and its legacy off switch. Use the onboard
skill for first-time setup and imports.
