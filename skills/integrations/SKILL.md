---
name: integrations
description: >-
  Find, connect, use, or disconnect Patricia integrations. Use when a person asks what is connected,
  asks Patricia to work through an integration, needs a connection link, or confirms an account
  disconnection. Triggers on integrations, connected accounts, connect an app, disconnect an app,
  account id, and use a connected tool.
---

# Integrations

## See connected accounts

Call `list_integrations` before you use or disconnect an integration. Each account includes an
`account_id`. Use that UUID for account-specific actions.

## Use an integration

Call `ask_patricia` with the required outcome and the integration name. Patricia uses the connected
account through her delegated run. Follow the delegating-work skill for task status and approvals.

## Connect an integration

1. Call `ask_patricia` and ask Patricia to connect the named integration for this person only, or for the team.
2. Poll `get_task_status` as the delegating-work skill describes. Read the connect link from `answer`.
   If `answer` asks whether the connection is personal or team-wide, ask the person and call `ask_patricia` again.
3. Ask the person to open that link and finish the provider flow.
4. Call `list_integrations` to confirm the connection.

## Disconnect an integration

1. Call `list_integrations` and identify the exact account.
2. Show the person the integration and account label.
3. Ask the person to confirm the disconnection in words.
4. Wait for the confirmation.
5. Call `disconnect_integration` with the selected `account_id` and set `confirm_disconnect` to true.

`confirm_disconnect` is a required `StrictBool` with no default. Set it to `true` only after the
person confirms in words. The `confirmation_required` refusal fires when `confirm_disconnect` is
not `true`.

Do not infer confirmation from an earlier request. Do not select another account without the
person's direction.

## Read a successful disconnect

- `account_id` identifies the disconnected Patricia account.
- `integration` gives the provider and app. It can be null for another person's private connection.
  It can also be null when Patricia cannot verify the current state.
- `disconnected` is always true after a successful local disconnect. The local disconnect is durable.
- `superseded` is true when the account was reconnected after the disconnect and is active again.
- `state_verified` is false when Patricia cannot read the current state. Then `superseded` and
  `integration` are null.
- `grant_shared_with_another_connection` is true when another live connection keeps the provider
  grant active. The person must not revoke the grant by hand when this field is true.
- `upstream` is one of `revoked`, `unsupported`, `pending`, or `adapter_error`.
- `upstream_confirmed` is true only when `upstream` is `revoked`.
- `note` appears only when there is something the person must know.

Tell the person what the `upstream` value means:

- For `revoked`, say that the provider confirmed the revoke.
- For `unsupported`, check `grant_shared_with_another_connection`. If it is true, say that another
  connection keeps the provider grant active. Otherwise, tell the person to remove Patricia in the
  app's own settings.
- For `pending`, say that the provider revoke is pending and may be retried.
- For `adapter_error`, report the adapter error. Say that a retry with the same input does not change it.

## Read disconnect refusals

The server prefixes each refusal with its bracketed code.

- `confirmation_required` (`[confirmation_required]`) means `confirm_disconnect` was not true.
  Nothing was disconnected. Ask the person to confirm in words before another call.
- `managed_account` (`[managed_account]`) means Patricia manages this integration. It cannot be
  disconnected here.
- `not_your_account` (`[not_your_account]`) means a member can disconnect only a personal account
  they connected. An owner or an admin can disconnect any account.
- `account_not_found` (`[account_not_found]`) means the account can be unknown or not visible to this
  person. It can also be disconnected or inactive. Call `list_integrations` and check the `account_id`.

Report the refusal. Do not try another account without the person's direction.
