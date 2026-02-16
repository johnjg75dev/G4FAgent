from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from g4fagent import config as cfgmod
from g4fagent.constants import DEFAULT_AGENTS_REL_DIR, DEFAULT_CONFIG_REL_PATH
from g4fagent.utils import (
    detect_verification_program_paths,
    deep_merge_dict,
    ensure_rel_path,
    extract_plan_json,
    final_verify_written_files,
    parse_tool_call,
    sanitize_generated_file_content,
)


class TestConfig(unittest.TestCase):
    def test_load_json_object_requires_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            p.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                cfgmod.load_json_object(p)

    def test_resolve_pipeline_stages_defaults(self) -> None:
        planning, writing = cfgmod.resolve_pipeline_stages({"pipeline": {"order": []}})
        self.assertEqual(planning, "planning")
        self.assertEqual(writing, "writing")

    def test_ensure_runtime_config_files_creates_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = cfgmod.ensure_runtime_config_files(base, DEFAULT_CONFIG_REL_PATH)
            self.assertTrue(config_path.exists())
            self.assertEqual(config_path, (base / DEFAULT_CONFIG_REL_PATH).resolve())
            self.assertTrue((base / DEFAULT_AGENTS_REL_DIR / "PlanningAgent.json").exists())
            self.assertTrue((base / DEFAULT_AGENTS_REL_DIR / "WritingAgent.json").exists())
            self.assertTrue((base / DEFAULT_AGENTS_REL_DIR / "DebugAgent.json").exists())

    def test_load_runtime_config_raises_for_missing_agent_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bad_cfg = {
                "agents_dir": "agents",
                "pipeline": {
                    "order": ["planning", "writing"],
                    "stages": {
                        "planning": {"role": "MissingAgent", "overrides": {}},
                        "writing": {"role": "MissingAgentTwo", "overrides": {}},
                    },
                },
                "g4f_defaults": {},
            }
            (base / "config.json").write_text(json.dumps(bad_cfg), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                cfgmod.load_runtime_config(base, "config.json")


class TestUtils(unittest.TestCase):
    def test_ensure_rel_path_rejects_escape(self) -> None:
        with self.assertRaises(ValueError):
            ensure_rel_path("../outside.txt")

    def test_deep_merge_dict_does_not_mutate_inputs(self) -> None:
        a = {"x": {"y": 1}, "k": 1}
        b = {"x": {"z": 2}}
        merged = deep_merge_dict(a, b)
        self.assertEqual(merged, {"x": {"y": 1, "z": 2}, "k": 1})
        self.assertEqual(a, {"x": {"y": 1}, "k": 1})
        self.assertEqual(b, {"x": {"z": 2}})

    def test_extract_plan_json(self) -> None:
        text = "hello\n<PLAN_JSON>{\"todo\": [\"a\"], \"files\": []}</PLAN_JSON>\nbye"
        cleaned, obj = extract_plan_json(text)
        self.assertIn("hello", cleaned)
        self.assertIn("bye", cleaned)
        self.assertEqual(obj["todo"], ["a"])

    def test_parse_tool_call(self) -> None:
        parsed = parse_tool_call('{"tool":"read_file","args":{"path":"x.txt"}}')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["tool"], "read_file")
        self.assertIsNone(parse_tool_call("not json"))
        mixed = (
            '{"tool":"read_file","args":{"path":"backend/app/schemas.py"}}\n\n'
            "Want best roleplay experience?\nhttps://llmplayground.net"
        )
        parsed_mixed = parse_tool_call(mixed)
        self.assertIsNotNone(parsed_mixed)
        self.assertEqual(parsed_mixed["tool"], "read_file")
        self.assertEqual(parsed_mixed["args"]["path"], "backend/app/schemas.py")

    def test_sanitize_generated_file_content_prefers_fenced_block(self) -> None:
        text = "Here you go\n```python\nprint('x')\n```"
        sanitized = sanitize_generated_file_content(text)
        self.assertEqual(sanitized, "print('x')")

    def test_final_verify_written_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text("print('ok')\n", encoding="utf-8")
            ok, report = final_verify_written_files(root, ["ok.py"])
            self.assertTrue(ok)
            self.assertIn("All planned files exist", report)

    @patch("g4fagent.utils.platform.system", return_value="Windows")
    @patch("g4fagent.utils.glob.glob", return_value=[])
    @patch("g4fagent.utils.shutil.which")
    def test_detect_verification_program_paths_prefers_path_hits(self, which_mock, *_mocks) -> None:
        def which_side_effect(name: str):
            if name == "python":
                return r"C:\Python314\python.exe"
            if name == "ruff":
                return r"C:\Python314\Scripts\ruff.exe"
            return None

        which_mock.side_effect = which_side_effect
        detected = detect_verification_program_paths(programs=["python", "ruff"])
        self.assertEqual(detected["total_programs"], 2)
        self.assertEqual(detected["found_count"], 2)

        by_name = {x["program"]: x for x in detected["results"]}
        self.assertEqual(by_name["python"]["source"], "PATH")
        self.assertTrue(by_name["python"]["preferred_path"].lower().endswith("python.exe"))
        self.assertIn("-m ruff check .", " ".join(by_name["python"]["suggested_lint_commands"]))
        self.assertEqual(by_name["ruff"]["source"], "PATH")
        self.assertIn("check .", " ".join(by_name["ruff"]["suggested_lint_commands"]))

    @patch("g4fagent.utils.platform.system", return_value="Windows")
    @patch("g4fagent.utils.shutil.which", return_value=None)
    @patch("g4fagent.utils.glob.glob")
    def test_detect_verification_program_paths_uses_known_path_patterns(self, glob_mock, *_mocks) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe_path = Path(tmp) / "Python314" / "python.exe"
            exe_path.parent.mkdir(parents=True, exist_ok=True)
            exe_path.write_text("", encoding="utf-8")

            def glob_side_effect(_pattern: str):
                return [str(exe_path)]

            glob_mock.side_effect = glob_side_effect
            detected = detect_verification_program_paths(programs=["python"])
            self.assertEqual(detected["found_count"], 1)
            python_result = detected["results"][0]
            self.assertEqual(python_result["source"], "KNOWN_PATH")
            self.assertTrue(str(exe_path).lower().endswith("python.exe"))
            self.assertTrue(python_result["all_paths"])


if __name__ == "__main__":
    unittest.main()
