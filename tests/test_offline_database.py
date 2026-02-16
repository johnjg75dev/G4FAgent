from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from g4fagent.api_server import create_api_server
from g4fagent.core import G4FManager, LLMConfig
from g4fagent.database import JSONDatabase

from tests.helpers import make_runtime_cfg


class TestJSONDatabase(unittest.TestCase):
    def test_json_database_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = JSONDatabase(root)
            db.set("settings", "state", {"telemetry_enabled": True})

            self.assertEqual(db.get("settings", "state"), {"telemetry_enabled": True})

            db_reloaded = JSONDatabase(root)
            self.assertEqual(db_reloaded.get("settings", "state"), {"telemetry_enabled": True})


class TestManagerDatabasePersistence(unittest.TestCase):
    def test_manager_project_state_persists_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = JSONDatabase(Path(tmp) / "db")

            manager_a = G4FManager.from_runtime_config(
                make_runtime_cfg(),
                cfg=LLMConfig(max_retries=1, log_requests=False),
                database=db,
            )
            manager_a.project.set_state("phase", "planning")
            manager_a.project.accept("user_prompt", "build a service")
            manager_a.project.upsert_file(
                "src/main.py",
                content="print('ok')\n",
                accepted=True,
                status="written",
            )

            manager_b = G4FManager.from_runtime_config(
                make_runtime_cfg(),
                cfg=LLMConfig(max_retries=1, log_requests=False),
                database=db,
            )
            self.assertEqual(manager_b.project.state.get("phase"), "planning")
            self.assertEqual(manager_b.project.accepted_data.get("user_prompt"), "build a service")
            tracked = manager_b.project.get_file("src/main.py")
            self.assertIsNotNone(tracked)
            self.assertTrue(bool(tracked and tracked.accepted))


class TestApiDatabasePersistence(unittest.TestCase):
    def _dispatch(self, server, method: str, path: str, *, body: dict | None = None):
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        response = server.state.dispatch(
            method=method,
            raw_path=path,
            headers={},
            body_bytes=payload,
        )
        return response.status_code, response.body

    def test_api_state_persists_projects_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"

            server_a = create_api_server(
                port=0,
                workspace_dir=workspace,
                auth_disabled=True,
                database="json",
            )
            try:
                status, body = self._dispatch(
                    server_a,
                    "POST",
                    "/api/v1/projects",
                    body={"name": "Persistent Project"},
                )
                self.assertEqual(status, 200)
                project_id = str(body["project"]["id"])

                status, _ = self._dispatch(
                    server_a,
                    "PUT",
                    "/api/v1/settings",
                    body={"telemetry_enabled": False},
                )
                self.assertEqual(status, 200)
            finally:
                server_a.server_close()

            server_b = create_api_server(
                port=0,
                workspace_dir=workspace,
                auth_disabled=True,
                database="json",
            )
            try:
                status, body = self._dispatch(server_b, "GET", "/api/v1/projects")
                self.assertEqual(status, 200)
                project_ids = [str(item.get("id", "")) for item in body.get("items", [])]
                self.assertIn(project_id, project_ids)

                status, body = self._dispatch(server_b, "GET", "/api/v1/settings")
                self.assertEqual(status, 200)
                self.assertEqual(body["settings"]["telemetry_enabled"], False)
            finally:
                server_b.server_close()


if __name__ == "__main__":
    unittest.main()
