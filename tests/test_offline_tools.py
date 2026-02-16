from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from g4fagent.tools import ToolRuntime
from g4fagent.tools.registry import load_tool_modules_from_dir


class TestToolRuntime(unittest.TestCase):
    def test_builtin_tools_available(self) -> None:
        runtime = ToolRuntime(root=".")
        tools = runtime.available_tools()
        self.assertIn("list_dir", tools)
        self.assertIn("read_file", tools)
        self.assertIn("write_file", tools)
        self.assertIn("apply_patch", tools)
        self.assertIn("delete_file", tools)

    def test_unknown_tool(self) -> None:
        runtime = ToolRuntime(root=".")
        result = runtime.execute("does_not_exist", {})
        self.assertFalse(result.ok)
        self.assertIn("Unknown tool", result.output)

    def test_file_tools_crud_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ToolRuntime(root=tmp)
            write_res = runtime.execute("write_file", {"path": "a.txt", "content": "line1\nline2\n"})
            self.assertTrue(write_res.ok)

            read_res = runtime.execute("read_file", {"path": "a.txt"})
            self.assertTrue(read_res.ok)
            self.assertIn("line2", read_res.output)

            patch_res = runtime.execute(
                "apply_patch",
                {
                    "path": "a.txt",
                    "diff": "@@ -1,2 +1,2 @@\n line1\n-line2\n+line-two\n",
                },
            )
            self.assertTrue(patch_res.ok)

            read_res2 = runtime.execute("read_file", {"path": "a.txt"})
            self.assertTrue(read_res2.ok)
            self.assertIn("line-two", read_res2.output)

            del_res = runtime.execute("delete_file", {"path": "a.txt"})
            self.assertTrue(del_res.ok)

    def test_load_external_tool_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools_dir = Path(tmp) / "ext"
            tools_dir.mkdir(parents=True, exist_ok=True)
            (tools_dir / "echo_tool.py").write_text(
                "from g4fagent.tools import ToolCategory, tool\n"
                "class EchoTools(ToolCategory):\n"
                "    @tool('echo')\n"
                "    def echo(self, text: str = 'ok'):\n"
                "        return text\n",
                encoding="utf-8",
            )

            runtime = ToolRuntime(root=tmp, extra_tool_dirs=[tools_dir])
            self.assertIn("echo", runtime.available_tools())
            result = runtime.execute("echo", {"text": "hello"})
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "hello")

    def test_load_tool_modules_from_missing_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with self.assertRaises(FileNotFoundError):
                load_tool_modules_from_dir(missing)


if __name__ == "__main__":
    unittest.main()

