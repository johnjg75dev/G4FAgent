"""Development HTTP API server for G4FAgent runtime workflows and tooling."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import math
import os
import random
import re
import subprocess
import threading
import time
import uuid
import zipfile
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Pattern, Tuple, Union
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from .constants import APP_ROOT, DEFAULT_CONFIG_REL_PATH
from .core import G4FManager, list_known_model_names, list_known_model_names_for_provider
from .database import Database, create_database
from .tools import ToolRuntime
from .utils import now_iso


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    """Normalize a value into a filesystem-safe slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return cleaned or "project"


def _sha256_text(value: str) -> str:
    """Return the SHA-256 hex digest for a UTF-8 text value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_int(value: Any, default: int) -> int:
    """Safely coerce a value to `int`, falling back to the provided default."""
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    """Safely coerce a value to `float`, falling back to the provided default."""
    try:
        return float(value)
    except Exception:
        return default


def _query_first(query: Mapping[str, List[str]], key: str, default: Optional[str] = None) -> Optional[str]:
    """Return the first value for a query parameter key."""
    values = query.get(key)
    if not values:
        return default
    return values[0]


def _query_bool(query: Mapping[str, List[str]], key: str, default: bool = False) -> bool:
    """Parse a query parameter as a boolean flag."""
    raw = _query_first(query, key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_iso(value: str) -> Optional[dt.datetime]:
    """Parse an ISO-8601 datetime string into a `datetime` object."""
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except Exception:
        return None


def _json_type_label(value: Any) -> str:
    """Return a compact label describing the JSON-compatible value type."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__


class ApiError(Exception):
    """Represent an API exception with HTTP status and machine-readable details."""
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        """Initialize a `ApiError` instance."""
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)
        self.details = details
        self.retryable = bool(retryable)


@dataclass
class ApiResponse:
    """Represent an HTTP response returned by API route handlers."""
    status_code: int
    body: Any
    content_type: str = "application/json"
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class Route:
    """Represent a compiled route template and its request handler."""
    method: str
    template: str
    regex: Pattern[str]
    handler: Callable[["RequestContext"], ApiResponse]
    auth_required: bool


class Router:
    """Provide method+path routing for the lightweight API server."""
    def __init__(self) -> None:
        """Initialize a `Router` instance."""
        self._routes: List[Route] = []

    def _compile_template(self, template: str) -> Pattern[str]:
        """Compile template."""
        parts = [part for part in template.strip("/").split("/") if part]
        if not parts:
            return re.compile(r"^/$")
        regex_parts: List[str] = []
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                name = part[1:-1].strip()
                if not name:
                    raise ValueError(f"Invalid path parameter in route: {template}")
                regex_parts.append(f"(?P<{name}>[^/]+)")
            else:
                regex_parts.append(re.escape(part))
        return re.compile("^/" + "/".join(regex_parts) + "$")

    def add(self, method: str, template: str, handler: Callable[["RequestContext"], ApiResponse], *, auth_required: bool = True) -> None:
        """Register a route handler for an HTTP method and path template."""
        self._routes.append(
            Route(
                method=method.upper(),
                template=template,
                regex=self._compile_template(template),
                handler=handler,
                auth_required=auth_required,
            )
        )

    def match(self, method: str, path: str) -> Tuple[Optional[Route], Dict[str, str]]:
        """Resolve a method/path pair to a registered route and path parameters."""
        method = method.upper()
        for route in self._routes:
            if route.method != method:
                continue
            m = route.regex.match(path)
            if m:
                return route, m.groupdict()
        return None, {}

    def allows_path(self, path: str) -> bool:
        """Return whether any registered route template matches the given path."""
        for route in self._routes:
            if route.regex.match(path):
                return True
        return False

    def endpoint_list(self) -> List[Dict[str, str]]:
        """Return all registered endpoints as method/path pairs."""
        return [{"method": route.method, "path": route.template} for route in self._routes]


@dataclass
class RequestContext:
    """Carry normalized request data for API route handlers."""
    state: "DevApiState"
    method: str
    path: str
    path_params: Dict[str, str]
    query: Dict[str, List[str]]
    headers: Mapping[str, str]
    body_bytes: bytes
    request_id: str
    user: Optional[Dict[str, Any]]
    _json_cache: Any = field(default=None, init=False, repr=False)
    _json_parsed: bool = field(default=False, init=False, repr=False)

    def json(self, *, required: bool = False) -> Dict[str, Any]:
        """Parse and return the request JSON body as an object."""
        if not self._json_parsed:
            self._json_parsed = True
            if not self.body_bytes:
                self._json_cache = {}
            else:
                try:
                    parsed = json.loads(self.body_bytes.decode("utf-8"))
                except Exception as exc:
                    raise ApiError(400, "invalid_json", f"Request body is not valid JSON: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise ApiError(400, "invalid_json", "Request body must be a JSON object.")
                self._json_cache = parsed
        if required and not self._json_cache:
            raise ApiError(400, "missing_body", "Request body is required.")
        return dict(self._json_cache or {})


class DevApiState:
    """Own server state, persistence, authorization, and endpoint handlers."""
    _PERSISTED_DICT_FIELDS = (
        "settings",
        "projects",
        "project_sessions",
        "project_diffs",
        "project_deployments",
        "project_workflows",
        "project_artifacts",
        "project_telemetry_streams",
        "sessions",
        "session_messages",
        "messages",
        "session_runs",
        "runs",
        "run_events",
        "diffs",
        "deployments",
        "deployment_logs",
        "workflows",
        "artifacts",
        "uploads",
        "file_meta",
        "notifications",
        "alerts",
        "dynamic_tools",
        "users",
        "user_passwords",
        "access_tokens",
        "refresh_tokens",
    )
    _PERSISTED_LIST_FIELDS = (
        "audit_events",
        "settings_audit_events",
    )

    def __init__(
        self,
        *,
        base_path: str,
        workspace_dir: Path,
        manager: G4FManager,
        tools_dirs: Optional[Iterable[str]] = None,
        auth_disabled: bool = False,
        api_key: str = "dev-api-key",
        database: Optional[Database] = None,
    ) -> None:
        """Initialize a `DevApiState` instance."""
        normalized_base = "/" + str(base_path or "/api/v1").strip("/")
        if normalized_base == "//":
            normalized_base = "/"
        self.base_path = normalized_base
        self.started_monotonic = time.monotonic()
        self.build = os.getenv("G4FAGENT_BUILD", "dev")
        self.version = os.getenv("G4FAGENT_VERSION", "1.0.0")
        self.manager = manager
        self.workspace_dir = Path(workspace_dir).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.tools_dirs = list(tools_dirs or [])
        self.auth_disabled = bool(auth_disabled)
        self.api_key = str(api_key)
        self.database = database
        self.router = Router()
        self._lock = threading.RLock()
        self._request_metrics: deque[Tuple[float, float]] = deque(maxlen=5000)
        self._project_tool_runtimes: Dict[str, ToolRuntime] = {}
        self._terminal_processes: Dict[str, subprocess.Popen[Any]] = {}
        self._deployment_threads: Dict[str, threading.Thread] = {}
        self._run_threads: Dict[str, threading.Thread] = {}

        self.capabilities = {
            "features": {
                "ws_streaming": False,
                "sse_streaming": True,
                "diffs": True,
                "file_editor": True,
                "workflows": True,
                "deployments": True,
                "telemetry": True,
                "multi_provider": True,
            },
            "limits": {
                "max_projects": 1000,
                "max_sessions_per_project": 10000,
                "max_file_size_bytes": 2 * 1024 * 1024,
                "max_upload_size_bytes": 200 * 1024 * 1024,
                "max_context_tokens": 200000,
            },
        }
        self.settings: Dict[str, Any] = {
            "memory_limit_gb": 8,
            "telemetry_enabled": True,
            "default_provider_id": "g4f",
            "default_model_id": "gpt-4o-mini",
            "providers": [
                {"provider_id": "openai", "enabled": True},
                {"provider_id": "anthropic", "enabled": True},
                {"provider_id": "ollama", "enabled": True},
                {"provider_id": "g4f", "enabled": True},
                {"provider_id": "custom", "enabled": True},
            ],
            "ui": {"theme": "neon_dark", "accent": "#00FF94"},
        }

        self.projects: Dict[str, Dict[str, Any]] = {}
        self.project_paths: Dict[str, Path] = {}
        self.project_sessions: Dict[str, List[str]] = {}
        self.project_diffs: Dict[str, List[str]] = {}
        self.project_deployments: Dict[str, List[str]] = {}
        self.project_workflows: Dict[str, List[str]] = {}
        self.project_artifacts: Dict[str, List[str]] = {}
        self.project_telemetry_streams: Dict[str, List[Dict[str, Any]]] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_messages: Dict[str, List[str]] = {}
        self.messages: Dict[str, Dict[str, Any]] = {}
        self.session_runs: Dict[str, List[str]] = {}
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.run_events: Dict[str, List[Dict[str, Any]]] = {}
        self.diffs: Dict[str, Dict[str, Any]] = {}
        self.deployments: Dict[str, Dict[str, Any]] = {}
        self.deployment_logs: Dict[str, List[Dict[str, Any]]] = {}
        self.workflows: Dict[str, Dict[str, Any]] = {}
        self.artifacts: Dict[str, Dict[str, Any]] = {}
        self.uploads: Dict[str, Dict[str, Any]] = {}
        self.file_meta: Dict[str, Dict[str, Any]] = {}
        self.notifications: Dict[str, Dict[str, Any]] = {}
        self.alerts: Dict[str, Dict[str, Any]] = {}
        self.dynamic_tools: Dict[str, Dict[str, Any]] = {}
        self.audit_events: List[Dict[str, Any]] = []
        self.settings_audit_events: List[Dict[str, Any]] = []

        self.users: Dict[str, Dict[str, Any]] = {}
        self.user_passwords: Dict[str, str] = {}
        self.access_tokens: Dict[str, Dict[str, Any]] = {}
        self.refresh_tokens: Dict[str, Dict[str, Any]] = {}
        self.access_token_ttl_s = max(60, _safe_int(os.getenv("G4FAGENT_ACCESS_TOKEN_TTL", 3600), 3600))
        self.refresh_token_ttl_s = max(60, _safe_int(os.getenv("G4FAGENT_REFRESH_TOKEN_TTL", 86400), 86400))
        self._seed_default_users()
        self._hydrate_state_from_database()
        self._register_routes()

    def _seed_default_users(self) -> None:
        """Seed the in-memory user store with the default admin account."""
        admin_id = "user_admin"
        admin = {
            "id": admin_id,
            "name": os.getenv("G4FAGENT_ADMIN_NAME", "Admin"),
            "email": os.getenv("G4FAGENT_ADMIN_EMAIL", "admin@g4fagent.local"),
            "roles": ["admin", "developer"],
            "created_at": _utc_now_iso(),
            "disabled": False,
        }
        self.users[admin_id] = admin
        self.user_passwords[admin_id] = os.getenv("G4FAGENT_ADMIN_PASSWORD", "admin")

    def _snapshot_database_state(self) -> Dict[str, Any]:
        """Build a serializable snapshot of persisted API state."""
        with self._lock:
            snapshot: Dict[str, Any] = {}
            for field_name in self._PERSISTED_DICT_FIELDS:
                snapshot[field_name] = deepcopy(getattr(self, field_name))
            snapshot["project_paths"] = {str(project_id): str(path) for project_id, path in self.project_paths.items()}
            for field_name in self._PERSISTED_LIST_FIELDS:
                snapshot[field_name] = deepcopy(getattr(self, field_name))
            return snapshot

    def _restore_database_state(self, snapshot: Dict[str, Any]) -> None:
        """Restore persisted API state from a previously stored snapshot."""
        with self._lock:
            for field_name in self._PERSISTED_DICT_FIELDS:
                value = snapshot.get(field_name)
                if isinstance(value, dict):
                    setattr(self, field_name, deepcopy(value))
            project_paths_raw = snapshot.get("project_paths")
            if isinstance(project_paths_raw, dict):
                restored_paths: Dict[str, Path] = {}
                for project_id, raw_path in project_paths_raw.items():
                    if not isinstance(raw_path, str):
                        continue
                    restored_paths[str(project_id)] = Path(raw_path).resolve()
                self.project_paths = restored_paths
            for field_name in self._PERSISTED_LIST_FIELDS:
                value = snapshot.get(field_name)
                if isinstance(value, list):
                    setattr(self, field_name, deepcopy(value))

    def _hydrate_state_from_database(self) -> None:
        """Load persisted API state from the configured database."""
        if self.database is None:
            return
        bucket = self.database.read_bucket("api_server")
        snapshot = bucket.get("state")
        if isinstance(snapshot, dict):
            self._restore_database_state(snapshot)
            if not self.users:
                self._seed_default_users()
                self._persist_database_state()
            return
        self._persist_database_state()

    def _persist_database_state(self) -> None:
        """Persist the current API state to the configured database."""
        if self.database is None:
            return
        self.database.set("api_server", "state", self._snapshot_database_state())

    def _register_routes(self) -> None:
        """Register all HTTP routes and their handler methods."""
        add = self.router.add
        add("GET", "/", self.handle_root, auth_required=False)
        add("GET", "/health", self.handle_health, auth_required=False)
        add("GET", "/capabilities", self.handle_capabilities, auth_required=False)
        add("GET", "/server/stats", self.handle_server_stats, auth_required=False)
        add("POST", "/auth/login", self.handle_auth_login, auth_required=False)
        add("POST", "/auth/refresh", self.handle_auth_refresh, auth_required=False)
        add("POST", "/auth/logout", self.handle_auth_logout)
        add("GET", "/me", self.handle_me)
        add("GET", "/providers", self.handle_providers_list)
        add("POST", "/providers/scan", self.handle_providers_scan)
        add("GET", "/providers/{provider_id}/models", self.handle_provider_models)
        add("POST", "/providers/{provider_id}/test", self.handle_provider_test)
        add("GET", "/settings", self.handle_settings_get)
        add("PUT", "/settings", self.handle_settings_put)
        add("GET", "/settings/audit", self.handle_settings_audit)
        add("GET", "/projects", self.handle_projects_list)
        add("POST", "/projects", self.handle_projects_create)
        add("GET", "/projects/{project_id}", self.handle_projects_get)
        add("PATCH", "/projects/{project_id}", self.handle_projects_patch)
        add("DELETE", "/projects/{project_id}", self.handle_projects_delete)
        add("GET", "/projects/{project_id}/sessions", self.handle_project_sessions_list)
        add("POST", "/projects/{project_id}/sessions", self.handle_project_sessions_create)
        add("GET", "/sessions/{session_id}", self.handle_sessions_get)
        add("PATCH", "/sessions/{session_id}", self.handle_sessions_patch)
        add("GET", "/sessions/{session_id}/messages", self.handle_session_messages_list)
        add("POST", "/sessions/{session_id}/messages", self.handle_session_messages_create)
        add("POST", "/sessions/{session_id}/runs", self.handle_session_runs_create)
        add("GET", "/runs/{run_id}", self.handle_runs_get)
        add("POST", "/runs/{run_id}/cancel", self.handle_runs_cancel)
        add("GET", "/runs/{run_id}/events", self.handle_runs_events)
        add("GET", "/tools", self.handle_tools_list)
        add("POST", "/tools", self.handle_tools_create)
        add("DELETE", "/tools/{tool_id}", self.handle_tools_delete)
        add("POST", "/tools/{tool_id}/invoke", self.handle_tools_invoke)
        add("GET", "/projects/{project_id}/files/tree", self.handle_files_tree)
        add("GET", "/projects/{project_id}/files/content", self.handle_files_get_content)
        add("PUT", "/projects/{project_id}/files/content", self.handle_files_put_content)
        add("POST", "/projects/{project_id}/files/batch", self.handle_files_batch)
        add("POST", "/projects/{project_id}/lint", self.handle_files_lint)
        add("POST", "/projects/{project_id}/format", self.handle_files_format)
        add("POST", "/projects/{project_id}/search", self.handle_files_search)
        add("GET", "/projects/{project_id}/diffs", self.handle_project_diffs_list)
        add("POST", "/projects/{project_id}/diffs", self.handle_project_diffs_create)
        add("GET", "/diffs/{diff_id}", self.handle_diffs_get)
        add("POST", "/diffs/{diff_id}/apply", self.handle_diffs_apply)
        add("POST", "/diffs/{diff_id}/discard", self.handle_diffs_discard)
        add("POST", "/diffs/{diff_id}/comment", self.handle_diffs_comment)
        add("GET", "/projects/{project_id}/repo/status", self.handle_repo_status)
        add("POST", "/projects/{project_id}/repo/checkout", self.handle_repo_checkout)
        add("POST", "/projects/{project_id}/repo/pull", self.handle_repo_pull)
        add("POST", "/projects/{project_id}/repo/commit", self.handle_repo_commit)
        add("POST", "/projects/{project_id}/terminal/sessions", self.handle_terminal_create)
        add("POST", "/projects/{project_id}/terminal/{terminal_id}/kill", self.handle_terminal_kill)
        add("GET", "/projects/{project_id}/deployments", self.handle_project_deployments_list)
        add("POST", "/projects/{project_id}/deployments", self.handle_project_deployments_create)
        add("GET", "/deployments/{deployment_id}", self.handle_deployments_get)
        add("GET", "/deployments/{deployment_id}/logs", self.handle_deployments_logs)
        add("POST", "/deployments/{deployment_id}/cancel", self.handle_deployments_cancel)
        add("GET", "/projects/{project_id}/telemetry/streams", self.handle_telemetry_streams_list)
        add("POST", "/telemetry/query", self.handle_telemetry_query)
        add("POST", "/telemetry/alerts", self.handle_telemetry_alerts_create)
        add("GET", "/projects/{project_id}/workflows", self.handle_project_workflows_list)
        add("POST", "/projects/{project_id}/workflows", self.handle_project_workflows_create)
        add("GET", "/workflows/{workflow_id}", self.handle_workflows_get)
        add("PUT", "/workflows/{workflow_id}", self.handle_workflows_put)
        add("POST", "/workflows/{workflow_id}/runs", self.handle_workflows_run)
        add("GET", "/projects/{project_id}/artifacts", self.handle_project_artifacts_list)
        add("POST", "/projects/{project_id}/artifacts", self.handle_project_artifacts_create)
        add("GET", "/artifacts/{artifact_id}", self.handle_artifacts_get)
        add("POST", "/uploads", self.handle_uploads_create)
        add("PUT", "/uploads/{upload_id}", self.handle_uploads_write)
        add("POST", "/uploads/{upload_id}", self.handle_uploads_write)
        add("GET", "/files/{file_id}", self.handle_files_meta_get)
        add("GET", "/notifications", self.handle_notifications_list)
        add("POST", "/notifications/ack", self.handle_notifications_ack)
        add("GET", "/audit", self.handle_audit_list)
        add("GET", "/admin/users", self.handle_admin_users_list)
        add("POST", "/admin/users", self.handle_admin_users_create)
        add("PATCH", "/admin/users/{user_id}", self.handle_admin_users_patch)
        add("DELETE", "/admin/users/{user_id}", self.handle_admin_users_delete)
        add("GET", "/stream/sessions/{session_id}", self.handle_stream_session)

    def _new_id(self, prefix: str) -> str:
        """Generate a short random identifier with the given prefix."""
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    def _json_response(self, status_code: int, payload: Dict[str, Any], *, headers: Optional[Dict[str, str]] = None) -> ApiResponse:
        """Create a JSON API response payload with optional headers."""
        return ApiResponse(status_code=status_code, body=payload, headers=headers or {})

    def _error_response(
        self,
        request_id: str,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> ApiResponse:
        """Create a standardized API error response envelope."""
        body = {
            "error": {
                "code": str(code),
                "message": str(message),
                "request_id": str(request_id),
                "retryable": bool(retryable),
            }
        }
        if details is not None:
            body["error"]["details"] = details
        return ApiResponse(status_code=status_code, body=body)

    def _paginate_items(
        self,
        items: List[Any],
        query: Mapping[str, List[str]],
        *,
        default_limit: int = 50,
        max_limit: int = 200,
    ) -> Tuple[List[Any], Optional[str]]:
        """Paginate a list using `limit` and `cursor` query parameters."""
        limit = _safe_int(_query_first(query, "limit", str(default_limit)), default_limit)
        limit = max(1, min(max_limit, limit))
        cursor_raw = _query_first(query, "cursor", "0") or "0"
        cursor = max(0, _safe_int(cursor_raw, 0))
        page = items[cursor : cursor + limit]
        next_cursor = cursor + limit
        if next_cursor >= len(items):
            return page, None
        return page, str(next_cursor)

    def _ensure_project(self, project_id: str) -> Dict[str, Any]:
        """Return the requested project or raise `ApiError` if missing."""
        project = self.projects.get(project_id)
        if project is None:
            raise ApiError(404, "project_not_found", f"Project not found: {project_id}")
        return project

    def _ensure_session(self, session_id: str) -> Dict[str, Any]:
        """Return the requested session or raise `ApiError` if missing."""
        session = self.sessions.get(session_id)
        if session is None:
            raise ApiError(404, "session_not_found", f"Session not found: {session_id}")
        return session

    def _ensure_run(self, run_id: str) -> Dict[str, Any]:
        """Return the requested run or raise `ApiError` if missing."""
        run = self.runs.get(run_id)
        if run is None:
            raise ApiError(404, "run_not_found", f"Run not found: {run_id}")
        return run

    def _ensure_project_path(self, project_id: str) -> Path:
        """Return the requested project path or raise `ApiError` if missing."""
        _ = self._ensure_project(project_id)
        path = self.project_paths.get(project_id)
        if path is None:
            raise ApiError(500, "project_path_missing", f"Project path not found for: {project_id}")
        return path

    def _safe_project_file_path(self, project_id: str, rel_path: str) -> Path:
        """Safely process project file path."""
        root = self._ensure_project_path(project_id).resolve()
        raw = Path(str(rel_path))
        if raw.is_absolute():
            raise ApiError(400, "invalid_path", "Absolute paths are not allowed.")
        target = (root / raw).resolve()
        # Block directory traversal so file operations always stay inside the project root.
        try:
            _ = target.relative_to(root)
        except Exception as exc:
            raise ApiError(400, "invalid_path", "Path escapes project root.") from exc
        return target

    def _runtime_for_project(self, project_id: Optional[str]) -> ToolRuntime:
        """Return the tool runtime scoped to a project or workspace."""
        key = project_id or "__workspace__"
        runtime = self._project_tool_runtimes.get(key)
        if runtime is not None:
            return runtime
        root = self.workspace_dir if not project_id else self._ensure_project_path(project_id)
        runtime = ToolRuntime(root=root, extra_tool_dirs=self.tools_dirs)
        self._project_tool_runtimes[key] = runtime
        return runtime

    def _token_user(self, token: str) -> Optional[Dict[str, Any]]:
        """Resolve user details from token state."""
        token_data = self.access_tokens.get(token)
        if not isinstance(token_data, dict):
            return None
        if token_data.get("expires_at", 0.0) < time.time():
            self.access_tokens.pop(token, None)
            self._persist_database_state()
            return None
        user_id = str(token_data.get("user_id", ""))
        user = self.users.get(user_id)
        if user is None or bool(user.get("disabled")):
            return None
        return user

    def _sanitize_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """Return a safe user payload suitable for API responses."""
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "roles": list(user.get("roles", [])),
            "created_at": user["created_at"],
        }

    def _issue_tokens(self, user_id: str) -> Dict[str, Any]:
        """Issue tokens."""
        access_token = self._new_id("atk")
        refresh_token = self._new_id("rtk")
        now_ts = time.time()
        self.access_tokens[access_token] = {"user_id": user_id, "expires_at": now_ts + self.access_token_ttl_s}
        self.refresh_tokens[refresh_token] = {"user_id": user_id, "expires_at": now_ts + self.refresh_token_ttl_s}
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.access_token_ttl_s,
        }

    def _authorize(self, headers: Mapping[str, str]) -> Optional[Dict[str, Any]]:
        """Resolve and validate the caller from the Authorization header."""
        if self.auth_disabled:
            return self._sanitize_user(next(iter(self.users.values())))
        auth = headers.get("Authorization") or headers.get("authorization")
        if not auth or not str(auth).lower().startswith("bearer "):
            raise ApiError(401, "unauthorized", "Missing bearer token.")
        token = str(auth).split(" ", 1)[1].strip()
        user = self._token_user(token)
        if user is None:
            raise ApiError(401, "unauthorized", "Invalid or expired access token.")
        return self._sanitize_user(user)

    def _record_request_metric(self, started: float) -> None:
        """Record request metric information in server state."""
        ended = time.monotonic()
        self._request_metrics.append((ended, (ended - started) * 1000.0))

    def _record_audit(self, actor_user_id: str, event_type: str, data: Dict[str, Any], *, project_id: Optional[str] = None) -> None:
        """Record audit information in server state."""
        event = {
            "id": self._new_id("audit"),
            "ts": _utc_now_iso(),
            "actor_user_id": actor_user_id,
            "project_id": project_id,
            "type": event_type,
            "data": data,
        }
        self.audit_events.append(event)
        self._persist_database_state()

    def _create_notification(self, level: str, title: str, body: str) -> None:
        """Create and store a user-facing notification event."""
        notification = {
            "id": self._new_id("notif"),
            "ts": _utc_now_iso(),
            "level": level,
            "title": title,
            "body": body,
            "acked": False,
        }
        self.notifications[notification["id"]] = notification
        self._persist_database_state()

    def _provider_catalog(self) -> List[Dict[str, Any]]:
        """Return catalog information."""
        now_ts = _utc_now_iso()
        return [
            {
                "id": "openai",
                "label": "OpenAI",
                "type": "cloud",
                "status": "active",
                "base_url": "https://api.openai.com",
                "supports": {"chat": True, "tools": True, "vision": True, "embeddings": True, "audio": True, "streaming": True},
                "last_checked_at": now_ts,
            },
            {
                "id": "anthropic",
                "label": "Anthropic",
                "type": "cloud",
                "status": "active",
                "base_url": "https://api.anthropic.com",
                "supports": {"chat": True, "tools": True, "vision": True, "embeddings": False, "audio": False, "streaming": True},
                "last_checked_at": now_ts,
            },
            {
                "id": "ollama",
                "label": "Ollama",
                "type": "local",
                "status": "idle",
                "base_url": "http://localhost:11434",
                "supports": {"chat": True, "tools": True, "vision": True, "embeddings": True, "audio": False, "streaming": True},
                "last_checked_at": now_ts,
            },
            {
                "id": "g4f",
                "label": "G4F Auto",
                "type": "proxy",
                "status": "active",
                "base_url": "",
                "supports": {"chat": True, "tools": True, "vision": True, "embeddings": True, "audio": True, "streaming": True},
                "last_checked_at": now_ts,
            },
            {
                "id": "custom",
                "label": "Custom",
                "type": "proxy",
                "status": "idle",
                "base_url": "",
                "supports": {"chat": True, "tools": True, "vision": True, "embeddings": True, "audio": True, "streaming": True},
                "last_checked_at": now_ts,
            },
        ]

    def dispatch(
        self,
        *,
        method: str,
        raw_path: str,
        headers: Mapping[str, str],
        body_bytes: bytes,
    ) -> ApiResponse:
        """Route an incoming HTTP request to the matching endpoint handler."""
        started = time.monotonic()
        request_id = self._new_id("req")
        method_upper = method.upper()
        mutating_method = method_upper in {"POST", "PUT", "PATCH", "DELETE"}
        try:
            parsed = urlparse(raw_path)
            request_path = parsed.path or "/"
            # Normalize incoming URL paths relative to the configured API base path.
            if self.base_path != "/" and request_path == self.base_path:
                subpath = "/"
            elif self.base_path == "/":
                subpath = request_path
            elif request_path.startswith(self.base_path + "/"):
                subpath = request_path[len(self.base_path) :]
            else:
                raise ApiError(404, "not_found", "Unknown API path.", details={"path": request_path})
            if not subpath.startswith("/"):
                subpath = "/" + subpath
            route, path_params = self.router.match(method_upper, subpath)
            if route is None:
                if self.router.allows_path(subpath):
                    raise ApiError(405, "method_not_allowed", "Method is not allowed for this path.")
                raise ApiError(404, "not_found", "Endpoint not found.")
            user = self._authorize(headers) if route.auth_required else None
            ctx = RequestContext(
                state=self,
                method=method_upper,
                path=subpath,
                path_params=path_params,
                query=parse_qs(parsed.query or "", keep_blank_values=True),
                headers=headers,
                body_bytes=body_bytes,
                request_id=request_id,
                user=user,
            )
            response = route.handler(ctx)
            if mutating_method:
                self._persist_database_state()
            return response
        except ApiError as exc:
            if mutating_method:
                self._persist_database_state()
            return self._error_response(
                request_id=request_id,
                status_code=exc.status_code,
                code=exc.code,
                message=exc.message,
                details=exc.details,
                retryable=exc.retryable,
            )
        except Exception as exc:
            if mutating_method:
                self._persist_database_state()
            return self._error_response(
                request_id=request_id,
                status_code=500,
                code="internal_error",
                message=str(exc),
                retryable=False,
            )
        finally:
            self._record_request_metric(started)

    # ----- Core endpoints -----
    def handle_root(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `root` API endpoint."""
        return self._json_response(
            200,
            {
                "ok": True,
                "name": "G4FAgent Dev Platform API",
                "version": self.version,
                "base_path": self.base_path,
                "endpoints": self.router.endpoint_list(),
            },
        )

    def handle_health(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `health` API endpoint."""
        return self._json_response(
            200,
            {
                "ok": True,
                "version": self.version,
                "build": self.build,
                "uptime_s": int(time.monotonic() - self.started_monotonic),
                "time": _utc_now_iso(),
            },
        )

    def handle_capabilities(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `capabilities` API endpoint."""
        return self._json_response(200, self.capabilities)

    def handle_server_stats(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `server_stats` API endpoint."""
        window_s = max(1, min(3600, _safe_int(_query_first(ctx.query, "window_s", "60"), 60)))
        cutoff = time.monotonic() - float(window_s)
        durations = [d for ts, d in self._request_metrics if ts >= cutoff]
        durations_sorted = sorted(durations)
        if durations_sorted:
            idx = max(0, min(len(durations_sorted) - 1, int(math.ceil(0.95 * len(durations_sorted))) - 1))
            p95_ms = int(round(durations_sorted[idx]))
        else:
            p95_ms = 0
        rps = round((len(durations) / float(window_s)), 4)

        ram_used = 0
        ram_total = 0
        try:
            import psutil  # type: ignore

            vm = psutil.virtual_memory()
            ram_used = int(vm.used)
            ram_total = int(vm.total)
            cpu_pct = float(psutil.cpu_percent(interval=None))
        except Exception:
            cpu_pct = 0.0
        return self._json_response(
            200,
            {
                "cpu": {"pct": cpu_pct},
                "ram": {"used_bytes": ram_used, "total_bytes": ram_total},
                "gpu": {"pct": 0.0, "vram_used_bytes": 0, "vram_total_bytes": 0},
                "network": {"rx_bps": 0, "tx_bps": 0},
                "requests": {"rps": rps, "p95_ms": p95_ms},
            },
        )

    # ----- Auth / identity -----
    def handle_auth_login(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `auth_login` API endpoint."""
        body = ctx.json(required=True)
        method = str(body.get("method", "")).strip().lower()
        with self._lock:
            if method == "password":
                email = str(body.get("email", "")).strip().lower()
                password = str(body.get("password", ""))
                matched_user: Optional[Dict[str, Any]] = None
                for user in self.users.values():
                    if str(user.get("email", "")).strip().lower() != email:
                        continue
                    if bool(user.get("disabled")):
                        raise ApiError(403, "forbidden", "User is disabled.")
                    if self.user_passwords.get(user["id"], "") != password:
                        break
                    matched_user = user
                    break
                if matched_user is None:
                    raise ApiError(401, "invalid_credentials", "Invalid email or password.")
                tokens = self._issue_tokens(matched_user["id"])
                return self._json_response(200, tokens)
            if method == "api_key":
                api_key = str(body.get("api_key", "")).strip()
                if api_key != self.api_key:
                    raise ApiError(401, "invalid_credentials", "Invalid API key.")
                admin = next(iter(self.users.values()))
                tokens = self._issue_tokens(admin["id"])
                return self._json_response(200, tokens)
        raise ApiError(400, "invalid_method", "Unsupported login method.")

    def handle_auth_refresh(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `auth_refresh` API endpoint."""
        body = ctx.json(required=True)
        refresh_token = str(body.get("refresh_token", "")).strip()
        if not refresh_token:
            raise ApiError(400, "invalid_request", "refresh_token is required.")
        with self._lock:
            entry = self.refresh_tokens.get(refresh_token)
            if not isinstance(entry, dict):
                raise ApiError(401, "invalid_refresh_token", "Refresh token is invalid.")
            if float(entry.get("expires_at", 0.0)) < time.time():
                self.refresh_tokens.pop(refresh_token, None)
                raise ApiError(401, "invalid_refresh_token", "Refresh token has expired.")
            user_id = str(entry.get("user_id", ""))
            user = self.users.get(user_id)
            if user is None or bool(user.get("disabled")):
                raise ApiError(401, "invalid_refresh_token", "Refresh token is invalid.")
            self.refresh_tokens.pop(refresh_token, None)
            return self._json_response(200, self._issue_tokens(user_id))

    def handle_auth_logout(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `auth_logout` API endpoint."""
        body = ctx.json(required=True)
        refresh_token = str(body.get("refresh_token", "")).strip()
        with self._lock:
            if refresh_token:
                self.refresh_tokens.pop(refresh_token, None)
        return self._json_response(200, {"ok": True})

    def handle_me(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `me` API endpoint."""
        if ctx.user is None:
            raise ApiError(401, "unauthorized", "Unauthorized.")
        return self._json_response(200, {"user": ctx.user})

    # ----- Providers -----
    def handle_providers_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `providers_list` API endpoint."""
        providers = self._provider_catalog()
        items, next_cursor = self._paginate_items(providers, ctx.query)
        return self._json_response(200, {"items": items, "next_cursor": next_cursor})

    def handle_providers_scan(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `providers_scan` API endpoint."""
        body = ctx.json(required=False)
        include = body.get("include")
        discovered = [item["id"] for item in self._provider_catalog()]
        if isinstance(include, list) and include:
            include_set = {str(x) for x in include}
            discovered = [pid for pid in discovered if pid in include_set]
        warnings: List[str] = []
        try:
            known = self.manager.list_agents()
            if not known:
                warnings.append("No agents loaded in current runtime config.")
        except Exception as exc:
            warnings.append(f"Provider scan warning: {exc}")
        return self._json_response(200, {"ok": True, "discovered": discovered, "warnings": warnings})

    def handle_provider_models(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `provider_models` API endpoint."""
        provider_id = str(ctx.path_params["provider_id"])
        all_models: List[str] = []
        try:
            all_models = list_known_model_names_for_provider(provider_id) or []
        except Exception:
            all_models = []
        if not all_models:
            all_models = list_known_model_names(include_defaults=True)
        q = (_query_first(ctx.query, "q", "") or "").strip().lower()
        capability = (_query_first(ctx.query, "capability", "") or "").strip().lower()
        items: List[Dict[str, Any]] = []
        for model_name in all_models:
            if q and q not in str(model_name).lower():
                continue
            capabilities = ["chat", "tools", "vision", "streaming"]
            if capability and capability not in capabilities:
                continue
            items.append({"id": str(model_name), "label": str(model_name), "context_tokens": 128000, "capabilities": capabilities, "pricing": {}})
        page, next_cursor = self._paginate_items(items, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_provider_test(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `provider_test` API endpoint."""
        _ = ctx.json(required=False)
        latency = random.randint(20, 200)
        provider_id = str(ctx.path_params["provider_id"])
        return self._json_response(200, {"ok": True, "latency_ms": latency, "details": f"{provider_id} provider check succeeded"})

    # ----- Settings -----
    def handle_settings_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `settings_get` API endpoint."""
        return self._json_response(200, {"settings": self.settings})

    def _collect_settings_changes(self, current: Any, updates: Any, prefix: str = "") -> List[Dict[str, Any]]:
        """Collect settings changes."""
        changes: List[Dict[str, Any]] = []
        if not isinstance(current, dict) or not isinstance(updates, dict):
            if current != updates:
                changes.append({"path": prefix or "/", "from": current, "to": updates})
            return changes
        for key, new_value in updates.items():
            path = f"{prefix}/{key}" if prefix else f"/{key}"
            old_value = current.get(key)
            if isinstance(old_value, dict) and isinstance(new_value, dict):
                changes.extend(self._collect_settings_changes(old_value, new_value, path))
            elif old_value != new_value:
                changes.append({"path": path, "from": old_value, "to": new_value})
        return changes

    def _deep_merge(self, current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Apply merge."""
        merged = dict(current)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(dict(merged.get(key) or {}), value)
            else:
                merged[key] = value
        return merged

    def handle_settings_put(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `settings_put` API endpoint."""
        body = ctx.json(required=True)
        actor = (ctx.user or {}).get("id", "unknown")
        with self._lock:
            changes = self._collect_settings_changes(self.settings, body)
            self.settings = self._deep_merge(self.settings, body)
            for change in changes:
                event = {
                    "id": self._new_id("setaudit"),
                    "ts": _utc_now_iso(),
                    "actor_user_id": actor,
                    "change": change,
                }
                self.settings_audit_events.append(event)
            if changes:
                self._record_audit(actor, "settings.updated", {"changes": changes})
        return self._json_response(200, {"ok": True})

    def handle_settings_audit(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `settings_audit` API endpoint."""
        items, next_cursor = self._paginate_items(list(self.settings_audit_events), ctx.query)
        return self._json_response(200, {"items": items, "next_cursor": next_cursor})

    # ----- Projects -----
    def handle_projects_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `projects_list` API endpoint."""
        q = (_query_first(ctx.query, "q", "") or "").strip().lower()
        status = (_query_first(ctx.query, "status", "") or "").strip().lower()
        environment = (_query_first(ctx.query, "environment", "") or "").strip().lower()
        projects = list(self.projects.values())
        filtered: List[Dict[str, Any]] = []
        for project in projects:
            if q and q not in str(project.get("name", "")).lower():
                continue
            if status and status != str(project.get("status", "")).lower():
                continue
            if environment and environment != str(project.get("environment", "")).lower():
                continue
            filtered.append(project)
        items, next_cursor = self._paginate_items(filtered, ctx.query)
        return self._json_response(200, {"items": items, "next_cursor": next_cursor})

    def handle_projects_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `projects_create` API endpoint."""
        body = ctx.json(required=True)
        name = str(body.get("name", "")).strip()
        if not name:
            raise ApiError(400, "invalid_request", "name is required.")
        project_id = self._new_id("proj")
        now_ts = _utc_now_iso()
        environment = str(body.get("environment", "dev") or "dev")
        project = {
            "id": project_id,
            "name": name,
            "description": str(body.get("description", "")),
            "status": str(body.get("status", "active") or "active"),
            "environment": environment,
            "last_commit": "",
            "repo": dict(body.get("repo", {}) or {}),
            "stats": {"sessions": 0, "runs_24h": 0},
            "created_at": now_ts,
            "updated_at": now_ts,
        }
        project_dir = self.workspace_dir / f"{_slugify(name)}-{project_id[-8:]}"
        project_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.projects[project_id] = project
            self.project_paths[project_id] = project_dir
            self.project_sessions[project_id] = []
            self.project_diffs[project_id] = []
            self.project_deployments[project_id] = []
            self.project_workflows[project_id] = []
            self.project_artifacts[project_id] = []
            self._record_audit((ctx.user or {}).get("id", "unknown"), "project.created", {"project_id": project_id}, project_id=project_id)
        return self._json_response(200, {"project": project})

    def handle_projects_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `projects_get` API endpoint."""
        project = self._ensure_project(str(ctx.path_params["project_id"]))
        return self._json_response(200, {"project": project})

    def handle_projects_patch(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `projects_patch` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        project = self._ensure_project(project_id)
        body = ctx.json(required=True)
        allowed = {"name", "description", "environment", "status", "repo"}
        for key, value in body.items():
            if key in allowed:
                project[key] = value
        project["updated_at"] = _utc_now_iso()
        self._record_audit((ctx.user or {}).get("id", "unknown"), "project.updated", {"project_id": project_id, "changes": body}, project_id=project_id)
        return self._json_response(200, {"ok": True})

    def handle_projects_delete(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `projects_delete` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        with self._lock:
            self.projects.pop(project_id, None)
            self.project_paths.pop(project_id, None)
            for sid in self.project_sessions.pop(project_id, []):
                self.sessions.pop(sid, None)
            self.project_diffs.pop(project_id, None)
            self.project_deployments.pop(project_id, None)
            self.project_workflows.pop(project_id, None)
            self.project_artifacts.pop(project_id, None)
        self._record_audit((ctx.user or {}).get("id", "unknown"), "project.deleted", {"project_id": project_id}, project_id=project_id)
        return self._json_response(200, {"ok": True})

    # ----- Sessions / messages -----
    def handle_project_sessions_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_sessions_list` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        ids = list(self.project_sessions.get(project_id, []))
        q = (_query_first(ctx.query, "q", "") or "").strip().lower()
        status = (_query_first(ctx.query, "status", "") or "").strip().lower()
        sessions = [self.sessions[sid] for sid in ids if sid in self.sessions]
        filtered: List[Dict[str, Any]] = []
        for session in sessions:
            if q and q not in str(session.get("title", "")).lower():
                continue
            if status and status != str(session.get("status", "")).lower():
                continue
            filtered.append(session)
        items, next_cursor = self._paginate_items(filtered, ctx.query)
        return self._json_response(200, {"items": items, "next_cursor": next_cursor})

    def handle_project_sessions_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_sessions_create` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        project = self._ensure_project(project_id)
        body = ctx.json(required=True)
        title = str(body.get("title", "")).strip()
        provider_id = str(body.get("provider_id", self.settings.get("default_provider_id", "g4f")))
        model_id = str(body.get("model_id", self.settings.get("default_model_id", "gpt-4o-mini")))
        if not title:
            raise ApiError(400, "invalid_request", "title is required.")
        if not model_id:
            raise ApiError(400, "invalid_request", "model_id is required.")
        now_ts = _utc_now_iso()
        session_id = self._new_id("sess")
        session = {
            "id": session_id,
            "project_id": project_id,
            "title": title,
            "status": str(body.get("status", "active") or "active"),
            "provider_id": provider_id,
            "model_id": model_id,
            "config": dict(body.get("config", {}) or {}),
            "memory": dict(body.get("memory", {}) or {}),
            "tags": list(body.get("tags", []) or []),
            "created_at": now_ts,
            "updated_at": now_ts,
        }
        with self._lock:
            self.sessions[session_id] = session
            self.project_sessions.setdefault(project_id, []).append(session_id)
            self.session_messages[session_id] = []
            self.session_runs[session_id] = []
            project["stats"]["sessions"] = int(project.get("stats", {}).get("sessions", 0)) + 1
            project["updated_at"] = now_ts
            self._record_audit((ctx.user or {}).get("id", "unknown"), "session.created", {"session_id": session_id}, project_id=project_id)
        return self._json_response(200, {"session": session})

    def handle_sessions_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `sessions_get` API endpoint."""
        session = self._ensure_session(str(ctx.path_params["session_id"]))
        return self._json_response(200, {"session": session})

    def handle_sessions_patch(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `sessions_patch` API endpoint."""
        session_id = str(ctx.path_params["session_id"])
        session = self._ensure_session(session_id)
        body = ctx.json(required=True)
        allowed = {"title", "status", "provider_id", "model_id", "config", "memory", "tags"}
        for key, value in body.items():
            if key in allowed:
                session[key] = value
        session["updated_at"] = _utc_now_iso()
        self._record_audit((ctx.user or {}).get("id", "unknown"), "session.updated", {"session_id": session_id, "changes": body}, project_id=session["project_id"])
        return self._json_response(200, {"ok": True})

    def handle_session_messages_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `session_messages_list` API endpoint."""
        session_id = str(ctx.path_params["session_id"])
        _ = self._ensure_session(session_id)
        after_ts = _coerce_iso(_query_first(ctx.query, "after_ts", "") or "")
        before_ts = _coerce_iso(_query_first(ctx.query, "before_ts", "") or "")
        message_ids = list(self.session_messages.get(session_id, []))
        messages = [self.messages[mid] for mid in message_ids if mid in self.messages]
        filtered: List[Dict[str, Any]] = []
        for message in messages:
            msg_ts = _coerce_iso(str(message.get("ts", "")))
            if after_ts and msg_ts and msg_ts <= after_ts:
                continue
            if before_ts and msg_ts and msg_ts >= before_ts:
                continue
            filtered.append(message)
        page, next_cursor = self._paginate_items(filtered, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_session_messages_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `session_messages_create` API endpoint."""
        session_id = str(ctx.path_params["session_id"])
        _ = self._ensure_session(session_id)
        body = ctx.json(required=True)
        role = str(body.get("role", "")).strip()
        content = body.get("content")
        if not role:
            raise ApiError(400, "invalid_request", "role is required.")
        if not isinstance(content, list):
            raise ApiError(400, "invalid_request", "content must be an array.")
        message_id = self._new_id("msg")
        message = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "meta": dict(body.get("meta", {}) or {}),
            "ts": _utc_now_iso(),
        }
        with self._lock:
            self.messages[message_id] = message
            self.session_messages.setdefault(session_id, []).append(message_id)
        return self._json_response(200, {"message_id": message_id})

    def _message_to_text(self, message: Dict[str, Any]) -> str:
        """Transform to text."""
        content = message.get("content")
        if not isinstance(content, list):
            return ""
        parts: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "text"))
            if item_type == "text":
                parts.append(str(item.get("text", "")))
            elif item_type == "code":
                parts.append(str(item.get("text", "")))
            elif item_type == "json":
                parts.append(json.dumps(item.get("value"), ensure_ascii=False))
            elif item_type == "image":
                parts.append(f"[image] {item.get('url', '')}")
            elif item_type == "diff_ref":
                parts.append(f"[diff_ref] {item.get('diff_id', '')}")
            elif item_type == "tool_call":
                parts.append(f"[tool_call] {item.get('tool_name', '')}")
            elif item_type == "tool_result":
                parts.append(f"[tool_result] {item.get('tool_name', '')}")
        return "\n".join([p for p in parts if p.strip()]).strip()

    def _append_run_event(self, run_id: str, event: Dict[str, Any]) -> None:
        """Append run event."""
        self.run_events.setdefault(run_id, []).append(event)

    def _execute_run_worker(self, run_id: str) -> None:
        """Execute run worker."""
        with self._lock:
            run = self.runs.get(run_id)
            if run is None:
                return
            if run.get("status") == "canceled":
                return
            # Transition the queued run to running before invoking the model manager.
            run["status"] = "running"
            run["progress"] = 0.05
            run["started_at"] = _utc_now_iso()
            self._append_run_event(run_id, {"type": "status", "ts": _utc_now_iso(), "status": "running", "progress": 0.05})
        self._persist_database_state()
        try:
            session_id = str(run.get("session_id", ""))
            session = self._ensure_session(session_id)
            input_payload = dict(run.get("_request", {}).get("input", {}) or {})
            message_id = str(input_payload.get("message_id", "")).strip()
            message = self.messages.get(message_id)
            if message is None:
                raise ApiError(400, "invalid_request", "Input message_id was not found.")
            prompt_text = self._message_to_text(message)
            instructions = str(((run.get("_request", {}).get("agent", {}) or {}).get("instructions", "")) or "")
            messages = []
            if instructions.strip():
                messages.append({"role": "system", "content": instructions.strip()})
            messages.append({"role": "user", "content": prompt_text})
            model_name = str(session.get("model_id", "gpt-4o-mini") or "gpt-4o-mini")
            response_text = self.manager.chat(messages=messages, model=model_name, provider=None, create_kwargs={}, max_retries=0)
            with self._lock:
                run_latest = self.runs.get(run_id)
                if run_latest is None:
                    return
                if run_latest.get("status") == "canceled":
                    self._append_run_event(run_id, {"type": "status", "ts": _utc_now_iso(), "status": "canceled", "progress": 1.0})
                    return
                assistant_message_id = self._new_id("msg")
                assistant_message = {
                    "id": assistant_message_id,
                    "session_id": session_id,
                    "role": "assistant",
                    "content": [{"type": "text", "text": str(response_text)}],
                    "meta": {},
                    "ts": _utc_now_iso(),
                }
                self.messages[assistant_message_id] = assistant_message
                self.session_messages.setdefault(session_id, []).append(assistant_message_id)
                run_latest["status"] = "completed"
                run_latest["progress"] = 1.0
                run_latest["ended_at"] = _utc_now_iso()
                run_latest["result"] = {
                    "summary": str(response_text)[:2000],
                    "message_id": assistant_message_id,
                    "diff_ids": [],
                }
                run_latest["usage"] = {
                    "input_tokens": max(1, len(prompt_text.split())),
                    "output_tokens": max(1, len(str(response_text).split())),
                    "cost_usd": 0.0,
                }
                self._append_run_event(
                    run_id,
                    {"type": "token", "ts": _utc_now_iso(), "message_id": assistant_message_id, "text": str(response_text)},
                )
                self._append_run_event(
                    run_id,
                    {"type": "status", "ts": _utc_now_iso(), "status": "completed", "progress": 1.0},
                )
                self._record_audit("system", "run.completed", {"run_id": run_id}, project_id=session.get("project_id"))
            self._persist_database_state()
        except Exception as exc:
            with self._lock:
                run_latest = self.runs.get(run_id)
                if run_latest is None:
                    return
                if run_latest.get("status") == "canceled":
                    return
                run_latest["status"] = "failed"
                run_latest["progress"] = 1.0
                run_latest["ended_at"] = _utc_now_iso()
                self._append_run_event(
                    run_id,
                    {
                        "type": "error",
                        "ts": _utc_now_iso(),
                        "error": {"code": "run_failed", "message": str(exc)},
                    },
                )
                self._append_run_event(
                    run_id,
                    {"type": "status", "ts": _utc_now_iso(), "status": "failed", "progress": 1.0},
                )
            self._persist_database_state()

    def handle_session_runs_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `session_runs_create` API endpoint."""
        session_id = str(ctx.path_params["session_id"])
        session = self._ensure_session(session_id)
        body = ctx.json(required=True)
        mode = str(body.get("mode", "")).strip()
        agent = body.get("agent")
        input_payload = body.get("input")
        if not mode:
            raise ApiError(400, "invalid_request", "mode is required.")
        if not isinstance(agent, dict):
            raise ApiError(400, "invalid_request", "agent is required.")
        if not isinstance(input_payload, dict):
            raise ApiError(400, "invalid_request", "input is required.")
        run_id = self._new_id("run")
        run = {
            "id": run_id,
            "session_id": session_id,
            "status": "queued",
            "progress": 0.0,
            "started_at": _utc_now_iso(),
            "ended_at": None,
            "result": {},
            "usage": {},
            "_request": body,
        }
        with self._lock:
            self.runs[run_id] = run
            self.session_runs.setdefault(session_id, []).append(run_id)
            self.run_events[run_id] = [{"type": "status", "ts": _utc_now_iso(), "status": "queued", "progress": 0.0}]
            t = threading.Thread(target=self._execute_run_worker, args=(run_id,), daemon=True)
            self._run_threads[run_id] = t
            t.start()
            project = self.projects.get(session["project_id"])
            if project is not None:
                stats = dict(project.get("stats", {}) or {})
                stats["runs_24h"] = int(stats.get("runs_24h", 0)) + 1
                project["stats"] = stats
        return self._json_response(200, {"run_id": run_id})

    def handle_runs_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `runs_get` API endpoint."""
        run = self._ensure_run(str(ctx.path_params["run_id"]))
        run_copy = dict(run)
        run_copy.pop("_request", None)
        return self._json_response(200, {"run": run_copy})

    def handle_runs_cancel(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `runs_cancel` API endpoint."""
        run_id = str(ctx.path_params["run_id"])
        run = self._ensure_run(run_id)
        with self._lock:
            if run.get("status") not in {"completed", "failed", "canceled"}:
                run["status"] = "canceled"
                run["progress"] = 1.0
                run["ended_at"] = _utc_now_iso()
                self._append_run_event(run_id, {"type": "status", "ts": _utc_now_iso(), "status": "canceled", "progress": 1.0})
        return self._json_response(200, {"ok": True})

    def handle_runs_events(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `runs_events` API endpoint."""
        run_id = str(ctx.path_params["run_id"])
        _ = self._ensure_run(run_id)
        events = list(self.run_events.get(run_id, []))
        page, next_cursor = self._paginate_items(events, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    # ----- Tools -----
    def handle_tools_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `tools_list` API endpoint."""
        scope_filter = (_query_first(ctx.query, "scope", "") or "").strip().lower()
        q = (_query_first(ctx.query, "q", "") or "").strip().lower()
        items: List[Dict[str, Any]] = []
        runtime = self._runtime_for_project(None)
        for tool_name in runtime.available_tools():
            item = {
                "id": tool_name,
                "name": tool_name,
                "scope": "global",
                "description": f"Built-in tool: {tool_name}",
                "schema": {"type": "object", "additionalProperties": True},
                "created_at": _utc_now_iso(),
            }
            items.append(item)
        for tool in self.dynamic_tools.values():
            items.append(
                {
                    "id": tool["id"],
                    "name": tool["name"],
                    "scope": tool["scope"],
                    "description": tool["description"],
                    "schema": tool.get("schema", {}),
                    "created_at": tool["created_at"],
                }
            )
        filtered: List[Dict[str, Any]] = []
        for item in items:
            if scope_filter and scope_filter != str(item.get("scope", "")).lower():
                continue
            if q and q not in str(item.get("name", "")).lower() and q not in str(item.get("description", "")).lower():
                continue
            filtered.append(item)
        page, next_cursor = self._paginate_items(filtered, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_tools_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `tools_create` API endpoint."""
        body = ctx.json(required=True)
        for required_key in ("name", "scope", "description", "schema", "handler"):
            if required_key not in body:
                raise ApiError(400, "invalid_request", f"Missing required field: {required_key}")
        tool_id = self._new_id("tool")
        tool = {
            "id": tool_id,
            "name": str(body["name"]),
            "scope": str(body["scope"]),
            "description": str(body["description"]),
            "schema": body["schema"],
            "handler": body["handler"],
            "created_at": _utc_now_iso(),
        }
        self.dynamic_tools[tool_id] = tool
        return self._json_response(200, {"tool_id": tool_id})

    def handle_tools_delete(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `tools_delete` API endpoint."""
        tool_id = str(ctx.path_params["tool_id"])
        if tool_id in self.dynamic_tools:
            self.dynamic_tools.pop(tool_id, None)
            return self._json_response(200, {"ok": True})
        raise ApiError(404, "tool_not_found", f"Dynamic tool not found: {tool_id}")

    def _invoke_dynamic_tool(self, tool: Dict[str, Any], args: Dict[str, Any]) -> Tuple[bool, Any]:
        """Execute a dynamic tool handler using Python or HTTP."""
        handler = dict(tool.get("handler", {}) or {})
        handler_type = str(handler.get("type", "")).strip().lower()
        if handler_type == "python":
            module_name = str(handler.get("module", "")).strip()
            fn_name = str(handler.get("fn", "")).strip()
            if not module_name or not fn_name:
                return False, {"error": "python handler requires module and fn"}
            module = importlib.import_module(module_name)
            fn = getattr(module, fn_name)
            if isinstance(args, dict):
                result = fn(**args)
            else:
                result = fn(args)
            return True, result
        if handler_type == "http":
            url = str(handler.get("url", "")).strip()
            if not url:
                return False, {"error": "http handler requires url"}
            raw_headers = dict(handler.get("headers", {}) or {})
            headers = {"Content-Type": "application/json"}
            headers.update({str(k): str(v) for k, v in raw_headers.items()})
            req = Request(url=url, method="POST", headers=headers, data=json.dumps(args).encode("utf-8"))
            with urlopen(req, timeout=20) as resp:
                payload = resp.read()
                text = payload.decode("utf-8", errors="replace")
                try:
                    return True, json.loads(text)
                except Exception:
                    return True, {"text": text}
        return False, {"error": f"Unsupported handler type: {handler_type}"}

    def handle_tools_invoke(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `tools_invoke` API endpoint."""
        tool_id = str(ctx.path_params["tool_id"])
        body = ctx.json(required=True)
        args = body.get("args")
        if not isinstance(args, dict):
            raise ApiError(400, "invalid_request", "args must be an object.")
        context = body.get("context")
        project_id = None
        if isinstance(context, dict):
            project_id_raw = context.get("project_id")
            if isinstance(project_id_raw, str) and project_id_raw.strip():
                project_id = project_id_raw.strip()
        if tool_id in self.dynamic_tools:
            ok, result = self._invoke_dynamic_tool(self.dynamic_tools[tool_id], args)
            return self._json_response(200, {"ok": ok, "result": result})
        runtime = self._runtime_for_project(project_id)
        result = runtime.execute(tool_id, args)
        payload = result.data if result.data is not None else {"output": result.output}
        return self._json_response(200, {"ok": bool(result.ok), "result": payload})

    # ----- Files -----
    def handle_files_tree(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_tree` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        root_param = _query_first(ctx.query, "root", "/") or "/"
        depth = max(1, min(20, _safe_int(_query_first(ctx.query, "depth", "4"), 4)))
        include_hidden = _query_bool(ctx.query, "include_hidden", False)
        project_root = self._ensure_project_path(project_id)
        root_path = project_root if root_param == "/" else self._safe_project_file_path(project_id, root_param)
        if not root_path.exists():
            raise ApiError(404, "not_found", f"Path not found: {root_param}")
        items: List[Dict[str, Any]] = []
        start_depth = len(root_path.parts)
        if root_path.is_file():
            rel = str(root_path.relative_to(project_root)).replace("\\", "/")
            stat = root_path.stat()
            items.append({"path": rel, "type": "file", "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(), "size_bytes": stat.st_size})
        else:
            for current_root, dirs, files in os.walk(root_path):
                current_path = Path(current_root)
                current_depth = len(current_path.parts) - start_depth
                if current_depth >= depth:
                    dirs[:] = []
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    files = [f for f in files if not f.startswith(".")]
                for d in dirs:
                    abs_dir = current_path / d
                    rel = str(abs_dir.relative_to(project_root)).replace("\\", "/")
                    stat = abs_dir.stat()
                    items.append({"path": rel, "type": "dir", "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(), "size_bytes": 0})
                for f in files:
                    abs_file = current_path / f
                    rel = str(abs_file.relative_to(project_root)).replace("\\", "/")
                    stat = abs_file.stat()
                    items.append({"path": rel, "type": "file", "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(), "size_bytes": stat.st_size})
        return self._json_response(200, {"root": root_param, "items": items})

    def handle_files_get_content(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_get_content` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        rel_path = _query_first(ctx.query, "path", "")
        if not rel_path:
            raise ApiError(400, "invalid_request", "path query parameter is required.")
        abs_path = self._safe_project_file_path(project_id, rel_path)
        if not abs_path.exists() or not abs_path.is_file():
            raise ApiError(404, "not_found", f"File not found: {rel_path}")
        text = abs_path.read_text(encoding="utf-8", errors="replace")
        return self._json_response(200, {"path": str(rel_path), "encoding": "utf-8", "text": text, "etag": _sha256_text(text)})

    def handle_files_put_content(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_put_content` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        body = ctx.json(required=True)
        rel_path = str(body.get("path", "")).strip()
        text = body.get("text")
        etag = body.get("etag")
        if not rel_path:
            raise ApiError(400, "invalid_request", "path is required.")
        if not isinstance(text, str):
            raise ApiError(400, "invalid_request", "text must be a string.")
        abs_path = self._safe_project_file_path(project_id, rel_path)
        if abs_path.exists() and isinstance(etag, str) and etag.strip():
            current = abs_path.read_text(encoding="utf-8", errors="replace")
            if _sha256_text(current) != etag.strip():
                raise ApiError(409, "etag_conflict", "File has changed since the provided etag.")
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(text, encoding="utf-8")
        return self._json_response(200, {"ok": True, "etag": _sha256_text(text)})

    def handle_files_batch(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_batch` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        body = ctx.json(required=False)
        reads = body.get("reads")
        writes = body.get("writes")
        read_results: List[Dict[str, Any]] = []
        write_results: List[Dict[str, Any]] = []
        if isinstance(reads, list):
            for read in reads:
                path = ""
                if isinstance(read, dict):
                    path = str(read.get("path", "")).strip()
                if not path:
                    read_results.append({"path": path, "ok": False, "error": {"code": "invalid_request", "message": "path is required"}})
                    continue
                try:
                    abs_path = self._safe_project_file_path(project_id, path)
                    if not abs_path.exists() or not abs_path.is_file():
                        raise ApiError(404, "not_found", f"File not found: {path}")
                    text = abs_path.read_text(encoding="utf-8", errors="replace")
                    read_results.append({"path": path, "ok": True, "text": text, "etag": _sha256_text(text)})
                except ApiError as exc:
                    read_results.append({"path": path, "ok": False, "error": {"code": exc.code, "message": exc.message}})
        if isinstance(writes, list):
            for write in writes:
                path = ""
                text = None
                etag = None
                if isinstance(write, dict):
                    path = str(write.get("path", "")).strip()
                    text = write.get("text")
                    etag = write.get("etag")
                if not path or not isinstance(text, str):
                    write_results.append({"path": path, "ok": False, "error": {"code": "invalid_request", "message": "path and text are required"}})
                    continue
                try:
                    abs_path = self._safe_project_file_path(project_id, path)
                    if abs_path.exists() and isinstance(etag, str) and etag.strip():
                        current = abs_path.read_text(encoding="utf-8", errors="replace")
                        if _sha256_text(current) != etag.strip():
                            raise ApiError(409, "etag_conflict", "File has changed.")
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(text, encoding="utf-8")
                    write_results.append({"path": path, "ok": True, "etag": _sha256_text(text)})
                except ApiError as exc:
                    write_results.append({"path": path, "ok": False, "error": {"code": exc.code, "message": exc.message}})
        return self._json_response(200, {"reads": read_results, "writes": write_results})

    def handle_files_lint(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_lint` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        body = ctx.json(required=True)
        paths = body.get("paths")
        if not isinstance(paths, list):
            raise ApiError(400, "invalid_request", "paths is required and must be an array.")
        diagnostics: List[Dict[str, Any]] = []
        for raw in paths:
            rel_path = str(raw).strip()
            if not rel_path:
                continue
            abs_path = self._safe_project_file_path(project_id, rel_path)
            if not abs_path.exists():
                diagnostics.append({"path": rel_path, "line": 1, "col": 1, "severity": "error", "code": "file_not_found", "message": "File not found"})
        return self._json_response(200, {"diagnostics": diagnostics})

    def handle_files_format(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_format` API endpoint."""
        _ = ctx.json(required=True)
        return self._json_response(200, {"ok": True})

    def handle_files_search(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_search` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        body = ctx.json(required=True)
        query_text = str(body.get("q", "")).strip()
        if not query_text:
            raise ApiError(400, "invalid_request", "q is required.")
        search_paths = body.get("paths")
        case_sensitive = bool(body.get("case_sensitive", False))
        regex = bool(body.get("regex", False))
        root = self._ensure_project_path(project_id)
        targets: List[Path] = []
        if isinstance(search_paths, list) and search_paths:
            for raw in search_paths:
                rel = str(raw).strip()
                if not rel:
                    continue
                p = self._safe_project_file_path(project_id, rel)
                if p.is_dir():
                    targets.extend([x for x in p.rglob("*") if x.is_file()])
                elif p.is_file():
                    targets.append(p)
        else:
            targets = [x for x in root.rglob("*") if x.is_file()]
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query_text, flags) if regex else None
        matches: List[Dict[str, Any]] = []
        for path in targets:
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
                for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    found = bool(pattern.search(line)) if pattern is not None else ((query_text in line) if case_sensitive else (query_text.lower() in line.lower()))
                    if found:
                        matches.append({"path": rel, "line": idx, "preview": line[:500]})
                        if len(matches) >= 5000:
                            return self._json_response(200, {"matches": matches})
            except Exception:
                continue
        return self._json_response(200, {"matches": matches})

    # ----- Diffs -----
    def _parse_diff_stats(self, patch: str) -> Tuple[int, int]:
        """Parse diff stats data from the provided input."""
        added = 0
        removed = 0
        for line in patch.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
        return added, removed

    def _parse_diff_files(self, patch: str) -> List[Dict[str, Any]]:
        """Parse diff files data from the provided input."""
        files: Dict[str, Dict[str, Any]] = {}
        current_path = ""
        current_lines: List[str] = []
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                if current_path:
                    block = "\n".join(current_lines)
                    a, r = self._parse_diff_stats(block)
                    files[current_path] = {"path": current_path, "patch": block, "added": a, "removed": r}
                current_path = line[6:].strip()
                current_lines = [line]
            elif line.startswith("+++ "):
                if current_path:
                    block = "\n".join(current_lines)
                    a, r = self._parse_diff_stats(block)
                    files[current_path] = {"path": current_path, "patch": block, "added": a, "removed": r}
                current_path = line[4:].strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        if current_path:
            block = "\n".join(current_lines)
            a, r = self._parse_diff_stats(block)
            files[current_path] = {"path": current_path, "patch": block, "added": a, "removed": r}
        if not files:
            added, removed = self._parse_diff_stats(patch)
            return [{"path": "", "patch": patch, "added": added, "removed": removed}]
        return list(files.values())

    def handle_project_diffs_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_diffs_list` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        status_filter = (_query_first(ctx.query, "status", "") or "").strip().lower()
        diff_ids = list(self.project_diffs.get(project_id, []))
        items: List[Dict[str, Any]] = []
        for diff_id in diff_ids:
            diff = self.diffs.get(diff_id)
            if not diff:
                continue
            if status_filter and status_filter != str(diff.get("status", "")).lower():
                continue
            items.append(diff)
        page, next_cursor = self._paginate_items(items, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_project_diffs_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_diffs_create` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        body = ctx.json(required=True)
        title = str(body.get("title", "")).strip()
        patch = str(body.get("patch", ""))
        if not title or not patch:
            raise ApiError(400, "invalid_request", "title and patch are required.")
        diff_id = self._new_id("diff")
        added, removed = self._parse_diff_stats(patch)
        files = self._parse_diff_files(patch)
        diff = {
            "id": diff_id,
            "project_id": project_id,
            "title": title,
            "status": "open",
            "stats": {"added": added, "removed": removed},
            "files": files,
            "base_rev": str(body.get("base_rev", "HEAD") or "HEAD"),
            "created_at": _utc_now_iso(),
            "_raw_patch": patch,
            "_comments": [],
        }
        with self._lock:
            self.diffs[diff_id] = diff
            self.project_diffs.setdefault(project_id, []).append(diff_id)
        return self._json_response(200, {"diff_id": diff_id})

    def handle_diffs_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `diffs_get` API endpoint."""
        diff_id = str(ctx.path_params["diff_id"])
        diff = self.diffs.get(diff_id)
        if diff is None:
            raise ApiError(404, "diff_not_found", f"Diff not found: {diff_id}")
        payload = dict(diff)
        payload.pop("_raw_patch", None)
        payload.pop("_comments", None)
        return self._json_response(200, {"diff": payload})

    def handle_diffs_apply(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `diffs_apply` API endpoint."""
        diff_id = str(ctx.path_params["diff_id"])
        diff = self.diffs.get(diff_id)
        if diff is None:
            raise ApiError(404, "diff_not_found", f"Diff not found: {diff_id}")
        if diff.get("status") != "open":
            raise ApiError(400, "invalid_state", "Only open diffs can be applied.")
        body = ctx.json(required=False)
        commit_message = str(body.get("commit_message", "")).strip() if isinstance(body, dict) else ""
        project_root = self._ensure_project_path(str(diff["project_id"]))
        patch_text = str(diff.get("_raw_patch", ""))
        ok = False
        commit_hash = ""
        try:
            proc = subprocess.run(
                ["git", "-C", str(project_root), "apply", "--whitespace=nowarn", "-"],
                input=patch_text,
                text=True,
                capture_output=True,
                check=False,
            )
            ok = proc.returncode == 0
            if ok and commit_message:
                _ = subprocess.run(["git", "-C", str(project_root), "add", "-A"], check=False, capture_output=True, text=True)
                commit_proc = subprocess.run(
                    ["git", "-C", str(project_root), "commit", "-m", commit_message],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if commit_proc.returncode == 0:
                    rev = subprocess.run(["git", "-C", str(project_root), "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
                    if rev.returncode == 0:
                        commit_hash = rev.stdout.strip()
        except Exception:
            ok = False
        if ok:
            diff["status"] = "applied"
        return self._json_response(200, {"ok": ok, "commit": commit_hash})

    def handle_diffs_discard(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `diffs_discard` API endpoint."""
        diff_id = str(ctx.path_params["diff_id"])
        diff = self.diffs.get(diff_id)
        if diff is None:
            raise ApiError(404, "diff_not_found", f"Diff not found: {diff_id}")
        diff["status"] = "discarded"
        return self._json_response(200, {"ok": True})

    def handle_diffs_comment(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `diffs_comment` API endpoint."""
        diff_id = str(ctx.path_params["diff_id"])
        diff = self.diffs.get(diff_id)
        if diff is None:
            raise ApiError(404, "diff_not_found", f"Diff not found: {diff_id}")
        body = ctx.json(required=True)
        for key in ("path", "line", "comment"):
            if key not in body:
                raise ApiError(400, "invalid_request", f"{key} is required.")
        comment = {
            "path": str(body["path"]),
            "line": int(body["line"]),
            "comment": str(body["comment"]),
            "ts": _utc_now_iso(),
            "author": (ctx.user or {}).get("id", "unknown"),
        }
        diff.setdefault("_comments", []).append(comment)
        return self._json_response(200, {"ok": True})

    # ----- Repo -----
    def _run_repo_cmd(self, project_id: str, args: List[str], *, input_text: Optional[str] = None) -> subprocess.CompletedProcess[str]:
        """Run repo cmd and return its result."""
        root = self._ensure_project_path(project_id)
        return subprocess.run(
            ["git", "-C", str(root), *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )

    def handle_repo_status(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `repo_status` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        proc = self._run_repo_cmd(project_id, ["status", "--porcelain=1", "-b"])
        if proc.returncode != 0:
            raise ApiError(400, "repo_not_available", proc.stderr.strip() or "git status failed")
        lines = [line.rstrip("\n") for line in proc.stdout.splitlines()]
        branch = ""
        ahead = 0
        behind = 0
        changes: List[Dict[str, Any]] = []
        if lines and lines[0].startswith("## "):
            head = lines[0][3:]
            branch = head.split("...", 1)[0].strip()
            ahead_match = re.search(r"ahead\s+(\d+)", head)
            behind_match = re.search(r"behind\s+(\d+)", head)
            if ahead_match:
                ahead = int(ahead_match.group(1))
            if behind_match:
                behind = int(behind_match.group(1))
            lines = lines[1:]
        for line in lines:
            if not line:
                continue
            status_chunk = line[:2]
            path_chunk = line[3:].strip()
            code = "modified"
            if "A" in status_chunk:
                code = "added"
            elif "D" in status_chunk:
                code = "deleted"
            elif "R" in status_chunk:
                code = "renamed"
            elif status_chunk == "??":
                code = "untracked"
            changes.append({"path": path_chunk, "status": code})
        return self._json_response(200, {"branch": branch, "dirty": bool(changes), "ahead": ahead, "behind": behind, "changes": changes})

    def handle_repo_checkout(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `repo_checkout` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        body = ctx.json(required=True)
        branch = str(body.get("branch", "")).strip()
        if not branch:
            raise ApiError(400, "invalid_request", "branch is required.")
        proc = self._run_repo_cmd(project_id, ["checkout", branch])
        if proc.returncode != 0:
            raise ApiError(400, "git_checkout_failed", proc.stderr.strip() or "git checkout failed")
        return self._json_response(200, {"ok": True})

    def handle_repo_pull(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `repo_pull` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        proc = self._run_repo_cmd(project_id, ["pull", "--ff-only"])
        if proc.returncode != 0:
            raise ApiError(400, "git_pull_failed", proc.stderr.strip() or "git pull failed")
        return self._json_response(200, {"ok": True})

    def handle_repo_commit(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `repo_commit` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        body = ctx.json(required=True)
        message = str(body.get("message", "")).strip()
        if not message:
            raise ApiError(400, "invalid_request", "message is required.")
        paths = body.get("paths")
        if isinstance(paths, list) and paths:
            add_args = ["add", *[str(p) for p in paths]]
        else:
            add_args = ["add", "-A"]
        add_proc = self._run_repo_cmd(project_id, add_args)
        if add_proc.returncode != 0:
            raise ApiError(400, "git_add_failed", add_proc.stderr.strip() or "git add failed")
        commit_proc = self._run_repo_cmd(project_id, ["commit", "-m", message])
        if commit_proc.returncode != 0:
            raise ApiError(400, "git_commit_failed", commit_proc.stderr.strip() or "git commit failed")
        rev_proc = self._run_repo_cmd(project_id, ["rev-parse", "HEAD"])
        commit_hash = rev_proc.stdout.strip() if rev_proc.returncode == 0 else ""
        return self._json_response(200, {"ok": True, "commit": commit_hash})

    # ----- Terminal -----
    def _terminal_shell_cmd(self, shell_name: str) -> List[str]:
        """Return terminal shell cmd."""
        mapping = {
            "bash": ["bash"],
            "pwsh": ["pwsh", "-NoLogo"],
            "cmd": ["cmd.exe"],
            "zsh": ["zsh"],
        }
        cmd = mapping.get(shell_name)
        if cmd is None:
            raise ApiError(400, "invalid_request", f"Unsupported shell: {shell_name}")
        return cmd

    def handle_terminal_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `terminal_create` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        project_root = self._ensure_project_path(project_id)
        body = ctx.json(required=True)
        shell_name = str(body.get("shell", "")).strip().lower()
        cwd = str(body.get("cwd", ".") or ".")
        env_patch = body.get("env")
        if not shell_name:
            raise ApiError(400, "invalid_request", "shell is required.")
        shell_cmd = self._terminal_shell_cmd(shell_name)
        cwd_path = project_root if cwd in {".", ""} else self._safe_project_file_path(project_id, cwd)
        env = os.environ.copy()
        if isinstance(env_patch, dict):
            env.update({str(k): str(v) for k, v in env_patch.items()})
        try:
            proc = subprocess.Popen(
                shell_cmd,
                cwd=str(cwd_path),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            raise ApiError(500, "terminal_create_failed", str(exc)) from exc
        terminal_id = self._new_id("term")
        with self._lock:
            self._terminal_processes[terminal_id] = proc
        return self._json_response(200, {"terminal_id": terminal_id})

    def handle_terminal_kill(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `terminal_kill` API endpoint."""
        terminal_id = str(ctx.path_params["terminal_id"])
        proc = self._terminal_processes.get(terminal_id)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._terminal_processes.pop(terminal_id, None)
        return self._json_response(200, {"ok": True})

    # ----- Deployments -----
    def _deployment_worker(self, deployment_id: str) -> None:
        """Process the worker."""
        step_names = ["prepare", "build", "deploy", "verify"]
        for idx, name in enumerate(step_names, start=1):
            with self._lock:
                deployment = self.deployments.get(deployment_id)
                if deployment is None:
                    return
                if deployment.get("status") == "canceled":
                    self.deployment_logs.setdefault(deployment_id, []).append({"ts": _utc_now_iso(), "level": "warn", "text": "Deployment canceled"})
                    return
                deployment["status"] = "running"
                deployment["progress"] = round((idx - 1) / len(step_names), 4)
                deployment["steps"].append({"id": self._new_id("dstep"), "name": name, "status": "running", "ts": _utc_now_iso()})
                self.deployment_logs.setdefault(deployment_id, []).append({"ts": _utc_now_iso(), "level": "info", "text": f"Step started: {name}"})
            self._persist_database_state()
            time.sleep(0.05)
            with self._lock:
                deployment = self.deployments.get(deployment_id)
                if deployment is None:
                    return
                if deployment["steps"]:
                    deployment["steps"][-1]["status"] = "done"
                deployment["progress"] = round(idx / len(step_names), 4)
            self._persist_database_state()
        with self._lock:
            deployment = self.deployments.get(deployment_id)
            if deployment is None:
                return
            if deployment.get("status") != "canceled":
                deployment["status"] = "succeeded"
                deployment["ended_at"] = _utc_now_iso()
                deployment["progress"] = 1.0
                self.deployment_logs.setdefault(deployment_id, []).append({"ts": _utc_now_iso(), "level": "info", "text": "Deployment succeeded"})
        self._persist_database_state()

    def handle_project_deployments_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_deployments_list` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        env_filter = (_query_first(ctx.query, "env", "") or "").strip().lower()
        status_filter = (_query_first(ctx.query, "status", "") or "").strip().lower()
        items: List[Dict[str, Any]] = []
        for dep_id in self.project_deployments.get(project_id, []):
            dep = self.deployments.get(dep_id)
            if not dep:
                continue
            if env_filter and env_filter != str(dep.get("env", "")).lower():
                continue
            if status_filter and status_filter != str(dep.get("status", "")).lower():
                continue
            items.append(dep)
        page, next_cursor = self._paginate_items(items, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_project_deployments_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_deployments_create` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        body = ctx.json(required=True)
        for key in ("env", "target", "strategy"):
            if key not in body:
                raise ApiError(400, "invalid_request", f"{key} is required.")
        deployment_id = self._new_id("dep")
        deployment = {
            "id": deployment_id,
            "project_id": project_id,
            "env": str(body["env"]),
            "target": str(body["target"]),
            "revision": str(body.get("revision", "HEAD")),
            "strategy": str(body["strategy"]),
            "status": "queued",
            "progress": 0.0,
            "started_at": _utc_now_iso(),
            "ended_at": None,
            "steps": [],
        }
        with self._lock:
            self.deployments[deployment_id] = deployment
            self.project_deployments.setdefault(project_id, []).append(deployment_id)
            self.deployment_logs[deployment_id] = [{"ts": _utc_now_iso(), "level": "info", "text": "Deployment queued"}]
            t = threading.Thread(target=self._deployment_worker, args=(deployment_id,), daemon=True)
            self._deployment_threads[deployment_id] = t
            t.start()
        return self._json_response(200, {"deployment_id": deployment_id})

    def handle_deployments_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `deployments_get` API endpoint."""
        deployment_id = str(ctx.path_params["deployment_id"])
        deployment = self.deployments.get(deployment_id)
        if deployment is None:
            raise ApiError(404, "deployment_not_found", f"Deployment not found: {deployment_id}")
        return self._json_response(200, {"deployment": deployment})

    def handle_deployments_logs(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `deployments_logs` API endpoint."""
        deployment_id = str(ctx.path_params["deployment_id"])
        _ = self.deployments.get(deployment_id)
        if deployment_id not in self.deployment_logs:
            raise ApiError(404, "deployment_not_found", f"Deployment not found: {deployment_id}")
        page, next_cursor = self._paginate_items(list(self.deployment_logs.get(deployment_id, [])), ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_deployments_cancel(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `deployments_cancel` API endpoint."""
        deployment_id = str(ctx.path_params["deployment_id"])
        deployment = self.deployments.get(deployment_id)
        if deployment is None:
            raise ApiError(404, "deployment_not_found", f"Deployment not found: {deployment_id}")
        deployment["status"] = "canceled"
        deployment["ended_at"] = _utc_now_iso()
        deployment["progress"] = 1.0
        self.deployment_logs.setdefault(deployment_id, []).append({"ts": _utc_now_iso(), "level": "warn", "text": "Deployment canceled by user"})
        return self._json_response(200, {"ok": True})

    # ----- Telemetry -----
    def _ensure_project_streams(self, project_id: str) -> List[Dict[str, Any]]:
        """Return the requested project streams or raise `ApiError` if missing."""
        streams = self.project_telemetry_streams.get(project_id)
        if streams is not None:
            return streams
        streams = [
            {"id": f"telem_{project_id}_cpu", "label": "CPU", "type": "system.cpu", "bands": ["pct"], "status": "online"},
            {"id": f"telem_{project_id}_ram", "label": "RAM", "type": "system.ram", "bands": ["used_bytes"], "status": "online"},
        ]
        self.project_telemetry_streams[project_id] = streams
        return streams

    def handle_telemetry_streams_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `telemetry_streams_list` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        streams = self._ensure_project_streams(project_id)
        page, next_cursor = self._paginate_items(list(streams), ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_telemetry_query(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `telemetry_query` API endpoint."""
        body = ctx.json(required=True)
        stream_id = str(body.get("stream_id", "")).strip()
        time_range = body.get("time_range")
        if not stream_id:
            raise ApiError(400, "invalid_request", "stream_id is required.")
        if not isinstance(time_range, dict):
            raise ApiError(400, "invalid_request", "time_range is required.")
        from_dt = _coerce_iso(str(time_range.get("from", "")))
        to_dt = _coerce_iso(str(time_range.get("to", "")))
        if from_dt is None or to_dt is None or to_dt <= from_dt:
            raise ApiError(400, "invalid_request", "time_range must contain valid from/to values.")
        limit = max(1, min(100000, _safe_int(body.get("limit", 5000), 5000)))
        span_seconds = max(1.0, (to_dt - from_dt).total_seconds())
        points_count = min(limit, 300)
        step = span_seconds / points_count
        series: List[Dict[str, Any]] = []
        for idx in range(points_count):
            ts = from_dt + dt.timedelta(seconds=idx * step)
            base = math.sin(idx / 10.0) * 10.0 + 50.0
            series.append({"ts": ts.astimezone(dt.timezone.utc).isoformat(), "value": round(base + random.uniform(-1.0, 1.0), 4)})
        anomalies: List[Dict[str, Any]] = []
        if points_count > 10 and random.random() < 0.3:
            mid = points_count // 2
            anomalies.append(
                {
                    "type": "spike_detect",
                    "confidence": 0.92,
                    "coords": [float(mid), float(series[mid]["value"])],
                    "ts": series[mid]["ts"],
                }
            )
        return self._json_response(200, {"series": series, "anomalies": anomalies})

    def handle_telemetry_alerts_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `telemetry_alerts_create` API endpoint."""
        body = ctx.json(required=True)
        for key in ("name", "stream_id", "condition", "actions"):
            if key not in body:
                raise ApiError(400, "invalid_request", f"{key} is required.")
        alert_id = self._new_id("alert")
        self.alerts[alert_id] = {"id": alert_id, "created_at": _utc_now_iso(), **body}
        self._create_notification("info", "Alert created", f"Telemetry alert created: {body.get('name', '')}")
        return self._json_response(200, {"alert_id": alert_id})

    # ----- Workflows -----
    def handle_project_workflows_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_workflows_list` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        workflows = [self.workflows[w_id] for w_id in self.project_workflows.get(project_id, []) if w_id in self.workflows]
        page, next_cursor = self._paginate_items(workflows, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_project_workflows_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_workflows_create` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        body = ctx.json(required=True)
        name = str(body.get("name", "")).strip()
        if not name:
            raise ApiError(400, "invalid_request", "name is required.")
        workflow_id = self._new_id("wf")
        now_ts = _utc_now_iso()
        workflow = {
            "id": workflow_id,
            "project_id": project_id,
            "name": name,
            "description": str(body.get("description", "")),
            "tags": list(body.get("tags", []) or []),
            "graph": {"nodes": [], "edges": []},
            "created_at": now_ts,
            "updated_at": now_ts,
        }
        self.workflows[workflow_id] = workflow
        self.project_workflows.setdefault(project_id, []).append(workflow_id)
        return self._json_response(200, {"workflow_id": workflow_id})

    def handle_workflows_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `workflows_get` API endpoint."""
        workflow_id = str(ctx.path_params["workflow_id"])
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            raise ApiError(404, "workflow_not_found", f"Workflow not found: {workflow_id}")
        return self._json_response(200, {"workflow": workflow})

    def handle_workflows_put(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `workflows_put` API endpoint."""
        workflow_id = str(ctx.path_params["workflow_id"])
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            raise ApiError(404, "workflow_not_found", f"Workflow not found: {workflow_id}")
        body = ctx.json(required=True)
        graph = body.get("graph")
        if not isinstance(graph, dict):
            raise ApiError(400, "invalid_request", "graph is required.")
        workflow["graph"] = graph
        workflow["updated_at"] = _utc_now_iso()
        return self._json_response(200, {"ok": True})

    def handle_workflows_run(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `workflows_run` API endpoint."""
        workflow_id = str(ctx.path_params["workflow_id"])
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            raise ApiError(404, "workflow_not_found", f"Workflow not found: {workflow_id}")
        body = ctx.json(required=True)
        if "inputs" not in body:
            raise ApiError(400, "invalid_request", "inputs is required.")
        run_id = self._new_id("run")
        run = {
            "id": run_id,
            "session_id": f"workflow:{workflow_id}",
            "status": "completed",
            "progress": 1.0,
            "started_at": _utc_now_iso(),
            "ended_at": _utc_now_iso(),
            "result": {"summary": f"Workflow '{workflow['name']}' executed.", "message_id": "", "diff_ids": []},
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            "_request": {"workflow_id": workflow_id, "inputs": body.get("inputs")},
        }
        self.runs[run_id] = run
        self.run_events[run_id] = [{"type": "status", "ts": _utc_now_iso(), "status": "completed", "progress": 1.0}]
        return self._json_response(200, {"run_id": run_id})

    # ----- Artifacts / uploads -----
    def handle_project_artifacts_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_artifacts_list` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        type_filter = (_query_first(ctx.query, "type", "") or "").strip().lower()
        items: List[Dict[str, Any]] = []
        for artifact_id in self.project_artifacts.get(project_id, []):
            artifact = self.artifacts.get(artifact_id)
            if not artifact:
                continue
            if type_filter and type_filter != str(artifact.get("type", "")).lower():
                continue
            items.append(artifact)
        page, next_cursor = self._paginate_items(items, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_project_artifacts_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `project_artifacts_create` API endpoint."""
        project_id = str(ctx.path_params["project_id"])
        _ = self._ensure_project(project_id)
        body = ctx.json(required=True)
        artifact_type = str(body.get("type", "")).strip()
        if not artifact_type:
            raise ApiError(400, "invalid_request", "type is required.")
        artifact_id = self._new_id("artifact")
        project_root = self._ensure_project_path(project_id)
        artifacts_dir = self.workspace_dir / "_artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        size_bytes = 0
        file_path = artifacts_dir / f"{artifact_id}.bin"
        paths = body.get("paths")
        if artifact_type == "zip":
            file_path = artifacts_dir / f"{artifact_id}.zip"
            with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if isinstance(paths, list) and paths:
                    for raw in paths:
                        rel = str(raw).strip()
                        if not rel:
                            continue
                        target = self._safe_project_file_path(project_id, rel)
                        if target.is_file():
                            zf.write(target, arcname=str(target.relative_to(project_root)))
                else:
                    for p in project_root.rglob("*"):
                        if p.is_file():
                            zf.write(p, arcname=str(p.relative_to(project_root)))
            size_bytes = file_path.stat().st_size if file_path.exists() else 0
        else:
            payload = json.dumps({"artifact_id": artifact_id, "project_id": project_id, "type": artifact_type, "label": body.get("label", "")}, ensure_ascii=False).encode("utf-8")
            file_path.write_bytes(payload)
            size_bytes = len(payload)
        artifact = {
            "id": artifact_id,
            "project_id": project_id,
            "type": artifact_type,
            "label": str(body.get("label", "")),
            "size_bytes": int(size_bytes),
            "download_url": f"{self.base_path}/artifacts/{artifact_id}",
            "created_at": _utc_now_iso(),
            "_file_path": str(file_path),
        }
        self.artifacts[artifact_id] = artifact
        self.project_artifacts.setdefault(project_id, []).append(artifact_id)
        return self._json_response(200, {"artifact_id": artifact_id, "download_url": artifact["download_url"]})

    def handle_artifacts_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `artifacts_get` API endpoint."""
        artifact_id = str(ctx.path_params["artifact_id"])
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise ApiError(404, "artifact_not_found", f"Artifact not found: {artifact_id}")
        payload = dict(artifact)
        payload.pop("_file_path", None)
        return self._json_response(200, {"artifact": payload})

    def handle_uploads_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `uploads_create` API endpoint."""
        body = ctx.json(required=True)
        for key in ("filename", "content_type", "size_bytes"):
            if key not in body:
                raise ApiError(400, "invalid_request", f"{key} is required.")
        upload_id = self._new_id("upload")
        file_id = self._new_id("file")
        upload = {
            "upload_id": upload_id,
            "file_id": file_id,
            "filename": str(body.get("filename")),
            "content_type": str(body.get("content_type")),
            "size_bytes": int(body.get("size_bytes", 0)),
            "created_at": _utc_now_iso(),
            "completed": False,
        }
        self.uploads[upload_id] = upload
        self.file_meta[file_id] = {
            "id": file_id,
            "filename": upload["filename"],
            "size_bytes": int(upload["size_bytes"]),
            "content_type": upload["content_type"],
            "created_at": upload["created_at"],
        }
        return self._json_response(
            200,
            {
                "upload_id": upload_id,
                "method": "PUT",
                "url": f"{self.base_path}/uploads/{upload_id}",
                "headers": {},
                "file_id": file_id,
            },
        )

    def handle_uploads_write(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `uploads_write` API endpoint."""
        upload_id = str(ctx.path_params["upload_id"])
        upload = self.uploads.get(upload_id)
        if upload is None:
            raise ApiError(404, "upload_not_found", f"Upload not found: {upload_id}")
        uploads_dir = self.workspace_dir / "_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", upload["filename"])
        file_path = uploads_dir / f"{upload['file_id']}_{safe_name}"
        file_path.write_bytes(ctx.body_bytes or b"")
        upload["completed"] = True
        upload["stored_path"] = str(file_path)
        meta = self.file_meta.get(upload["file_id"])
        if meta is not None:
            meta["size_bytes"] = len(ctx.body_bytes or b"")
        return self._json_response(200, {"ok": True})

    def handle_files_meta_get(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `files_meta_get` API endpoint."""
        file_id = str(ctx.path_params["file_id"])
        meta = self.file_meta.get(file_id)
        if meta is None:
            raise ApiError(404, "file_not_found", f"File not found: {file_id}")
        return self._json_response(200, {"file": meta})

    # ----- Notifications / audit / admin -----
    def handle_notifications_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `notifications_list` API endpoint."""
        items = list(self.notifications.values())
        items.sort(key=lambda x: str(x.get("ts", "")), reverse=True)
        page, next_cursor = self._paginate_items(items, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_notifications_ack(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `notifications_ack` API endpoint."""
        body = ctx.json(required=True)
        ids = body.get("ids")
        if not isinstance(ids, list):
            raise ApiError(400, "invalid_request", "ids must be an array.")
        for item in ids:
            notif = self.notifications.get(str(item))
            if notif is not None:
                notif["acked"] = True
        return self._json_response(200, {"ok": True})

    def handle_audit_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `audit_list` API endpoint."""
        project_id = (_query_first(ctx.query, "project_id", "") or "").strip()
        event_type = (_query_first(ctx.query, "type", "") or "").strip()
        events = list(self.audit_events)
        filtered: List[Dict[str, Any]] = []
        for event in events:
            if project_id and project_id != str(event.get("project_id", "")):
                continue
            if event_type and event_type != str(event.get("type", "")):
                continue
            filtered.append(event)
        page, next_cursor = self._paginate_items(filtered, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_admin_users_list(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `admin_users_list` API endpoint."""
        q = (_query_first(ctx.query, "q", "") or "").strip().lower()
        users = [self._sanitize_user(u) for u in self.users.values() if not u.get("disabled", False)]
        if q:
            users = [u for u in users if q in str(u.get("name", "")).lower() or q in str(u.get("email", "")).lower()]
        page, next_cursor = self._paginate_items(users, ctx.query)
        return self._json_response(200, {"items": page, "next_cursor": next_cursor})

    def handle_admin_users_create(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `admin_users_create` API endpoint."""
        body = ctx.json(required=True)
        for key in ("name", "email", "roles"):
            if key not in body:
                raise ApiError(400, "invalid_request", f"{key} is required.")
        user_id = self._new_id("user")
        user = {
            "id": user_id,
            "name": str(body["name"]),
            "email": str(body["email"]),
            "roles": list(body.get("roles") or []),
            "created_at": _utc_now_iso(),
            "disabled": False,
        }
        self.users[user_id] = user
        self.user_passwords[user_id] = str(body.get("password", ""))
        return self._json_response(200, {"user": self._sanitize_user(user)})

    def handle_admin_users_patch(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `admin_users_patch` API endpoint."""
        user_id = str(ctx.path_params["user_id"])
        user = self.users.get(user_id)
        if user is None:
            raise ApiError(404, "user_not_found", f"User not found: {user_id}")
        body = ctx.json(required=True)
        if "name" in body:
            user["name"] = str(body["name"])
        if "roles" in body and isinstance(body["roles"], list):
            user["roles"] = list(body["roles"])
        if "password" in body:
            self.user_passwords[user_id] = str(body["password"])
        if "disabled" in body:
            user["disabled"] = bool(body["disabled"])
        return self._json_response(200, {"ok": True})

    def handle_admin_users_delete(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `admin_users_delete` API endpoint."""
        user_id = str(ctx.path_params["user_id"])
        if user_id in self.users:
            self.users.pop(user_id, None)
            self.user_passwords.pop(user_id, None)
            return self._json_response(200, {"ok": True})
        raise ApiError(404, "user_not_found", f"User not found: {user_id}")

    # ----- Streaming -----
    def handle_stream_session(self, ctx: RequestContext) -> ApiResponse:
        """Handle the `stream_session` API endpoint."""
        session_id = str(ctx.path_params["session_id"])
        _ = self._ensure_session(session_id)
        run_id = (_query_first(ctx.query, "run_id", "") or "").strip()
        from_cursor = max(0, _safe_int(_query_first(ctx.query, "from_cursor", "0"), 0))
        events: List[Dict[str, Any]] = []
        if run_id:
            if run_id in self.run_events:
                events = list(self.run_events[run_id])
        else:
            for sid_run_id in self.session_runs.get(session_id, []):
                events.extend(self.run_events.get(sid_run_id, []))
        if from_cursor > 0:
            events = events[from_cursor:]
        chunks: List[str] = []
        # Keep idle SSE connections alive even when no events are available.
        if not events:
            chunks.append(": keep-alive\n\n")
        for idx, event in enumerate(events, start=from_cursor):
            envelope = {"type": str(event.get("type", "event")), "ts": str(event.get("ts", _utc_now_iso())), "data": event}
            chunks.append(f"id: {idx}\n")
            chunks.append(f"event: {envelope['type']}\n")
            chunks.append(f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n")
        payload = "".join(chunks).encode("utf-8")
        return ApiResponse(
            status_code=200,
            body=payload,
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


class _ApiRequestHandler(BaseHTTPRequestHandler):
    """Bridge HTTP requests into `DevApiState` dispatch calls."""
    server_version = "G4FAgentDevApi/1.0"
    protocol_version = "HTTP/1.1"

    def _read_body(self) -> bytes:
        """Read the full HTTP request body based on the Content-Length header."""
        length = _safe_int(self.headers.get("Content-Length", "0"), 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    @property
    def state(self) -> DevApiState:
        """Return the shared API state for this HTTP server instance."""
        return self.server.state  # type: ignore[attr-defined]

    def _handle(self, method: str) -> None:
        """Dispatch a specific HTTP method to the API state handler."""
        response = self.state.dispatch(
            method=method.upper(),
            raw_path=self.path,
            headers=self.headers,
            body_bytes=self._read_body(),
        )
        self._write_response(response)

    def _write_response(self, response: ApiResponse) -> None:
        """Serialize and write an `ApiResponse` to the client socket."""
        self.send_response(response.status_code)
        body_bytes: bytes
        if isinstance(response.body, (bytes, bytearray)):
            body_bytes = bytes(response.body)
        elif response.content_type == "application/json":
            body_bytes = json.dumps(response.body, ensure_ascii=False).encode("utf-8")
        else:
            body_bytes = str(response.body).encode("utf-8")
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        for key, value in response.headers.items():
            self.send_header(str(key), str(value))
        self.end_headers()
        if body_bytes:
            self.wfile.write(body_bytes)

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle HTTP OPTIONS requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        """Handle HTTP GET requests."""
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        """Handle HTTP POST requests."""
        self._handle("POST")

    def do_PUT(self) -> None:  # noqa: N802
        """Handle HTTP PUT requests."""
        self._handle("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        """Handle HTTP PATCH requests."""
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        """Handle HTTP DELETE requests."""
        self._handle("DELETE")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP server log output."""
        _ = format
        _ = args
        return


class DevApiHttpServer(ThreadingHTTPServer):
    """Threaded HTTP server that exposes a shared `DevApiState` instance."""
    def __init__(self, server_address: Tuple[str, int], state: DevApiState):
        """Initialize a `DevApiHttpServer` instance."""
        self.state = state
        super().__init__(server_address, _ApiRequestHandler)


def create_api_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    base_path: str = "/api/v1",
    workspace_dir: Optional[Path] = None,
    config_rel_path: str = DEFAULT_CONFIG_REL_PATH,
    config_base_dir: Path = APP_ROOT,
    tools_dirs: Optional[Iterable[str]] = None,
    auth_disabled: bool = False,
    api_key: str = "dev-api-key",
    database: Optional[Union[str, Database]] = None,
) -> DevApiHttpServer:
    """Create and configure a development API HTTP server instance."""
    resolved_workspace_dir = (workspace_dir or (Path.cwd() / ".g4fagent_api")).resolve()
    resolved_workspace_dir.mkdir(parents=True, exist_ok=True)
    resolved_database = create_database(database, base_dir=resolved_workspace_dir)
    manager = G4FManager.from_config(
        config_rel_path=config_rel_path,
        base_dir=config_base_dir,
        database=resolved_database,
        database_base_dir=resolved_workspace_dir,
    )
    state = DevApiState(
        base_path=base_path,
        workspace_dir=resolved_workspace_dir,
        manager=manager,
        tools_dirs=tools_dirs,
        auth_disabled=auth_disabled,
        api_key=api_key,
        database=resolved_database,
    )
    return DevApiHttpServer((host, int(port)), state)


def run_api_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    base_path: str = "/api/v1",
    workspace_dir: Optional[Path] = None,
    config_rel_path: str = DEFAULT_CONFIG_REL_PATH,
    config_base_dir: Path = APP_ROOT,
    tools_dirs: Optional[Iterable[str]] = None,
    auth_disabled: bool = False,
    api_key: str = "dev-api-key",
    database: Optional[Union[str, Database]] = None,
) -> int:
    """Run the development API server until interrupted."""
    server = create_api_server(
        host=host,
        port=port,
        base_path=base_path,
        workspace_dir=workspace_dir,
        config_rel_path=config_rel_path,
        config_base_dir=config_base_dir,
        tools_dirs=tools_dirs,
        auth_disabled=auth_disabled,
        api_key=api_key,
        database=database,
    )
    bound_host, bound_port = server.server_address[:2]
    print(f"G4FAgent API server listening on http://{bound_host}:{bound_port}{server.state.base_path}")
    print(f"Workspace: {server.state.workspace_dir}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0

