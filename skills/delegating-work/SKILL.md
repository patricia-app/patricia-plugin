---
name: delegating-work
description: >-
  Delegate work to Patricia and track it through completion. Use when a task needs Patricia,
  task-status polling, a human approval decision, or help with a result that has not started or
  was cut short. Triggers on delegate to Patricia, ask Patricia, task status, waiting approval,
  approve, deny, approve this run, always approve this tool, and truncated task answer.
---

# Delegating work

Use `ask_patricia` when Patricia must use a skill, an integration, or workspace context to do the work.

## Start and poll the task

1. Call `ask_patricia` with the complete task.
2. Read the returned `task_id`.
3. Call `get_task_status` with that task identifier.
4. Continue polling while the status is `queued`, `running`, `waiting_approval`, or `suspended`.

When a `queued` status carries `blocked_by`, show its `message` to the person.

Every other status is terminal.

A `status` of `not_started` is terminal. The task did not start. If the result has `answered_by`, another task took the request. Poll the task in `answered_by.task_id` and do not repeat the request. Otherwise call `ask_patricia` again with the same request.

The `answer` field carries Patricia's result. `answer_truncated` means the answer was cut at the
server's bound. Ask Patricia for the rest or a shorter answer.

## Handle a waiting approval

When `status` is `waiting_approval`, read the `approval` block before you reply.

A structured block has `readable` set to `true` and contains these fields:

| Field | Meaning |
|---|---|
| `permission_request_id` | The pending approval identifier. |
| `tool_name` | The server's tool name. |
| `tool_label` | The human-readable tool label. |
| `risk_tier` | The action's risk tier. |
| `integration` | The integration label, when available. |
| `summary` | The plain-language question the approval asks. |
| `args_digest` | The current argument digest for the decision call. |
| `expires_at` | The decision deadline. |
| `where` | The Patricia location for a manual decision. |
| `options` | The decisions this connection may offer. |
| `option_notes` | The reasons that other decisions are unavailable. |

A prose-only block has `readable` set to `false`. It contains only `readable`, `where`, and
`request`. Show the person the `request` text. Send the person to `where`. Do not call
`decide_approval` from this block.

For a structured block, use this sequence:

1. Show the person `tool_label`, `risk_tier`, `integration`, `summary`, and `expires_at`.
2. Show the person each listed option and its `option_notes` entry when present.
3. Offer exactly the choices in `options`.
4. Wait for the person to select a choice.
5. Call `decide_approval(permission_request_id, decision, args_digest)` with the selected choice.
6. Continue polling with `get_task_status`.

Do not add, remove, rename, or select an approval choice. Never decide on the person's behalf.

`options` can be empty. Send the person to `where` when it is empty.

- `approve` approves the current call.
- `deny` rejects the current call.
- `approve_run` approves once and requests a grant for eligible calls during this run.
- `approve_tool_always` approves once and requests a durable grant for this tool.

The decision result contains these fields:

- `accepted` says that the asynchronous decision was accepted for processing.
- `grant_requested` identifies a run grant, a tool grant, or no grant.
- `grant_eligible` is a provisional pre-read. It is never a grant receipt.
- `grant_note` explains the grant result.

## Read decision refusals

- `[approval_not_found]` means the approval request is not available to this connection.
- `[approval_scope_required]` means this credential's role does not grant `runs:execute`.
- `[not_your_decision]` means this connection cannot decide the request. Send the person to `where`.
- `[approval_expired]` means the request expired. Ask Patricia again to restart the work.
- `[already_resolved]` means another decision reached the request. Poll the task before another action.
- `[decision_needs_patricia]` means a critical request can be decided only in Patricia. Send the person to `where`.
- `[run_actor_not_connection_owner]` means the requester cannot use the action's personal connection.
- `[approval_context_changed]` means the request changed. Call `get_task_status` and show the new request.

Report the refusal. Do not replace the person's choice or retry a different decision.
