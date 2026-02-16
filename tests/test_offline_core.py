from __future__ import annotations

import unittest
from unittest.mock import patch

from g4fagent.core import (
    Agent,
    G4FManager,
    LLMConfig,
    Pipeline,
    Project,
    Stage,
    enforce_strict_json_object_response_format,
    merge_prompt_media_kwargs,
    resolve_model_name,
)
from g4fagent.utils import msg

from tests.helpers import make_runtime_cfg


class TestCoreHelpers(unittest.TestCase):
    def test_resolve_model_name_uses_explicit_name(self) -> None:
        self.assertEqual(resolve_model_name("custom-model"), "custom-model")

    @patch("g4fagent.core.g4f.models", create=True)
    def test_resolve_model_name_uses_default_model_alias(self, mock_models) -> None:
        mock_models.default = "default-model"
        self.assertEqual(resolve_model_name(None), "default-model")

    def test_enforce_strict_json_object_response_format_from_string(self) -> None:
        result = enforce_strict_json_object_response_format("json_object")
        self.assertEqual(result["type"], "json_schema")
        self.assertEqual(result["json_schema"]["strict"], True)
        self.assertEqual(result["json_schema"]["schema"]["type"], "object")

    def test_enforce_strict_json_object_response_format_from_existing_schema(self) -> None:
        result = enforce_strict_json_object_response_format(
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "payload",
                    "strict": False,
                    "schema": {"type": "array", "properties": {"x": {"type": "string"}}},
                },
            }
        )
        self.assertEqual(result["json_schema"]["name"], "payload")
        self.assertEqual(result["json_schema"]["strict"], True)
        self.assertEqual(result["json_schema"]["schema"]["type"], "object")
        self.assertIn("properties", result["json_schema"]["schema"])

    def test_enforce_strict_json_object_response_format_keeps_non_json_types(self) -> None:
        obj = {"type": "text"}
        self.assertIs(enforce_strict_json_object_response_format(obj), obj)

    def test_merge_prompt_media_kwargs_prioritizes_media(self) -> None:
        result = merge_prompt_media_kwargs(
            {"image": "old", "image_name": "old.png", "images": ["a"]},
            image="new",
            image_name="new.png",
            images=["b"],
            media=[("data:image/png;base64,AAA", "new.png")],
        )
        self.assertIn("media", result)
        self.assertNotIn("image", result)
        self.assertNotIn("images", result)

    def test_merge_prompt_media_kwargs_updates_image_name_for_existing_image(self) -> None:
        result = merge_prompt_media_kwargs({"image": "http://img"}, image_name="img.png")
        self.assertEqual(result["image_name"], "img.png")


class TestProjectModel(unittest.TestCase):
    def test_project_upsert_file_and_to_dict(self) -> None:
        project = Project(name="demo")
        project.accept("k", {"x": 1})
        project.set_state("phase", "planning")
        file_obj = project.upsert_file("a.txt", spec="spec", content="hello", accepted=True, status="done")

        self.assertEqual(file_obj.path, "a.txt")
        self.assertTrue(file_obj.accepted)
        self.assertEqual(project.get_file("a.txt"), file_obj)
        serialized = project.to_dict()
        self.assertEqual(serialized["name"], "demo")
        self.assertEqual(serialized["files"][0]["content"], "hello")

    def test_project_append_accepted_type_check(self) -> None:
        project = Project()
        project.accept("bucket", {"x": 1})
        with self.assertRaises(TypeError):
            project.append_accepted("bucket", {"y": 2})


class TestAgentStagePipeline(unittest.TestCase):
    def test_agent_build_request_merges_and_filters_params(self) -> None:
        agent = Agent(
            role="R",
            prompt="P",
            user_prompt_template="T",
            model="default",
            provider="auto",
            g4f_params={
                "temperature": 0.9,
                "response_format": "json",
                "unknown_param": 1,
                "max_retries": 5,
                "extra_kwargs": {"custom_key": "ok", "none_value": None},
            },
        )

        model, provider, kwargs, retries = agent.build_request(
            defaults={"stream": False, "stop": None},
            stage_overrides={"model": "m1", "provider": "p1", "g4f_params": {"top_p": 0.7}},
            cli_model=None,
            cli_temperature=0.3,
            fallback_retries=2,
        )

        self.assertEqual(model, "m1")
        self.assertEqual(provider, "p1")
        self.assertEqual(retries, 5)
        self.assertEqual(kwargs["temperature"], 0.3)
        self.assertEqual(kwargs["top_p"], 0.7)
        self.assertEqual(kwargs["custom_key"], "ok")
        self.assertNotIn("unknown_param", kwargs)
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")

    def test_stage_from_config_validations(self) -> None:
        known = {"R": Agent(role="R", prompt="", user_prompt_template="")}
        with self.assertRaises(KeyError):
            Stage.from_config("s", {"role": "missing"}, known)
        with self.assertRaises(ValueError):
            Stage.from_config("s", {"roles": []}, known)

    def test_pipeline_add_stage_skips_duplicates(self) -> None:
        stage = Stage(name="planning", agents=[Agent(role="R", prompt="", user_prompt_template="")])
        pipeline = Pipeline(stages=[stage], order=["planning"])
        pipeline.add_stage(stage)
        self.assertEqual(len(pipeline.stages), 1)


class TestManagerChat(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = G4FManager.from_runtime_config(
            make_runtime_cfg(),
            cfg=LLMConfig(max_retries=1, log_requests=False),
        )

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_chat_string_response_records_history(self, create_mock) -> None:
        create_mock.return_value = "hello"
        response = self.manager.chat(
            messages=[msg("user", "ping")],
            model="m",
            max_retries=0,
            stage_name="planning",
        )
        self.assertEqual(response, "hello")
        self.assertEqual(len(self.manager.project.chat_history), 1)
        self.assertEqual(self.manager.project.chat_history[0]["response"], "hello")

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_chat_dict_response_extracts_content(self, create_mock) -> None:
        create_mock.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response = self.manager.chat(messages=[msg("user", "ping")], model="m", max_retries=0)
        self.assertEqual(response, "ok")

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_chat_retries_and_records_error_then_success(self, create_mock) -> None:
        create_mock.side_effect = [RuntimeError("boom"), "ok"]
        response = self.manager.chat(messages=[msg("user", "ping")], model="m", max_retries=1, stage_name="planning")
        self.assertEqual(response, "ok")
        self.assertEqual(create_mock.call_count, 2)
        self.assertEqual(len(self.manager.project.chat_history), 2)
        self.assertIn("error", self.manager.project.chat_history[0])
        self.assertEqual(self.manager.project.chat_history[1]["response"], "ok")

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_chat_raises_after_retries_exhausted(self, create_mock) -> None:
        create_mock.side_effect = RuntimeError("always fails")
        with self.assertRaises(RuntimeError):
            self.manager.chat(messages=[msg("user", "ping")], model="m", max_retries=0)

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_chat_stage_forwards_images_and_updates_state(self, create_mock) -> None:
        create_mock.return_value = "stage-ok"
        response = self.manager.chat_stage(
            stage_name="planning",
            template_context={"user_prompt": "Build app"},
            image="https://example.com/img.png",
            image_name="img.png",
        )
        self.assertEqual(response, "stage-ok")
        self.assertEqual(self.manager.project.state.get("last_completed_stage"), "planning")
        call_kwargs = create_mock.call_args.kwargs
        self.assertEqual(call_kwargs["image"], "https://example.com/img.png")
        self.assertEqual(call_kwargs["image_name"], "img.png")


if __name__ == "__main__":
    unittest.main()

