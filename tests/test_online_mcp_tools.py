from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from g4fagent.core import G4FManager, LLMConfig, resolve_model_name
from g4fagent.tools import ToolRuntime
from g4fagent.utils import msg, parse_tool_call

from tests.helpers import make_runtime_cfg


def _fixture_mcp_tools_dir() -> Path:
    return (Path(__file__).resolve().parent / "fixtures" / "mcp_tools").resolve()


def _extract_tool_call(text: str) -> Optional[Dict[str, Any]]:
    parsed = parse_tool_call(text)
    if parsed is not None:
        return parsed
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return None
    return parse_tool_call(match.group(0))


class TestOnlineMcpTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv("G4F_ONLINE_TESTS", "0") != "1":
            raise unittest.SkipTest("Online tests are disabled. Set G4F_ONLINE_TESTS=1 to run them.")

    def test_model_generated_mcp_tool_call_can_be_executed(self) -> None:
        manager = G4FManager.from_runtime_config(
            make_runtime_cfg(),
            cfg=LLMConfig(max_retries=0, log_requests=False),
        )

        with tempfile.TemporaryDirectory() as tmp:
            runtime = ToolRuntime(root=tmp, extra_tool_dirs=[_fixture_mcp_tools_dir()])

            prompt = (
                "Respond ONLY with JSON object in this exact envelope format: "
                "{\"tool\":\"mcp_echo\",\"args\":{\"text\":\"online-mcp\"}}. "
                "Do not include markdown or extra text."
            )

            try:
                response = manager.chat(
                    messages=[msg("user", prompt)],
                    model=resolve_model_name(None),
                    create_kwargs={
                        "timeout": 45,
                        "response_format": {"type": "json_object"},
                    },
                    max_retries=0,
                )
            except Exception as e:
                self.skipTest(f"Online provider unavailable: {e}")

            tool_call = _extract_tool_call(response)
            if tool_call is None:
                self.skipTest(f"Model did not return parseable tool-call JSON: {response[:200]}")

            if tool_call.get("tool") != "mcp_echo":
                self.skipTest(f"Model returned unexpected tool '{tool_call.get('tool')}'")

            result = runtime.execute(tool_call["tool"], tool_call.get("args", {}))
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "online-mcp")


if __name__ == "__main__":
    unittest.main()

