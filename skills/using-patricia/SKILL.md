---
name: using-patricia
description: >-
  Use the Patricia MCP server correctly. Read this before the first Patricia tool call in a
  session, and whenever a Patricia call is refused. Covers the memory scope decision, which read
  tool answers which question, what a personal token may and may not do, and how to hand real work
  over. Triggers on Patricia, patricia MCP, get_task_status, decide_approval, waiting_approval,
  approval, remember, search_memory, list_memories, forget_memory, ask_patricia,
  workspace memory, personal memory, memory scope, create_file, update_file, delete_file,
  create_folder, share_file, publish_publicly, list_skills,
  list_integrations, list_integration_tools, read_integration_data, use_integration_tool,
  disconnect_integration, list_scheduled_tasks, cancel_scheduled_task, scheduled task, reminder,
  disconnect_integration, share_integration, unshare_integration, share_with_team,
  start_onboarding_import, whoami, get_settings, update_settings, pat_mcp, pat_live.
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

A tenant key answers for a workspace and names no person. It cannot write or run tools whose
answers depend on the person holding the credential: `list_skills`, `list_custom_skills`,
`read_custom_skill_file`, `list_integrations`, `list_integration_tools`, `read_integration_data`,
`use_integration_tool`, `get_task_status`, `list_files`, `read_file`, `search_files`, `list_memories`,
`list_scheduled_tasks`, and `start_onboarding_import`. Read a refusal literally. It usually names
the credential, not the tool.

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

## Importing a batch of memory: one `remember` call with `items`

If you already hold this person's memory yourself, for example you are a Claude.ai or ChatGPT
connection asked to bring memory into Patricia, call `remember` with `items`, up to 50 per call.
Pass `scope` once for the call, and `personal` is the right choice for
memory exported from a personal assistant, because it usually describes one person. An item may set
its own `scope` to override the call's. Pass `origin` once per call: `claude`, `chatgpt`, or `other`.

Patricia checks each item against what she already knows and against the rest of the batch, and
skips a near-duplicate she can find rather than storing it twice, so sending the same batch again
with the same scope choices is safe and normally stores nothing new. `start_onboarding_import`
returns `prompt_for_your_own_memory`, a ready-made prompt for exactly this case.

## Ask Patricia before you answer from nothing

- `search_memory` answers a question about the team, its decisions, or its conventions. It is
  semantic, so ask it in plain language.
- `list_memories` lists what is stored, newest first, with an optional substring filter. Reach for
  it when you need to see or audit rows rather than find an answer. It returns `total`, so size the
  job before you page it, and pass `content_chars` to trim each body when you are auditing rather
  than reading: a meeting recap is an ordinary memory row and its body is long.
- `search_memory` and `list_memories` return `facts`, the typed facts Patricia holds about this person.
  Treat these facts as personal. `list_memories` also returns `documents`, the workspace brain document index.
  These lists contain no memory rows, so `forget_memory` does not reach them.
- `search_files` finds an answer in a document. `read_file` opens one.
  `list_files` returns files and includes folders with visibility-filtered counts on the first page, at offset zero.
- `list_skills` and `list_integrations` say what this workspace can already do. Call them before
  you tell somebody their team cannot do something.
- `list_integration_tools` lists the exact connected actions available to this person.
- The two integration tools are split by effect, and each refuses the other's refs.
  `read_integration_data` takes only a `read_only` `tool_ref` and changes nothing.
  `use_integration_tool` takes only a ref that can change data. Both run the action at once and
  answer with `tool_result`, or with an `approval` block when Patricia's approval rules gate the
  call; after the person decides, the same call again runs it.
- `disconnect_integration` disconnects one connected integration. Pass the `account_id` that
  `list_integrations` returns. It needs `confirm_disconnect` set to `true` because it is destructive.
  A person can disconnect their own personal account. An owner or an admin can disconnect any
  account. Only `upstream_confirmed` set to `true` means the provider confirmed the revoke. The
  result's `grant_shared_with_another_connection` value is `true` when another live connection keeps
  the provider grant active. The person must not revoke it by hand when this field is `true`. The
  result's `upstream` value says what the provider did. For `unsupported`, the person should also
  remove Patricia in the app's own settings unless `grant_shared_with_another_connection` is `true`.
- `share_integration` lets the whole company use a personal integration account. Only the person
  who connected the account can share it, and the person needs account-edit authority, which owners
  and admins hold. It needs `share_with_team` set to `true` because it widens who can act through a
  credential. `unshare_integration` makes a shared account private to the person who connected it
  and deletes every other member's auto-run consent on it; the result's `consents_removed` says how
  many. Both return `changed`, which is `false` when the account was already at that visibility.
- `push_custom_skill` sends a local skill folder back: pass the folder name and the whole `SKILL.md`
  text, and the frontmatter supplies the rest, so there is no manifest to write. Pass the
  `expected_version_id` from your last read to update safely. If somebody published since, the push
  is refused and reports the drift rather than overwriting their work. Only an owner or admin can
  push a folder skill, and their push approves the version as it writes it, so `needs_approval` is
  `false` on every push this token can make. A push writes a version and does not enable the skill:
  `installed` says whether the workspace holds an install of it that you can see (a team one, or
  your own personal one), and `next_step_code` names the one act still needed before Patricia runs
  this version for you, with `next_step` as the sentence. The codes are `approve` (the version waits
  on an owner or admin; a personal token's own push never produces it), `enable` (nothing enabled
  it yet), `share` (a teammate's personal install holds the workspace's one slot, so ask them to
  share it with the team), `update` (the workspace runs an earlier version) and `switch_on` (it is
  enabled but paused). Both are null when nothing remains; until then Patricia does not run the
  skill for you and `list_custom_skills` does not list it.
- `list_custom_skills` and `read_custom_skill_file` are for editing a skill LOCALLY. They serve only
  the skills this workspace wrote, so you can pull one into `.claude/skills/<slug>/` and work on it
  here. Every file the listing names comes back as `text`, a `scripts/` file included, so the pulled
  folder is complete; `truncated` is `true` when one read did not hold the whole file. The listing's
  `archetype` says what each skill is: a `skill` is a folder you can push back, and an `instructions`
  skill is one `SKILL.md` written in the dashboard, readable here and edited there. A `SKILL.md` read
  carries `settings`, the workspace's answers to the skill's declared settings as a run reads them,
  and `settings_hidden` counts the rows the settings budget cut. Patricia's own
  catalog is not among them: a slug she ships answers exactly as an unknown one
  does, so do not read a missing answer as a permissions problem or retry it a different way. The
  `detail` on that answer says the same thing: to put a skill Patricia manages to work, call
  `ask_patricia` and name it.
- `get_settings(keys=["company_profile"])` and `list_team_members` answer who this workspace is.
  `get_brand_kit` answers
  what it looks like: colours by role, chart palettes, typography, and logo URLs.
- `list_scheduled_tasks` lists the live reminders and scheduled agent tasks this person created,
  soonest next run first, with `total` so you can size the page. An owner or an admin can pass
  `scope` set to "team" to see every task in the workspace; a member who asks for the team view is
  refused, so call again with "mine". An automation that runs on an approved standing authority is
  not a task and is not listed: call `ask_patricia` to see or stop one.

## Read and change settings

Call `get_settings` without keys to list the settings this credential can read.
Use `get_settings(keys=["approvals"])` to read one group, or pass an exact setting key.
Each row gives its typed value, meaning, choices, bounds, and whether you can change it.
Personal meetings rows name the personal override, workspace default, effective value, and source.
A tenant key reads workspace groups; personal groups appear under refused.

Call `update_settings` with a group and the field names and values to change.
For example, use group `meetings.personal` with changes `{"recap_email_audience": "only_me"}`.
The operation uses the dashboard's permission and validation rules and preserves neighboring settings.
Outreach changes require the dashboard because enabling outreach can send messages.

An approval-policy change affects this person's Patricia chat and console runs.
Critical and provider-required actions keep their approval floor. An action whose name matches the audience rule, or that needs a direct click, keeps its floor on any action Patricia already asks about.
Standing grants and overrides retain their execution identity.
A settings change through Patricia chat needs a click from the requesting person.

## Hand real work over

`ask_patricia` gives Patricia a free-form task and returns a task id. Poll it with
`get_task_status`. When `answer` is a question, call `ask_patricia` again with the reply;
the token's conversation continues. Use `list_integration_tools`, then `read_integration_data` or
`use_integration_tool`, when you
need one exact connected action.

- Call `get_task_status` without `task_id` to list the pending approvals this person may read. The
  list is not a census of approval work: an approved direct call that waits for its retry is not
  listed. A per-fire card for a scheduled write can stay pending while its task runs or after it
  ended. A true `review_available` routes to a review call with `task_id` and `permission_request_id`.
  If `approval.review` is absent, use the answer's current `options`, `option_notes`, and `where`.
  Otherwise show the full arguments before the person chooses, and pass the `document_id` as
  `expected_document_id` for each later slice. Retry `[task_status_unavailable]` and
  `[approval_review_busy]` shortly. An `accepted` decision is queued, not settled; the
  delegating-work skill covers a per-fire card that stays pending after it. A pending per-fire card
  can still be denied after its deadline, until Patricia expires it.
- When `get_task_status` reports `waiting_approval`, or an `approval` block on another status, read
  that `approval` block. The block uses
  `readable` set to `true` for the structured shape and `false` for the prose-only fallback. When it
  is readable, show the person its `tool_label`, `risk_tier`, and `summary`. Before you ask,
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
  only in Patricia. A task-permission offer is decided only in the Patricia dashboard approval queue or the conversation.
  After a direct integration approval, follow the result's `next` sentence.
  Call the named tool again with the same tool_ref and arguments to run it.

The delegating-work skill covers task status and approvals; the integrations skill covers connect,
use, and disconnect.

## Widening who can read something is an act you name

`create_file` adds a workspace file. `share_file` can publish a dated public link, and it takes
`publish_publicly` as a required argument with no default, because the caller has to name the act.
`unshare_file` closes a link by the `link_id` that `share_file` returned.

## Change and remove files

`update_file` changes one file in one call: pass `content` for a new version, `name` to rename it,
or `folder_id` to move it into a folder. Older versions stay readable through `read_file`. A move
into a shared folder is refused with `folder_is_public` and nothing moves, because that move would
publish the file. `share_file` is the one tool that publishes.

`delete_file` moves one file to the trash. It needs a non-blank `reason`, which lands on the audit
record, and it closes every open public link to the file for good. Only an owner or an admin holds
the scope it needs.

`create_folder` makes one empty folder, at the top level or inside `parent_folder_id`. Its result is
one folder from the folders collection in `list_files`.

`forget_memory` removes visible memory. Pass one id, or a bounded list of them to clear a set in one
call. Either form reports every submitted id in `memories` with its own `status` and `reason_code`,
so a partial result is legible. A malformed id, or a list over the bound, refuses the whole call
before anything is forgotten, and one id that cannot be forgotten is refused rather than reported.

`cancel_scheduled_task` retires one scheduled task for good: pass the id that
`list_scheduled_tasks` returned as `task_id`. It is destructive and has no undo, so confirm the task
with the person first. Only an owner or an admin can call it, the same rule the dashboard applies.
When a member is refused, the `detail` names the path that works: `ask_patricia` cancels a task its
creator names, under Patricia's ordinary approval rules. An id that is unknown, already cancelled,
or not visible answers `task_not_found`, and that answer never says whether a hidden task exists.

## When you do not know the tool name

`search_capabilities` returns a short ranked list of tool names, each with a one-line description.
The full description and schema of every tool is already in your tool list. Prefer the search over
guessing a name.

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
| `Stop` | At the end of a substantial turn, the push reminder proposes `remember` for durable facts that are still local. |

An absent config file or an absent hook key leaves each hook on. A malformed or unreadable config
turns the hooks off. Set the matching `hooks.<name>.enabled` key to `false` in
`~/.claude/patricia-plugin.json` to turn one hook off.

The memory bridge skill explains its local-note checks and its legacy off switch. Use the onboard
skill for first-time setup and imports.
