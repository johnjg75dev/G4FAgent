from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from g4fagent.core import G4FManager, LLMConfig, Project
from g4fagent.tools import ToolRuntime

from main import (
    append_accepted_file_once,
    chat_with_model_retry,
    extract_saved_user_prompt,
    extract_diagnostics,
    find_debug_stage_name,
    is_file_marked_complete,
    load_resume_payload,
    normalize_commands,
    print_tool_call_console,
    project_needs_completion,
    resolve_existing_file_policy,
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

    def build_stage_request(self, stage_name: str, cli_model, cli_provider, cli_temperature):
        return "fake-model", None, {}, 0

    def chat(self, messages, model, provider=None, create_kwargs=None, max_retries=None, stage_name=None):
        self.calls += 1
        return self._replies.pop(0)


class _FakeRetryManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, messages, model, provider=None, create_kwargs=None, max_retries=None, stage_name=None):
        model_name = str(model)
        self.calls.append(model_name)
        if model_name == "bad-model":
            raise RuntimeError("quota exhausted")
        return "ok"


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

    def test_project_needs_completion_status_detection(self) -> None:
        self.assertTrue(project_needs_completion({"state": {"status": "writing"}}))
        self.assertFalse(project_needs_completion({"state": {"status": "completed"}}))
        self.assertFalse(project_needs_completion({"state": {"status": "completed_with_quality_failures"}}))

    def test_extract_saved_user_prompt(self) -> None:
        snapshot = {"accepted_data": {"user_prompt": "Build a web API"}}
        self.assertEqual(extract_saved_user_prompt(snapshot), "Build a web API")

    def test_load_resume_payload_reads_plan_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "PROJECT_PLAN.json").write_text(
                '{"todo":["a"],"files":[{"path":"app/main.py","spec":"x"}]}',
                encoding="utf-8",
            )
            (out / "PROJECT_PLAN.md").write_text("plan text", encoding="utf-8")
            snapshot = {"accepted_data": {"user_prompt": "Build app"}}
            payload = load_resume_payload(out, snapshot)
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["user_prompt"], "Build app")
            self.assertEqual(payload["expected_files"], [str(Path("app/main.py"))])

    def test_is_file_marked_complete_from_project_data(self) -> None:
        project = Project(name="demo")
        project.upsert_file("a.py", accepted=True, status="written")
        self.assertTrue(is_file_marked_complete(project, "a.py"))
        self.assertFalse(is_file_marked_complete(project, "b.py"))

    def test_append_accepted_file_once_avoids_duplicates(self) -> None:
        project = Project(name="demo")
        append_accepted_file_once(project, "a.py")
        append_accepted_file_once(project, "a.py")
        append_accepted_file_once(project, "b.py")
        accepted = project.accepted_data.get("accepted_files")
        self.assertEqual(accepted, ["a.py", "b.py"])

    def test_resolve_existing_file_policy(self) -> None:
        self.assertEqual(resolve_existing_file_policy(skip_existing=True, force=False), "skip")
        self.assertEqual(resolve_existing_file_policy(skip_existing=False, force=True), "force")
        self.assertEqual(resolve_existing_file_policy(skip_existing=False, force=False), "prompt")
        with self.assertRaises(ValueError):
            resolve_existing_file_policy(skip_existing=True, force=True)

    def test_print_tool_call_console_for_auto_executed_tool(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            print_tool_call_console(
                {"tool": "read_file", "args": {"path": "x.txt"}},
                auto_accept=True,
                approval_needed=False,
            )
        out = buffer.getvalue()
        self.assertIn("auto-executed", out)
        self.assertIn('"tool": "read_file"', out)

    @patch("builtins.input", side_effect=["good-model"])
    def test_chat_with_model_retry_prompts_new_model_after_failure(self, _input) -> None:
        manager = _FakeRetryManager()
        with redirect_stdout(StringIO()):
            out, used_model = chat_with_model_retry(
                manager,  # type: ignore[arg-type]
                [{"role": "user", "content": "hi"}],
                model="bad-model",
                provider=None,
                create_kwargs={},
                max_retries=0,
                stage_name="writing",
            )
        self.assertEqual(out, "ok")
        self.assertEqual(used_model, "good-model")
        self.assertEqual(manager.calls, ["bad-model", "good-model"])

    @patch("main.time.sleep")
    @patch("main.time.monotonic")
    def test_chat_with_model_retry_applies_chat_delay(self, monotonic_mock, sleep_mock) -> None:
        class _AlwaysOkManager:
            def chat(self, messages, model, provider=None, create_kwargs=None, max_retries=None, stage_name=None):
                return "ok"

        state = {"last_chat_time": 10.0}
        monotonic_mock.side_effect = [11.0, 11.1, 12.5]

        out, used_model = chat_with_model_retry(
            _AlwaysOkManager(),  # type: ignore[arg-type]
            [{"role": "user", "content": "hi"}],
            model="good-model",
            provider=None,
            create_kwargs={},
            max_retries=0,
            stage_name="writing",
            chat_delay_seconds=3.0,
            chat_delay_state=state,
        )
        self.assertEqual(out, "ok")
        self.assertEqual(used_model, "good-model")
        sleep_mock.assert_called_once_with(2.0)
        self.assertEqual(monotonic_mock.call_count, 3)
        self.assertEqual(state["last_chat_time"], 12.5)

    @patch("builtins.input", side_effect=["", ""])
    @patch("main.time.sleep")
    @patch("main.time.monotonic")
    def test_chat_with_model_retry_blank_retry_adds_cumulative_extra_delay(
        self,
        monotonic_mock,
        sleep_mock,
        _input,
    ) -> None:
        class _FailTwiceManager:
            def __init__(self) -> None:
                self.calls = 0

            def chat(self, messages, model, provider=None, create_kwargs=None, max_retries=None, stage_name=None):
                self.calls += 1
                if self.calls <= 2:
                    raise RuntimeError("rate limit")
                return "ok"

        state = {"last_chat_time": 10.0}
        monotonic_mock.side_effect = [11.0, 11.1, 11.2, 16.3, 16.4, 29.4, 29.5]

        manager = _FailTwiceManager()
        with redirect_stdout(StringIO()):
            out, used_model = chat_with_model_retry(
                manager,  # type: ignore[arg-type]
                [{"role": "user", "content": "hi"}],
                model="same-model",
                provider=None,
                create_kwargs={},
                max_retries=0,
                stage_name="writing",
                chat_delay_seconds=3.0,
                chat_delay_state=state,
                retry_no_selection_extra_delay_seconds=5.0,
            )

        self.assertEqual(out, "ok")
        self.assertEqual(used_model, "same-model")
        self.assertEqual(manager.calls, 3)
        sleep_args = [float(c.args[0]) for c in sleep_mock.call_args_list]
        self.assertEqual(len(sleep_args), 5)
        self.assertAlmostEqual(sleep_args[0], 2.0, places=3)
        self.assertAlmostEqual(sleep_args[1], 2.9, places=3)
        self.assertAlmostEqual(sleep_args[2], 5.0, places=3)
        self.assertAlmostEqual(sleep_args[3], 2.9, places=3)
        self.assertAlmostEqual(sleep_args[4], 10.0, places=3)
        self.assertEqual(state["last_chat_time"], 29.5)

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
                    cli_provider=None,
                    cli_temperature=None,
                    auto_accept=True,
                    max_tool_steps=3,
                )
            self.assertEqual(result["tool_steps"], 1)
            self.assertIn("re-run lint/tests", result["summary"])
            self.assertTrue((Path(tmp) / "fixed.txt").exists())


if __name__ == "__main__":
    unittest.main()
