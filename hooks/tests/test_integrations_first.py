"""Tests for the integrations-first prompt and tool reminder."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import integrations_first

from tests._support import FakeMCPServer, HookTestCase


class IntegrationsFirstTests(HookTestCase):
    def payload(self, prompt: str, session: str = "session-one") -> dict[str, object]:
        return {
            "session_id": session,
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
        }

    def tool_payload(self, tool: str, field: str, value: str, session: str) -> dict[str, object]:
        return {
            "session_id": session,
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {field: value},
        }

    def context(
        self,
        payload: dict[str, object],
        *,
        arguments: list[str] | None = None,
        expected_event: str | None = None,
    ) -> str | None:
        result = self.parse_output(
            self.run_hook("integrations_first", payload, arguments=arguments)
        )
        if result is None:
            return None
        specific = result["hookSpecificOutput"]
        assert isinstance(specific, dict)
        event = expected_event or payload.get("hook_event_name")
        if event not in integrations_first.SUPPORTED_EVENTS:
            event = "UserPromptSubmit"
        self.assertEqual(specific["hookEventName"], event)
        return str(specific["additionalContext"])

    def test_prompt_matches_a_name_and_alias_without_matching_inside_a_word(self) -> None:
        name = self.context(self.payload("Please check HUBSPOT for this contact.", "name"))
        alias = self.context(self.payload("Use HubSpot CRM for this lead.", "alias"))
        inside = self.context(self.payload("We are hubspotting the market.", "inside"))

        self.assertIn("HubSpot", name or "")
        self.assertIn("HubSpot", alias or "")
        self.assertIsNone(inside)

    def test_plain_english_does_not_match_short_or_generic_aliases(self) -> None:
        prompts = [
            "Please drive this point home and discuss the meta issue.",
            "Please pick up the slack before the deadline.",
            "Please zoom in on this image before editing it.",
            "The notion uses a linear model, so resend the draft.",
            "Hold this asana while you read the next instruction.",
            "The review caused discord across the whole team.",
            "Use the lobby intercom to contact the front desk.",
            "Add a blue stripe across the top of the image.",
            "Send a telegram to confirm the delivery time.",
            "Resolve the open review threads before the merge.",
            "The birds twitter outside this office each morning.",
        ]

        for index, prompt in enumerate(prompts):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.context(self.payload(prompt, f"plain-{index}")))

    def test_each_app_is_mentioned_once_per_session(self) -> None:
        payload = self.payload("Check HubSpot for the customer.")

        self.assertIsNotNone(self.context(payload))
        self.assertIsNone(self.context(payload))
        self.assertIsNotNone(self.context(self.payload("Check HubSpot again.", "session-two")))

    def test_missing_event_uses_the_prompt_lane(self) -> None:
        payload = self.payload("Check HubSpot for the customer.", "missing-event")
        payload.pop("hook_event_name")

        context = self.context(payload)

        self.assertIn("HubSpot", context or "")

    def test_command_events_override_mismatched_payload_events(self) -> None:
        tool_payload = self.payload("Check HubSpot for the customer.", "explicit-tool")
        tool_payload.update(
            {
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://api.stripe.com/v1/customers"},
            }
        )

        tool_context = self.context(
            tool_payload,
            arguments=["--event", "PreToolUse"],
            expected_event="PreToolUse",
        )
        prompt_payload = self.tool_payload(
            "WebFetch",
            "url",
            "https://api.stripe.com/v1/customers",
            "explicit-prompt",
        )
        prompt_payload["prompt"] = "Check HubSpot for the customer."
        prompt_context = self.context(
            prompt_payload,
            arguments=["--event", "UserPromptSubmit"],
            expected_event="UserPromptSubmit",
        )

        self.assertIn("Stripe", tool_context or "")
        self.assertNotIn("HubSpot", tool_context or "")
        self.assertIn("HubSpot", prompt_context or "")
        self.assertNotIn("Stripe", prompt_context or "")

    def test_state_write_failure_is_silent(self) -> None:
        with mock.patch("patricia_client.write_state", return_value=False):
            context = self.context(self.payload("Check HubSpot for the customer.", "no-state"))

        self.assertIsNone(context)

    def test_webfetch_url_and_wildcard_subdomain_match(self) -> None:
        hubspot = self.context(
            self.tool_payload("WebFetch", "url", "https://api.hubspot.com/crm/v3/objects", "webfetch")
        )
        shopify = self.context(
            self.tool_payload("WebFetch", "url", "https://shop-name.myshopify.com/admin/api", "wildcard")
        )

        self.assertIn("HubSpot", hubspot or "")
        self.assertIn("Shopify", shopify or "")

    def test_prompt_match_does_not_consume_the_tool_reminder(self) -> None:
        session = "prompt-then-tool"

        prompt = self.context(self.payload("Please check HubSpot for this customer.", session))
        tool = self.context(
            self.tool_payload("WebFetch", "url", "https://api.hubspot.com/crm/v3", session)
        )

        self.assertIn("HubSpot", prompt or "")
        self.assertIn("HubSpot", tool or "")

    def test_prompt_opt_out_still_allows_a_host_match(self) -> None:
        context = self.context(
            self.tool_payload("WebFetch", "url", "https://slack.com/api/conversations.list", "slack-host")
        )

        self.assertIn("Slack", context or "")

    def test_bash_and_websearch_extract_hosts(self) -> None:
        stripe = self.context(self.tool_payload("Bash", "command", "curl https://api.stripe.com/v1/customers", "bash"))
        linear = self.context(self.tool_payload("WebSearch", "query", "API docs at api.linear.app/graphql", "search"))

        self.assertIn("Stripe", stripe or "")
        self.assertIn("Linear", linear or "")

    def test_unrelated_host_is_silent(self) -> None:
        context = self.context(self.tool_payload("WebFetch", "url", "https://api.example.org/data", "unrelated"))

        self.assertIsNone(context)

    def test_adversarial_host_input_finishes_before_the_hook_timeout(self) -> None:
        registry = json.loads((integrations_first.CATALOG_PATH.parent / "hooks.json").read_text(encoding="utf-8"))
        timeout = registry["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"]
        started = time.perf_counter()

        integrations_first.extract_hosts("a." * 20000)

        self.assertLess(time.perf_counter() - started, timeout)

    def test_output_never_contains_a_decision_field(self) -> None:
        result = self.parse_output(self.run_hook("integrations_first", self.payload("Use HubSpot.", "shape")))

        self.assertIsNotNone(result)
        assert result is not None
        encoded = json.dumps(result)
        self.assertNotIn("permissionDecision", encoded)
        self.assertNotIn('"decision"', encoded)

    def test_literal_false_disables_the_hook(self) -> None:
        Path(os.environ["PATRICIA_PLUGIN_CONFIG"]).write_text(
            json.dumps({"hooks": {"integrations_first": {"enabled": False}}}),
            encoding="utf-8",
        )

        self.assertIsNone(self.context(self.payload("Use HubSpot.", "disabled")))

    def test_catalog_entries_are_complete_sorted_and_host_only(self) -> None:
        apps = integrations_first.load_apps()
        slugs = [app["slug"] for app in apps]

        self.assertEqual(slugs, sorted(slugs))
        self.assertNotIn("googleads", slugs)
        self.assertIn("windsor_openai_ads", slugs)
        for app in apps:
            with self.subTest(slug=app.get("slug")):
                self.assertIsInstance(app.get("slug"), str)
                self.assertTrue(app["slug"])
                self.assertIsInstance(app.get("name"), str)
                self.assertTrue(app["name"])
                self.assertIsInstance(app.get("hosts"), list)
                self.assertTrue(app["hosts"])
                if "prompt_match" in app:
                    self.assertIsInstance(app["prompt_match"], bool)
                for host in app["hosts"]:
                    self.assertEqual(host, host.casefold())
                    self.assertNotIn("://", host)

        prompt_opt_outs = {app["slug"] for app in apps if app.get("prompt_match") is False}
        self.assertTrue(
            {
                "asana",
                "discord",
                "intercom",
                "linear",
                "notion",
                "resend",
                "slack",
                "stripe",
                "telegram",
                "threads",
                "twitter",
                "zoom",
            }
            <= prompt_opt_outs
        )

    def test_real_script_reminds_without_contacting_the_configured_server(self) -> None:
        response = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"unused": True}}}
        with FakeMCPServer(response) as server:
            completed = self.run_script(
                "integrations_first.py",
                self.payload("Please check HubSpot.", "subprocess"),
                extra_environment={"PATRICIA_MCP_URL": server.url},
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("HubSpot", completed.stdout)
        self.assertEqual(server.requests, [])
