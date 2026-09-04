"""Tests for the quiet Patricia hook client and shared helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
from pathlib import Path
from unittest import mock

import patricia_client

from tests._support import FakeMCPServer, HookTestCase, patched_stdio


def _result(
    value: object, *, is_error: bool = False, request_id: int = 1
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"structuredContent": value, "isError": is_error},
    }


class TokenTests(HookTestCase):
    def test_environment_token_beats_the_file_and_is_stripped(self) -> None:
        self.write_token("file-token")
        os.environ["PATRICIA_MCP_TOKEN"] = "  environment-token  "

        self.assertEqual(patricia_client.read_token(), "environment-token")

    def test_empty_environment_token_still_beats_the_file(self) -> None:
        self.write_token("file-token")
        os.environ["PATRICIA_MCP_TOKEN"] = "   "

        self.assertIsNone(patricia_client.read_token())

    def test_missing_token_never_starts_a_network_call(self) -> None:
        with mock.patch(
            "patricia_client._open_request", side_effect=AssertionError("network call")
        ) as open_request:
            self.assertFalse(patricia_client.has_token())
            self.assertIsNone(patricia_client.call("whoami"))

        open_request.assert_not_called()

    def test_module_import_does_not_load_the_network_stack(self) -> None:
        code = (
            "import sys; import patricia_client; "
            "forbidden = {'urllib.request', 'ssl', 'socket', 'email'}; "
            "assert forbidden.isdisjoint(sys.modules), forbidden & sys.modules"
        )

        completed = subprocess.run(  # noqa: S603 - fixed interpreter and code
            [sys.executable, "-c", code],
            cwd=Path(patricia_client.__file__).parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


class CallTests(HookTestCase):
    def test_json_response_and_request_contract(self) -> None:
        self.write_token()
        with FakeMCPServer(_result({"workspace": {"name": "Acme"}})) as server:
            os.environ["PATRICIA_MCP_URL"] = server.url
            result = patricia_client.call("whoami")

        self.assertEqual(result, {"workspace": {"name": "Acme"}})
        self.assertEqual(len(server.requests), 1)
        request = server.requests[0]
        self.assertEqual(request["path"], "/v1/mcp")
        self.assertEqual(
            request["json"],
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "whoami", "arguments": {}},
            },
        )
        headers = {key.casefold(): value for key, value in request["headers"].items()}
        self.assertEqual(headers["authorization"], "Bearer secret-test-token")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["accept"], "application/json, text/event-stream")

    def test_sse_uses_the_first_matching_json_rpc_message(self) -> None:
        self.write_token()
        body = b"\n\n".join(
            [
                b"data: ignored",
                b"data: "
                + json.dumps(_result([{"id": "wrong"}], request_id=2)).encode("utf-8"),
                b"data: " + json.dumps(_result([{"id": "first"}])).encode("utf-8"),
                b"data: " + json.dumps(_result([{"id": "last"}])).encode("utf-8"),
            ]
        )
        with FakeMCPServer(_result({}), sse=True, body=body) as server:
            os.environ["PATRICIA_MCP_URL"] = server.url
            result = patricia_client.call(
                "search_memory", {"query": "a query", "limit": 5}
            )

        self.assertEqual(result, [{"id": "first"}])

    def test_unsafe_endpoint_overrides_send_nothing(self) -> None:
        self.write_token()
        with mock.patch(
            "patricia_client._open_request",
            side_effect=AssertionError("network call"),
        ) as open_request:
            for value in (
                "https://evil.example/v1/mcp",
                "http://api.patricia.app/v1/mcp",
            ):
                with self.subTest(value=value):
                    os.environ["PATRICIA_MCP_URL"] = value
                    self.assertIsNone(patricia_client.call("whoami"))

        open_request.assert_not_called()

    def test_cross_host_redirect_does_not_receive_authorization(self) -> None:
        self.write_token()
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                with FakeMCPServer(_result({})) as target:
                    target_url = target.url.replace("127.0.0.1", "localhost")
                    with FakeMCPServer(
                        _result({}), status=status, headers={"Location": target_url}
                    ) as redirect:
                        os.environ["PATRICIA_MCP_URL"] = redirect.url
                        result = patricia_client.call("whoami")

                self.assertEqual(
                    len(redirect.requests), 1, f"redirect {status} received no request"
                )
                self.assertFalse(
                    any(
                        any(
                            name.casefold() == "authorization"
                            for name in request["headers"]
                        )
                        for request in target.requests
                    ),
                    f"redirect {status} delivered an Authorization header to the target",
                )
                self.assertEqual(
                    target.requests, [], f"redirect {status} reached the target"
                )
                self.assertIsNone(result, f"redirect {status} returned a result")

    def test_oversized_response_is_not_parsed(self) -> None:
        self.write_token()
        body = b" " * (patricia_client.RESPONSE_MAX_BYTES + 1)
        with FakeMCPServer(_result({}), body=body) as server:
            os.environ["PATRICIA_MCP_URL"] = server.url
            self.assertIsNone(patricia_client.call("whoami"))

    def test_text_content_is_parsed_when_structured_content_is_absent(self) -> None:
        self.write_token()
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": json.dumps({"ok": True})}],
                "isError": False,
            },
        }
        with FakeMCPServer(response) as server:
            os.environ["PATRICIA_MCP_URL"] = server.url
            result = patricia_client.call("whoami")

        self.assertEqual(result, {"ok": True})

    def test_error_shapes_and_http_401_return_none(self) -> None:
        self.write_token()
        responses = [
            _result({"ignored": True}, is_error=True),
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "failed"}},
        ]
        for response in responses:
            with self.subTest(response=response), FakeMCPServer(response) as server:
                os.environ["PATRICIA_MCP_URL"] = server.url
                self.assertIsNone(patricia_client.call("whoami"))

        with FakeMCPServer(_result({"ignored": True}), status=401) as server:
            os.environ["PATRICIA_MCP_URL"] = server.url
            self.assertIsNone(patricia_client.call("whoami"))

    def test_timeout_and_url_error_return_none(self) -> None:
        self.write_token()
        for error in (TimeoutError("slow"), urllib.error.URLError("offline")):
            with (
                self.subTest(error=error),
                mock.patch.object(
                    patricia_client, "_open_request", side_effect=error
                ),
            ):
                self.assertIsNone(patricia_client.call("whoami"))

    def test_request_construction_failure_returns_none(self) -> None:
        self.write_token()

        self.assertIsNone(patricia_client.call("whoami", {"not_json": object()}))

    def test_token_never_appears_in_output_or_an_exception(self) -> None:
        token = "private-token-value"
        os.environ["PATRICIA_MCP_TOKEN"] = token
        with (
            mock.patch.object(
                patricia_client,
                "_open_request",
                side_effect=RuntimeError(f"request carried {token}"),
            ),
            patched_stdio() as (stdout, stderr),
        ):
            result = patricia_client.call("whoami")

        self.assertIsNone(result)
        self.assertNotIn(token, stdout.getvalue())
        self.assertNotIn(token, stderr.getvalue())


class ConfigTests(HookTestCase):
    def test_hook_is_enabled_unless_a_literal_false_disables_it(self) -> None:
        config = Path(os.environ["PATRICIA_PLUGIN_CONFIG"])
        self.assertTrue(patricia_client.hook_enabled("recall"))

        cases = [
            ({"hooks": {"recall": {"enabled": False}}}, False),
            ({"hooks": {"recall": {"enabled": "false"}}}, True),
            ({"hooks": {"recall": {"enabled": 0}}}, True),
            ({"hooks": {}}, True),
        ]
        for contents, expected in cases:
            with self.subTest(contents=contents):
                config.write_text(json.dumps(contents), encoding="utf-8")
                self.assertEqual(patricia_client.hook_enabled("recall"), expected)

        config.write_text("not json", encoding="utf-8")
        self.assertFalse(patricia_client.hook_enabled("recall"))


class EmitTests(HookTestCase):
    def test_emit_suppresses_stdout_and_keeps_additional_context(self) -> None:
        with patched_stdio() as (stdout, _stderr):
            patricia_client.emit("SessionStart", "Useful context")

        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "suppressOutput": True,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "Useful context",
                },
            },
        )


class StateTests(HookTestCase):
    def test_session_file_sanitizes_the_identifier_and_prunes_only_its_suffix(
        self,
    ) -> None:
        state = patricia_client.session_state_file("../session 1", "recall")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.name, "session1.recall.patricia-session.json")
        stranger = state.parent / "keep.txt"
        stranger.write_text("keep", encoding="utf-8")
        stale = state.parent / f"old.recall{patricia_client.SESSION_STATE_SUFFIX}"
        stale.write_text("{}", encoding="utf-8")
        old = time.time() - patricia_client.SESSION_STATE_TTL_SECONDS - 1
        os.utime(stale, (old, old))

        self.assertTrue(patricia_client.write_state(state, {"seen": ["one"]}))

        self.assertFalse(stale.exists())
        self.assertTrue(stranger.exists())
        self.assertEqual(patricia_client.read_state(state), {"seen": ["one"]})
        self.assertEqual(state.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)

    def test_state_write_refuses_a_precreated_symlink(self) -> None:
        state = patricia_client.project_state_file("/project/symlink")
        assert state is not None
        target = self.root / "target.json"
        target.write_text("unchanged", encoding="utf-8")
        state.symlink_to(target)

        self.assertFalse(patricia_client.write_state(state, {"secret": "state"}))

        self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")

    def test_project_file_is_a_stable_short_hash(self) -> None:
        first = patricia_client.project_state_file("/project/one")
        second = patricia_client.project_state_file("/project/one")
        different = patricia_client.project_state_file("/project/two")

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)
        assert first is not None
        self.assertEqual(len(first.stem), 16)


class PayloadTests(HookTestCase):
    def test_every_unusable_input_returns_an_empty_mapping(self) -> None:
        unusable = mock.Mock()
        unusable.read.return_value = object()

        with mock.patch.object(patricia_client.sys, "stdin", unusable):
            self.assertEqual(patricia_client.read_payload(), {})
