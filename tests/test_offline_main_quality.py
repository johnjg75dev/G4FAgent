from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from g4fagent.core import G4FManager, LLMConfig, Project
from g4fagent.tools import ToolRuntime

from main import (
    extract_diagnostics,
    find_debug_stage_name,
    normalize_commands,
    run_debug_stage_round,
    run_quality_checks,
    run_quality_command,
)
from tests.helpers import make_runtime_cfg


class _FakeDebugManager:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    def build_stage_messages(self, stage_name: str, template_context: dict) -> list[dict]:
        self.last_stage_name = stage_name
        self.last_template_context = dict(template_context)
        return [{"role": "user", "content": "debug"}]

    def build_stage_request(self, stage_name: str, cli_model, cli_temperature):
        return "fake-model", None, {}, 0

    def chat(self, messages, model, provider=None, create_kwargs=None, max_retries=None, stage_name=None):
        self.calls += 1
        return self._replies.pop(0)


class TestMainQualityHelpers(unittest.TestCase):
    def test_normalize_commands_filters_empty_values(self) -> None:
        commands = normalize_commands(["  ", "pytest -q", "", "ruff check .  "])
        self.assertEqual(commands, ["pytest -q", "ruff check ."])

    def test_extract_diagnostics_captures_error_and_warning_lines(self) -> None:
        result = extract_diagnostics(
            "file.py:1: warning: style issue\nok line",
            "Traceback (most recent call last):\nValueError: error happened",
        )
        self.assertGreaterEqual(len(result["warnings"]), 1)
        self.assertGreaterEqual(len(result["errors"]), 1)

    def test_run_quality_command_collects_stdout_stderr_and_diagnostics(self) -> None:
        cmd = (
            f"\"{sys.executable}\" -c "
            "\"import sys; print('lint warning: issue'); print('lint error: bad', file=sys.stderr); sys.exit(1)\""
        )
        report = run_quality_command(cmd, kind="lint", cwd=Path.cwd())
        self.assertFalse(report["ok"])
        self.assertNotEqual(report["exit_code"], 0)
        self.assertIn("lint warning", report["stdout"])
        self.assertIn("lint error", report["stderr"])
        self.assertTrue(report["warnings"])
        self.assertTrue(report["errors"])

    def test_run_quality_checks_aggregates_results(self) -> None:
        ok_cmd = f"\"{sys.executable}\" -c \"print('all good')\""
        fail_cmd = f"\"{sys.executable}\" -c \"import sys; print('test warning'); sys.exit(1)\""
        report = run_quality_checks(Path.cwd(), lint_commands=[ok_cmd], test_commands=[fail_cmd])
        self.assertFalse(report["success"])
        self.assertEqual(report["totals"]["commands"], 2)
        self.assertEqual(report["totals"]["failed"], 1)
        self.assertGreaterEqual(report["totals"]["errors"], 1)

    def test_find_debug_stage_name_uses_debug_role(self) -> None:
        manager = G4FManager.from_runtime_config(
            make_runtime_cfg(),
            cfg=LLMConfig(max_retries=0, log_requests=False),
        )
        self.assertEqual(find_debug_stage_name(manager), "debug")

    def test_run_debug_stage_round_executes_tool_call_then_returns_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ToolRuntime(root=tmp)
            project = Project(name="demo")
            manager = _FakeDebugManager(
                [
                    '{"tool":"write_file","args":{"path":"fixed.txt","content":"ok","overwrite":true}}',
                    "Applied fixes; re-run lint/tests.",
                ]
            )
            with redirect_stdout(StringIO()):
                result = run_debug_stage_round(
                    manager,  # type: ignore[arg-type]
                    stage_name="debug",
                    tools=runtime,
                    project=project,
                    out_dir=Path(tmp),
                    user_prompt="Build app",
                    todo=["task"],
                    quality_report={"commands": [], "success": False},
                    cli_model=None,
                    cli_temperature=None,
                    auto_accept=True,
                    max_tool_steps=3,
                )
            self.assertEqual(result["tool_steps"], 1)
            self.assertIn("re-run lint/tests", result["summary"])
            self.assertTrue((Path(tmp) / "fixed.txt").exists())


if __name__ == "__main__":
    unittest.main()
