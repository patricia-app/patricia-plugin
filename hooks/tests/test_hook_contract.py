"""Cross-hook configuration, style, and output-shape tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from tests._support import HOOKS_DIRECTORY, HOOK_MODULES, HookTestCase


class HookContractTests(HookTestCase):
    def test_hook_registry_has_the_required_commands_matchers_and_timeouts(self) -> None:
        registry = json.loads((HOOKS_DIRECTORY / "hooks.json").read_text(encoding="utf-8"))
        hooks = registry["hooks"]

        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "WebFetch|WebSearch|Bash")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Write|Edit|MultiEdit")

        expected = {
            "onboarding.py": 10,
            "recall.py": 8,
            "integrations_first.py": {5, 8},
            "memory_bridge.py": 5,
            "push_reminder.py": 8,
        }
        found: dict[str, set[int]] = {}
        for event, groups in hooks.items():
            for group in groups:
                for handler in group["hooks"]:
                    script_path, _quote, arguments = handler["command"].split(
                        "/hooks/", 1
                    )[1].partition('"')
                    script = Path(script_path).name
                    found.setdefault(script, set()).add(handler["timeout"])
                    self.assertEqual(handler["type"], "command")
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", handler["command"])
                    if script == "integrations_first.py":
                        self.assertEqual(arguments.split(), ["--event", event])
                    else:
                        self.assertEqual(arguments, "")

        for script, timeouts in expected.items():
            expected_timeouts = timeouts if isinstance(timeouts, set) else {timeouts}
            self.assertEqual(found[script], expected_timeouts)

        description = registry["description"]
        self.assertIn("propose actions and never write", description)
        self.assertIn("~/.claude/patricia-plugin.json", description)
        self.assertIn("only recall sends prompt text", description)

    def test_every_text_file_under_hooks_contains_no_em_dash(self) -> None:
        offenders = [
            str(path.relative_to(HOOKS_DIRECTORY))
            for path in HOOKS_DIRECTORY.rglob("*")
            if path.is_file() and path.suffix in {".py", ".json"} and chr(0x2014) in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(offenders, [])

    def test_every_hook_emits_nothing_or_one_json_object_for_each_payload(self) -> None:
        payloads: list[object] = [
            None,
            [],
            {},
            {
                "session_id": "shape-session-start",
                "hook_event_name": "SessionStart",
                "cwd": "/projects/shape-start",
                "source": "startup",
            },
            {
                "session_id": "shape-prompt",
                "hook_event_name": "UserPromptSubmit",
                "cwd": "/projects/shape-prompt",
                "prompt": "Please check HubSpot for this customer account.",
            },
            {
                "session_id": "shape-tool",
                "hook_event_name": "PreToolUse",
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://api.hubspot.com/crm/v3"},
            },
            {
                "session_id": "shape-stop",
                "hook_event_name": "Stop",
                "transcript_path": "/missing/transcript.jsonl",
                "stop_hook_active": False,
            },
        ]

        for module_name in HOOK_MODULES:
            for index, payload in enumerate(payloads):
                with self.subTest(module=module_name, payload=index):
                    output = self.run_hook(module_name, payload)
                    if output.strip():
                        parsed = json.loads(output)
                        self.assertIsInstance(parsed, dict)

    def test_every_hook_exits_zero_when_its_output_fails(self) -> None:
        for module_name in ("onboarding", "recall", "integrations_first", "push_reminder"):
            module = HOOK_MODULES[module_name]
            payload = {"hook_event_name": "UserPromptSubmit"} if module_name == "integrations_first" else {}
            with (
                self.subTest(module=module_name),
                mock.patch.object(module, "decide", return_value="context"),
                mock.patch("patricia_client.emit", side_effect=OSError("closed output")),
            ):
                self.assertEqual(self.run_hook(module_name, payload), "")

        memory_bridge = HOOK_MODULES["memory_bridge"]
        with (
            mock.patch.object(memory_bridge, "decide", return_value="context"),
            mock.patch.object(memory_bridge.json, "dump", side_effect=OSError("closed output")),
        ):
            self.assertEqual(self.run_hook("memory_bridge", {}), "")
