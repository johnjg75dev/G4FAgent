from __future__ import annotations

import unittest
from unittest.mock import patch

from g4fagent.core import (
    Agent,
    G4FManager,
    LLMConfig,
    ModelScanSummary,
    Pipeline,
    Project,
    Stage,
    enforce_strict_json_object_response_format,
    list_known_model_names_for_provider,
    list_known_model_names,
    list_known_provider_names,
    merge_prompt_media_kwargs,
    resolve_model_name,
    resolve_provider_name,
    scan_models,
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
            cli_provider=None,
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

    def test_agent_build_request_cli_provider_override(self) -> None:
        agent = Agent(role="R", prompt="P", user_prompt_template="T", provider="base-provider")
        _, provider, _, _ = agent.build_request(
            defaults={},
            stage_overrides={"provider": "stage-provider"},
            cli_model="m1",
            cli_provider="cli-provider",
            cli_temperature=None,
            fallback_retries=1,
        )
        self.assertEqual(provider, "cli-provider")

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

    @patch("g4fagent.core.Stage.build_request")
    def test_build_stage_request_forwards_cli_provider(self, build_mock) -> None:
        build_mock.return_value = ("m", "p", {}, 0)
        _ = self.manager.build_stage_request("planning", "m", "provider-override", 0.1)
        kwargs = build_mock.call_args.kwargs
        self.assertEqual(kwargs["cli_provider"], "provider-override")


class TestModelScanner(unittest.TestCase):
    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_classifies_ok_no_response_and_error(self, create_mock) -> None:
        def side_effect(*args, **kwargs):
            model = kwargs.get("model")
            if model == "good-model":
                return "OK"
            if model == "empty-model":
                return "   "
            raise RuntimeError("model unavailable")

        create_mock.side_effect = side_effect
        summary = scan_models(
            models=["good-model", "empty-model", "bad-model"],
            delay_seconds=0,
            parallel=False,
        )
        self.assertIsInstance(summary, ModelScanSummary)
        serialized = summary.to_dict()
        self.assertEqual(serialized["total"], 3)
        self.assertEqual(serialized["ok_count"], 1)
        self.assertEqual(serialized["no_response_count"], 1)
        self.assertEqual(serialized["error_count"], 1)
        self.assertIn("provider", serialized["results"][0])
        self.assertIn("provider_model", serialized["results"][0])
        self.assertIn("working_provider_models", serialized)

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_parallel_mode(self, create_mock) -> None:
        create_mock.return_value = "OK"
        summary = scan_models(
            models=["m1", "m2", "m3", "m4"],
            parallel=True,
            max_workers=3,
            delay_seconds=0,
        )
        serialized = summary.to_dict()
        self.assertTrue(serialized["parallel"])
        self.assertEqual(serialized["ok_count"], 4)
        self.assertEqual(create_mock.call_count, 4)

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_supports_per_model_provider_overrides(self, create_mock) -> None:
        create_mock.return_value = "OK"
        summary = scan_models(
            models=[
                {"model": "same-model", "provider": "ProviderA"},
                {"model": "same-model", "provider": "ProviderB"},
            ],
            parallel=False,
            delay_seconds=0,
        )
        serialized = summary.to_dict()
        provider_models = [item["provider_model"] for item in serialized["results"]]
        self.assertEqual(provider_models, ["ProviderA/same-model", "ProviderB/same-model"])
        called_providers = [call.kwargs.get("provider") for call in create_mock.call_args_list]
        self.assertEqual(called_providers, ["ProviderA", "ProviderB"])

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_classifies_provider_error_text_as_error(self, create_mock) -> None:
        def side_effect(*args, **kwargs):
            model_value = kwargs.get("model")
            model_name = str(getattr(model_value, "name", model_value)).strip().lower()
            if model_name == "flux":
                return "Falling back to IP-based quotas (InvalidRepoToken)"
            return "OK"

        create_mock.side_effect = side_effect
        summary = scan_models(
            models=["flux", "good-model"],
            parallel=False,
            delay_seconds=0,
        )
        serialized = summary.to_dict()
        self.assertEqual(serialized["ok_count"], 1)
        self.assertEqual(serialized["error_count"], 1)
        flux = next(item for item in serialized["results"] if item["model"] == "flux")
        self.assertEqual(flux["status"], "error")
        self.assertIn("InvalidRepoToken", str(flux["error"]))

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_streams_results_via_callback(self, create_mock) -> None:
        create_mock.return_value = "OK"
        streamed: list[str] = []

        def on_result(item) -> None:
            streamed.append(item.model)

        summary = scan_models(
            models=["m1", "m2", "m3"],
            parallel=False,
            delay_seconds=0,
            on_result=on_result,
        )
        self.assertEqual(len(summary.results), 3)
        self.assertEqual(len(streamed), 3)
        self.assertEqual(summary.to_dict()["stopped"], False)

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_stop_requested_returns_partial_results(self, create_mock) -> None:
        create_mock.return_value = "OK"

        summary = scan_models(
            models=["m1", "m2", "m3", "m4"],
            parallel=False,
            delay_seconds=0,
            stop_requested=lambda: create_mock.call_count >= 2,
        )
        serialized = summary.to_dict()
        self.assertEqual(serialized["total"], 2)
        self.assertEqual(create_mock.call_count, 2)
        self.assertEqual(serialized["stopped"], True)
        self.assertEqual(serialized["stop_reason"], "stop_requested")

    @patch("g4fagent.core.g4f.ChatCompletion.create")
    def test_scan_models_parallel_immediate_stop_makes_no_calls(self, create_mock) -> None:
        summary = scan_models(
            models=["m1", "m2", "m3", "m4"],
            parallel=True,
            max_workers=2,
            delay_seconds=0,
            stop_requested=lambda: True,
        )
        serialized = summary.to_dict()
        self.assertEqual(serialized["total"], 0)
        self.assertEqual(serialized["stopped"], True)
        self.assertEqual(serialized["stop_reason"], "stop_requested")
        self.assertEqual(create_mock.call_count, 0)

    @patch("g4fagent.core.g4f.models", create=True)
    def test_list_known_model_names_returns_sorted_aliases(self, mock_models) -> None:
        class FakeModel:
            pass

        mock_models.Model = FakeModel
        mock_models.zed = FakeModel()
        mock_models.alpha = FakeModel()
        mock_models.default = FakeModel()

        result = list_known_model_names(include_defaults=False)
        self.assertEqual(result, ["alpha", "zed"])

    @patch("g4fagent.core.g4f", create=True)
    def test_list_known_provider_names_and_resolve_provider(self, mock_g4f) -> None:
        class BaseProvider:
            pass

        class RetryProvider(BaseProvider):
            working = False

        class AlphaProvider(BaseProvider):
            working = True

        class BetaProvider(BaseProvider):
            working = True

        provider_module = type("ProviderModule", (), {})()
        provider_module.BaseProvider = BaseProvider
        provider_module.RetryProvider = RetryProvider
        provider_module.AlphaProvider = AlphaProvider
        provider_module.BetaProvider = BetaProvider
        mock_g4f.Provider = provider_module

        providers = list_known_provider_names(include_meta=False)
        self.assertEqual(providers, ["AlphaProvider", "BetaProvider"])
        self.assertEqual(resolve_provider_name("alpha_provider"), "AlphaProvider")
        self.assertIsNone(resolve_provider_name("missing-provider"))

    @patch("g4fagent.core.g4f", create=True)
    def test_list_known_model_names_for_provider(self, mock_g4f) -> None:
        class BaseProvider:
            pass

        class RetryProvider(BaseProvider):
            working = False

        class AlphaProvider(BaseProvider):
            working = True

        class BetaProvider(BaseProvider):
            working = True

        class IterListProvider(BaseProvider):
            working = False

            def __init__(self, providers):
                self.providers = providers

        provider_module = type("ProviderModule", (), {})()
        provider_module.BaseProvider = BaseProvider
        provider_module.RetryProvider = RetryProvider
        provider_module.IterListProvider = IterListProvider
        provider_module.AlphaProvider = AlphaProvider
        provider_module.BetaProvider = BetaProvider
        mock_g4f.Provider = provider_module

        class FakeModel:
            def __init__(self, best_provider):
                self.best_provider = best_provider

        models_module = type("ModelsModule", (), {})()
        models_module.Model = FakeModel
        models_module.model_a = FakeModel(AlphaProvider)
        models_module.model_b = FakeModel(IterListProvider([BetaProvider]))
        models_module.default = FakeModel(IterListProvider([AlphaProvider]))
        mock_g4f.models = models_module

        alpha_models = list_known_model_names_for_provider("AlphaProvider", include_defaults=False)
        beta_models = list_known_model_names_for_provider("betaprovider", include_defaults=True)
        self.assertEqual(alpha_models, ["model_a"])
        self.assertEqual(beta_models, ["model_b"])

    @patch("g4fagent.core.scan_models")
    def test_manager_scan_models_merges_defaults_and_passes_kwargs(self, scan_mock) -> None:
        manager = G4FManager.from_runtime_config(
            make_runtime_cfg(),
            cfg=LLMConfig(max_retries=1, log_requests=False),
        )
        scan_mock.return_value = ModelScanSummary(
            started_at="s",
            finished_at="f",
            duration_seconds=0.1,
            prompt="p",
            provider=None,
            delay_seconds=0.0,
            parallel=False,
            max_workers=1,
            results=[],
        )

        cb = lambda _item: None
        stopper = lambda: False
        _ = manager.scan_models(
            models=["gpt_4o"],
            create_kwargs={"timeout": 30},
            parallel=True,
            max_workers=2,
            on_result=cb,
            stop_requested=stopper,
        )

        call_kwargs = scan_mock.call_args.kwargs
        self.assertEqual(call_kwargs["models"], ["gpt_4o"])
        self.assertEqual(call_kwargs["parallel"], True)
        self.assertEqual(call_kwargs["max_workers"], 2)
        self.assertEqual(call_kwargs["create_kwargs"]["timeout"], 30)
        self.assertIs(call_kwargs["on_result"], cb)
        self.assertIs(call_kwargs["stop_requested"], stopper)

    @patch("g4fagent.core.detect_verification_program_paths_util")
    def test_manager_detect_verification_program_paths_forwards_args(self, detect_mock) -> None:
        manager = G4FManager.from_runtime_config(
            make_runtime_cfg(),
            cfg=LLMConfig(max_retries=1, log_requests=False),
        )
        detect_mock.return_value = {"total_programs": 1, "found_count": 1, "results": []}

        result = manager.detect_verification_program_paths(programs=["python"], max_matches_per_program=3)
        self.assertEqual(result["found_count"], 1)
        detect_mock.assert_called_once_with(
            programs=["python"],
            max_matches_per_program=3,
        )


if __name__ == "__main__":
    unittest.main()
