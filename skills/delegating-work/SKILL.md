---
name: delegating-work
description: >-
  Delegate work to Patricia and track it through completion. Use when a task needs Patricia,
  task-status polling, a human approval decision, or help with a result that has not started or
  was cut short. Triggers on delegate to Patricia, ask Patricia, task status, waiting approval,
  pending approvals, review a scheduled write, approve, deny, approve this run, always approve this
  tool, and truncated task answer.
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

A task can close with a write that still waits for a person. `pending_effect_at_close` says so, and
`deferred_effect_status` says what became of that write.

## Find pending approvals

Call `get_task_status` without `task_id` to list the pending approvals this person may read. The
result has `approvals`, `total`, `limit`, and `offset`. Each item has `task_id`, `run_id`, `status`,
and an `approval` block. The newest card comes first. Use `offset` for the next page.

The list is not a census of approval work. An approved direct integration call that waits for its
retry is not pending, so the list leaves it out. `get_task_status` on its task returns `next`.

## Handle a pending approval

When `status` is `waiting_approval`, read the `approval` block before you reply. A per-fire card is a
scheduled write that waits for a person. Its block can also appear while its task runs or after the
task ended, and the task keeps its own `status`.

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
| `approval_kind` | `per_fire` for a scheduled write, `ordinary` for any other card. |
| `review_available` | `true` routes to the explicit review call; it does not promise a complete document. |
| `review_coordinates` | The `task_id`, `permission_request_id`, and `action_id` of that review. |

A prose-only block has `readable` set to `false`. It contains only `readable`, `where`, and
`request`. Show the person the `request` text. Send the person to `where`. Do not call
`decide_approval` from this block.

For a structured block, use this sequence:

1. Show the person `tool_label`, `risk_tier`, `integration`, `summary`, and `expires_at`.
2. When `review_available` is `true`, read and show the full arguments as described below.
3. Show the person each listed option and its `option_notes` entry when present.
4. Offer exactly the choices in `options`.
5. Wait for the person to select a choice.
6. Call `decide_approval(permission_request_id, decision, args_digest)` with the selected choice.
7. Continue polling with `get_task_status`.

Do not add, remove, rename, or select an approval choice. Never decide on the person's behalf.

`options` can be empty. Send the person to `where` when it is empty.

- `approve` approves the current call.
- `deny` rejects the current call.
- `approve_run` approves once and requests a grant for eligible calls during this run.
- `approve_tool_always` approves once and requests a durable grant for this tool.

The decision result contains these fields:

- `accepted` says that the asynchronous decision was accepted for processing. It is not the outcome.
- `grant_requested` identifies a run grant, a tool grant, or no grant.
- `grant_eligible` is a provisional pre-read. It is never a grant receipt.
- `grant_note` explains the grant result.

A pending per-fire card can still be denied after `expires_at`, until Patricia expires it. Approving
it after that time answers `[approval_expired]`.

## Read the full arguments of a scheduled write

A plain poll and the pending list carry no `review`. When `review_available` is `true`:

1. Call `get_task_status` with the `task_id` and `permission_request_id` from `review_coordinates`.
2. If `approval.review` is absent, use this answer's current `options`, `option_notes`, and `where`.
   Otherwise read its `details`, with `label`, `text`, `part`, and `parts`.
   It also has `total`, `limit`, `offset`, `truncated`, `args_digest`, and `document_id`.
3. While `truncated` is `true`, call again with the next `offset` and with `expected_document_id` set
   to the `document_id` you hold.
4. Show the person every entry before you offer the options.

`[approval_context_changed]` means the document changed. Start again at offset 0 and show the new
content. `[task_status_unavailable]` means Patricia could not read the task now. Try again shortly.
An exact-form `[task_not_found]` means this connection cannot read that card as pending now.
Poll with `task_id` alone and keep polling the task.

## Send a per-fire decision again

Patricia can set aside an accepted decision on a per-fire card while that card is still being posted
to chat. Patricia does not send the decision again by itself.

After an accepted per-fire decision, wait a short time.
Poll `get_task_status` with the same `task_id` and `permission_request_id`.
If the card stays pending, compare its `args_digest` with the one used for the decision.
If this poll and the read before the decision both returned a review, compare its `document_id` too.
When they match, send the same decision again.
Do this at most 2 more times.
If that poll answers `[task_not_found]`, stop and poll with `task_id` alone. Report what that answer shows.
If the digest or document changed, or a resend answers `[approval_expired]`, report that without sending the previous decision again.
If the card is still pending after the last retry, tell the person the outcome is not confirmed.
Never change the person's choice.

## Read decision refusals

- `[approval_not_found]` means the approval request is not available to this connection.
- `[approval_scope_required]` means this credential's role does not grant `runs:execute`.
- `[not_your_decision]` means this connection cannot decide the request. Send the person to `where`.
- `[approval_expired]` means the request expired. Ask Patricia again to restart the work.
- `[already_resolved]` means another decision reached the request. Poll the task before another action.
- `[decision_needs_patricia]` means a critical request, or a per-fire write whose complete arguments
  cannot be shown here, can be decided only in Patricia. Send the person to `where`.
  A task-permission offer is decided only in the Patricia dashboard approval queue or the conversation.
  A click-only card is approved only on its card or in the dashboard; you can deny it here.
- `[run_actor_not_connection_owner]` means the requester cannot use the action's personal connection.
- `[approval_context_changed]` means the request changed. Call `get_task_status` and show the new request.
- `[approval_review_busy]` means the check before a per-fire approval is busy. Nothing was decided.
  Try the same decision again shortly.

Report the refusal. Do not replace the person's choice or retry a different decision.
