from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as cli_module
from g4fagent.api_server import create_api_server


class TestApiServerDispatch(unittest.TestCase):
    def _dispatch(self, server, method: str, path: str, *, body: dict | None = None, headers: dict | None = None):
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        response = server.state.dispatch(
            method=method,
            raw_path=path,
            headers=headers or {},
            body_bytes=payload,
        )
        return response.status_code, response.body, response.content_type

    def test_public_health_and_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = create_api_server(port=0, workspace_dir=Path(tmp), auth_disabled=True)
            try:
                status, body, content_type = self._dispatch(server, "GET", "/api/v1/health")
                self.assertEqual(status, 200)
                self.assertEqual(content_type, "application/json")
                self.assertTrue(body["ok"])
                self.assertIn("uptime_s", body)

                status, body, _ = self._dispatch(server, "GET", "/api/v1/capabilities")
                self.assertEqual(status, 200)
                self.assertIn("features", body)
                self.assertIn("limits", body)
            finally:
                server.server_close()

    def test_auth_login_then_me(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = create_api_server(port=0, workspace_dir=Path(tmp), auth_disabled=False)
            try:
                status, body, _ = self._dispatch(
                    server,
                    "POST",
                    "/api/v1/auth/login",
                    body={"method": "password", "email": "admin@g4fagent.local", "password": "admin"},
                )
                self.assertEqual(status, 200)
                access = body["access_token"]
                self.assertTrue(access)

                status, body, _ = self._dispatch(
                    server,
                    "GET",
                    "/api/v1/me",
                    headers={"Authorization": f"Bearer {access}"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(body["user"]["email"], "admin@g4fagent.local")
            finally:
                server.server_close()

    def test_projects_and_files_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = create_api_server(port=0, workspace_dir=Path(tmp), auth_disabled=False)
            try:
                login_status, login_body, _ = self._dispatch(
                    server,
                    "POST",
                    "/api/v1/auth/login",
                    body={"method": "password", "email": "admin@g4fagent.local", "password": "admin"},
                )
                self.assertEqual(login_status, 200)
                headers = {"Authorization": f"Bearer {login_body['access_token']}"}

                status, body, _ = self._dispatch(
                    server,
                    "POST",
                    "/api/v1/projects",
                    body={"name": "Demo Project"},
                    headers=headers,
                )
                self.assertEqual(status, 200)
                project_id = body["project"]["id"]
                self.assertTrue(project_id)

                status, body, _ = self._dispatch(
                    server,
                    "PUT",
                    f"/api/v1/projects/{project_id}/files/content",
                    body={"path": "src/app.py", "text": "print('ok')\n"},
                    headers=headers,
                )
                self.assertEqual(status, 200)
                self.assertTrue(body["ok"])
                self.assertTrue(body["etag"])

                status, body, _ = self._dispatch(
                    server,
                    "GET",
                    f"/api/v1/projects/{project_id}/files/content?path=src/app.py",
                    headers=headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(body["path"], "src/app.py")
                self.assertIn("print('ok')", body["text"])
                self.assertTrue(body["etag"])
            finally:
                server.server_close()


class TestMainServerCommand(unittest.TestCase):
    @patch("main.run_api_server", return_value=0)
    def test_main_server_subcommand_invokes_api_runner(self, run_api_server_mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "g4fagent",
                "server",
                "--host",
                "0.0.0.0",
                "--port",
                "8123",
                "--base-path",
                "/api/v1",
                "--workspace",
                tmp,
                "--auth-disabled",
                "--api-key",
                "test-key",
                "--tools-dir",
                tmp,
            ]
            with patch.object(sys, "argv", argv):
                rc = cli_module.main()

            self.assertEqual(rc, 0)
            kwargs = run_api_server_mock.call_args.kwargs
            self.assertEqual(kwargs["host"], "0.0.0.0")
            self.assertEqual(kwargs["port"], 8123)
            self.assertEqual(kwargs["base_path"], "/api/v1")
            self.assertEqual(kwargs["workspace_dir"], Path(tmp).resolve())
            self.assertEqual(kwargs["auth_disabled"], True)
            self.assertEqual(kwargs["api_key"], "test-key")
            self.assertEqual(kwargs["tools_dirs"], [tmp])

    @patch("main.run_api_server", return_value=0)
    def test_main_server_subcommand_rejects_invalid_port(self, run_api_server_mock) -> None:
        with patch.object(sys, "argv", ["g4fagent", "server", "--port", "70000"]):
            rc = cli_module.main()
        self.assertEqual(rc, 2)
        run_api_server_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
