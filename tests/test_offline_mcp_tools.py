from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from g4fagent.tools import ToolRuntime


def _fixture_mcp_tools_dir() -> Path:
    return (Path(__file__).resolve().parent / "fixtures" / "mcp_tools").resolve()


class TestOfflineMcpTools(unittest.TestCase):
    def test_mcp_tools_load_and_execute_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ToolRuntime(root=tmp, extra_tool_dirs=[_fixture_mcp_tools_dir()])
            tools = runtime.available_tools()

            self.assertIn("mcp_ping", tools)
            self.assertIn("mcp_echo", tools)
            self.assertIn("mcp_note_write", tools)

            ping = runtime.execute("mcp_ping", {})
            self.assertTrue(ping.ok)
            self.assertEqual(ping.output, "pong")

            echo = runtime.execute("mcp_echo", {"text": "offline-mcp"})
            self.assertTrue(echo.ok)
            self.assertEqual(echo.output, "offline-mcp")

            write = runtime.execute(
                "mcp_note_write",
                {"path": "notes/mcp.txt", "content": "hello"},
            )
            self.assertTrue(write.ok)
            self.assertTrue((Path(tmp) / "notes" / "mcp.txt").exists())

    def test_mcp_note_write_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ToolRuntime(root=tmp, extra_tool_dirs=[_fixture_mcp_tools_dir()])
            result = runtime.execute("mcp_note_write", {"path": "../escape.txt", "content": "bad"})
            self.assertFalse(result.ok)
            self.assertIn("Path escapes project root", result.output)


if __name__ == "__main__":
    unittest.main()

