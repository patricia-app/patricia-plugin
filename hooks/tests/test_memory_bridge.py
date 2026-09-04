"""Tests for the default-on local memory bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path

import memory_bridge
import patricia_client

from tests._support import FakeMCPServer, HookTestCase


class MemoryBridgeTests(HookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.memory = self.root / "home" / ".claude" / "projects" / "project-one" / "memory"
        self.memory.mkdir(parents=True)

    def note(self, body: str = "A durable fact") -> Path:
        path = self.memory / "fact.md"
        path.write_text(body, encoding="utf-8")
        return path

    def payload(self, path: Path, session: str = "session-one") -> dict[str, object]:
        return {
            "session_id": session,
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(path)},
            "tool_response": {"filePath": str(path)},
        }

    def context(self, payload: dict[str, object]) -> str | None:
        result = self.parse_output(self.run_hook("memory_bridge", payload))
        if result is None:
            return None
        self.assertEqual(set(result), {"suppressOutput", "hookSpecificOutput"})
        self.assertIs(result["suppressOutput"], True)
        specific = result["hookSpecificOutput"]
        assert isinstance(specific, dict)
        self.assertEqual(specific["hookEventName"], "PostToolUse")
        return str(specific["additionalContext"])

    def test_bridge_is_on_without_any_config_file(self) -> None:
        note = self.note()

        context = self.context(self.payload(note))

        self.assertIn(str(note), context or "")
        self.assertIn("`remember`", context or "")

    def test_legacy_config_literal_false_turns_the_bridge_off(self) -> None:
        Path(os.environ["PATRICIA_MEMORY_BRIDGE_CONFIG"]).write_text('{"enabled":false}', encoding="utf-8")

        self.assertIsNone(self.context(self.payload(self.note())))

    def test_plugin_config_literal_false_turns_the_bridge_off(self) -> None:
        Path(os.environ["PATRICIA_PLUGIN_CONFIG"]).write_text(
            json.dumps({"hooks": {"memory_bridge": {"enabled": False}}}),
            encoding="utf-8",
        )

        self.assertIsNone(self.context(self.payload(self.note())))

    def test_present_malformed_config_turns_the_bridge_off(self) -> None:
        paths = [
            Path(os.environ["PATRICIA_MEMORY_BRIDGE_CONFIG"]),
            Path(os.environ["PATRICIA_PLUGIN_CONFIG"]),
        ]
        for index, path in enumerate(paths):
            with self.subTest(path=path):
                path.write_text("not json", encoding="utf-8")
                self.assertIsNone(self.context(self.payload(self.note(), f"malformed-{index}")))
                path.unlink()

    def test_tilde_paths_match_the_shared_client_resolution(self) -> None:
        home = self.root / "home"
        config = home / ".claude" / "patricia-plugin.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps({"hooks": {"memory_bridge": {"enabled": False}}}),
            encoding="utf-8",
        )
        os.environ["PATRICIA_PLUGIN_CONFIG"] = "~/.claude/patricia-plugin.json"
        os.environ["PATRICIA_MEMORY_BRIDGE_STATE"] = (
            "~/.claude/patricia-memory-bridge-state"
        )

        self.assertFalse(patricia_client.hook_enabled("memory_bridge"))
        self.assertIsNone(self.context(self.payload(self.note(), "tilde-config")))
        self.assertEqual(
            memory_bridge.state_file("tilde-state"),
            home / ".claude" / "patricia-memory-bridge-state" / "tilde-state.patricia-session",
        )

    def test_non_false_values_leave_the_bridge_on(self) -> None:
        Path(os.environ["PATRICIA_MEMORY_BRIDGE_CONFIG"]).write_text('{"enabled":"false"}', encoding="utf-8")
        Path(os.environ["PATRICIA_PLUGIN_CONFIG"]).write_text(
            json.dumps({"hooks": {"memory_bridge": {"enabled": 0}}}),
            encoding="utf-8",
        )

        self.assertIsNotNone(self.context(self.payload(self.note())))

    def test_skip_marker_stays_silent(self) -> None:
        note = self.note("---\npatricia: skip\n---\n\nPrivate fact\n")

        self.assertIsNone(self.context(self.payload(note)))

    def test_note_is_offered_once_per_session(self) -> None:
        note = self.note()
        payload = self.payload(note)

        self.assertIsNotNone(self.context(payload))
        self.assertIsNone(self.context(payload))
        self.assertIsNotNone(self.context(self.payload(note, "session-two")))

        record = memory_bridge.state_file("session-one")
        assert record is not None
        self.assertEqual(record.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)

    def test_state_write_refuses_a_precreated_symlink(self) -> None:
        note = self.note()
        record = memory_bridge.state_file("symlink-session")
        assert record is not None
        target = self.root / "target-state"
        target.write_text("unchanged", encoding="utf-8")
        record.symlink_to(target)

        context = self.context(self.payload(note, "symlink-session"))

        self.assertIsNotNone(context)
        self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")

    def test_real_script_stays_local_while_it_emits_the_nudge(self) -> None:
        note = self.note()
        response = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"unused": True}}}
        with FakeMCPServer(response) as server:
            completed = self.run_script(
                "memory_bridge.py",
                self.payload(note, "subprocess"),
                extra_environment={"PATRICIA_MCP_URL": server.url},
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(str(note), completed.stdout)
        self.assertEqual(server.requests, [])
