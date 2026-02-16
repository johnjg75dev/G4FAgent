from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import main as cli_module


class _FakeScanSummary:
    def __init__(self) -> None:
        self._report = {
            "total": 0,
            "ok_count": 0,
            "failed_count": 0,
            "no_response_count": 0,
            "error_count": 0,
            "results": [],
        }

    def to_dict(self):
        return dict(self._report)


class _FakeManager:
    def __init__(self) -> None:
        self.scan_calls = []
        self.database = None

    def scan_models(self, **kwargs):
        self.scan_calls.append(kwargs)
        callback = kwargs.get("on_result")
        if callable(callback):
            callback(
                SimpleNamespace(
                    model="m",
                    provider="P",
                    status="ok",
                    elapsed_seconds=0.01,
                    error=None,
                    response_preview="OK",
                )
            )
        return _FakeScanSummary()


class _FakeDB:
    def __init__(self) -> None:
        self.calls = []

    def set(self, bucket, key, value):
        self.calls.append((bucket, key, value))


class TestScanModelsCommand(unittest.TestCase):
    @patch("main.signal.signal")
    @patch("main.signal.getsignal", return_value=None)
    @patch("main.print_model_scan_report")
    @patch("main.create_database")
    @patch("main.G4FManager.from_config")
    @patch("main.list_known_model_names_for_provider")
    @patch("main.list_known_provider_names")
    def test_scan_models_command_builds_provider_model_matrix(
        self,
        list_providers_mock,
        models_for_provider_mock,
        manager_from_config_mock,
        create_database_mock,
        _print_report_mock,
        _getsignal_mock,
        _signal_mock,
    ) -> None:
        list_providers_mock.return_value = ["ProviderA", "ProviderB"]

        def models_side_effect(provider_name: str):
            if provider_name == "ProviderA":
                return ["a1", "a2"]
            if provider_name == "ProviderB":
                return ["b1"]
            return []

        models_for_provider_mock.side_effect = models_side_effect
        manager = _FakeManager()
        manager_from_config_mock.return_value = manager
        fake_db = _FakeDB()
        create_database_mock.return_value = fake_db

        with patch.object(sys, "argv", ["g4fagent", "scan-models"]):
            with redirect_stdout(StringIO()):
                rc = cli_module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(manager.scan_calls), 3)
        observed_targets = [call["models"][0] for call in manager.scan_calls]
        self.assertEqual(
            observed_targets,
            [
                {"model": "a1", "provider": "ProviderA"},
                {"model": "a2", "provider": "ProviderA"},
                {"model": "b1", "provider": "ProviderB"},
            ],
        )
        self.assertTrue(all(call["parallel"] is False for call in manager.scan_calls))
        self.assertGreaterEqual(len(fake_db.calls), 3)

    @patch("main.signal.signal")
    @patch("main.signal.getsignal", return_value=None)
    @patch("main.print_model_scan_report")
    @patch("main.resolve_provider_name", return_value="ProviderA")
    @patch("main.create_database")
    @patch("main.G4FManager.from_config")
    @patch("main.list_known_model_names_for_provider", return_value=["known"])
    def test_scan_models_command_explicit_provider_allows_explicit_models(
        self,
        _models_for_provider_mock,
        manager_from_config_mock,
        create_database_mock,
        _resolve_provider_name_mock,
        _print_report_mock,
        _getsignal_mock,
        _signal_mock,
    ) -> None:
        manager = _FakeManager()
        manager_from_config_mock.return_value = manager
        fake_db = _FakeDB()
        create_database_mock.return_value = fake_db

        with patch.object(
            sys,
            "argv",
            ["g4fagent", "scan-models", "--provider", "ProviderA", "--model", "known", "--model", "custom"],
        ):
            with redirect_stdout(StringIO()):
                rc = cli_module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(manager.scan_calls), 2)
        scan_kwargs = manager.scan_calls[0]
        self.assertEqual(
            [call["models"][0] for call in manager.scan_calls],
            [
                {"model": "known", "provider": "ProviderA"},
                {"model": "custom", "provider": "ProviderA"},
            ],
        )
        self.assertGreaterEqual(len(fake_db.calls), 2)

    @patch("main.list_known_provider_names", return_value=["ProviderA"])
    @patch("main.resolve_provider_name", return_value=None)
    def test_scan_models_command_rejects_unknown_provider(
        self,
        _resolve_provider_name_mock,
        _list_providers_mock,
    ) -> None:
        with patch.object(sys, "argv", ["g4fagent", "scan-models", "--provider", "UnknownProvider"]):
            with redirect_stdout(StringIO()):
                rc = cli_module.main()
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
