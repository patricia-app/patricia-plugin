"""Tests for the Patricia durable-fact stop reminder."""

from __future__ import annotations

import json
import os
from pathlib import Path

import push_reminder

from tests._support import FakeMCPServer, HookTestCase


def _tool_use(name: str = "Read", tool_input: dict[str, object] | None = None) -> dict[str, object]:
    return {"type": "tool_use", "name": name, "input": tool_input or {}}


class PushReminderTests(HookTestCase):
    def transcript(self, tool_uses: list[dict[str, object]], name: str = "transcript.jsonl") -> Path:
        path = self.root / name
        entries = [{"type": "assistant", "message": {"content": [tool_use]}} for tool_use in tool_uses]
        path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
        return path

    def payload(
        self,
        transcript: Path,
        *,
        session: str = "session-one",
        active: bool = False,
    ) -> dict[str, object]:
        return {
            "session_id": session,
            "transcript_path": str(transcript),
            "cwd": str(self.root),
            "hook_event_name": "Stop",
            "stop_hook_active": active,
            "last_assistant_message": "Finished.",
        }

    def context(self, payload: dict[str, object]) -> str | None:
        result = self.parse_output(self.run_hook("push_reminder", payload))
        if result is None:
            return None
        specific = result["hookSpecificOutput"]
        assert isinstance(specific, dict)
        self.assertEqual(specific["hookEventName"], "Stop")
        return str(specific["additionalContext"])

    def test_stop_hook_active_is_silent(self) -> None:
        self.write_token()
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS)])

        self.assertIsNone(self.context(self.payload(transcript, active=True)))

    def test_without_a_token_the_hook_is_silent(self) -> None:
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS)])

        self.assertIsNone(self.context(self.payload(transcript)))

    def test_short_session_without_a_memory_write_is_silent(self) -> None:
        self.write_token()
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS - 1)])

        self.assertIsNone(self.context(self.payload(transcript)))

    def test_twelve_tool_calls_without_remember_fire(self) -> None:
        self.write_token()
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS)])

        context = self.context(self.payload(transcript))

        self.assertIn("facts worth keeping", context or "")
        self.assertNotIn("local memory note", context or "")

    def test_mcp_prefixed_remember_suppresses_the_long_session_case(self) -> None:
        self.write_token()
        tools = [_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS - 1)]
        tools.append(_tool_use("mcp__patricia__remember"))
        transcript = self.transcript(tools)

        self.assertIsNone(self.context(self.payload(transcript)))

    def test_a_late_remember_call_is_read_after_the_transcript_boundary(self) -> None:
        self.write_token()
        early_entries = [
            {"type": "assistant", "message": {"content": [_tool_use()]}}
            for _ in range(push_reminder.MIN_TOOL_CALLS)
        ]
        padding = {"type": "padding", "value": "x" * push_reminder.MAX_TRANSCRIPT_BYTES}
        late_remember = {
            "type": "assistant",
            "message": {"content": [_tool_use("mcp__patricia__remember")]},
        }
        transcript = self.root / "long-transcript.jsonl"
        transcript.write_text(
            "\n".join(
                json.dumps(entry)
                for entry in [*early_entries, padding, late_remember]
            ),
            encoding="utf-8",
        )

        self.assertIsNone(self.context(self.payload(transcript, session="tail")))

    def test_memory_directory_write_fires_regardless_of_tool_count(self) -> None:
        self.write_token()
        note = self.root / "home" / ".claude" / "projects" / "project-one" / "memory" / "fact.md"
        note.parent.mkdir(parents=True)
        note.write_text("A fact", encoding="utf-8")
        transcript = self.transcript([_tool_use("Write", {"file_path": str(note)})])

        context = self.context(self.payload(transcript))

        self.assertIn("local memory note", context or "")

    def test_reminder_fires_once_per_session(self) -> None:
        self.write_token()
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS)])
        payload = self.payload(transcript)

        self.assertIsNotNone(self.context(payload))
        self.assertIsNone(self.context(payload))
        self.assertIsNotNone(self.context(self.payload(transcript, session="session-two")))

    def test_missing_and_malformed_transcripts_are_tolerated(self) -> None:
        self.write_token()
        missing = self.root / "missing.jsonl"
        malformed = self.root / "malformed.jsonl"
        malformed.write_text("not json\n[]\n{}\n", encoding="utf-8")

        self.assertIsNone(self.context(self.payload(missing, session="missing")))
        self.assertIsNone(self.context(self.payload(malformed, session="malformed")))

    def test_literal_false_disables_the_hook(self) -> None:
        self.write_token()
        Path(os.environ["PATRICIA_PLUGIN_CONFIG"]).write_text(
            json.dumps({"hooks": {"push_reminder": {"enabled": False}}}),
            encoding="utf-8",
        )
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS)])

        self.assertIsNone(self.context(self.payload(transcript)))

    def test_real_script_reads_the_transcript_without_contacting_the_server(self) -> None:
        self.write_token()
        transcript = self.transcript([_tool_use() for _ in range(push_reminder.MIN_TOOL_CALLS)])
        response = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"unused": True}}}
        with FakeMCPServer(response) as server:
            completed = self.run_script(
                "push_reminder.py",
                self.payload(transcript, session="subprocess"),
                extra_environment={"PATRICIA_MCP_URL": server.url},
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("facts worth keeping", completed.stdout)
        self.assertEqual(server.requests, [])
