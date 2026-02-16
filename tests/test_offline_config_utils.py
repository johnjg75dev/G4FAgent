from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from g4fagent import config as cfgmod
from g4fagent.utils import (
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
            config_path = cfgmod.ensure_runtime_config_files(base, "config.json")
            self.assertTrue(config_path.exists())
            self.assertTrue((base / "agents" / "PlanningAgent.json").exists())
            self.assertTrue((base / "agents" / "WritingAgent.json").exists())

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


if __name__ == "__main__":
    unittest.main()

