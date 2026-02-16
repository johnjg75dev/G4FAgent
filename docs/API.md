# G4FAgent Dev API Reference

This document reflects all routes currently registered in `g4fagent/api_server.py` (`DevApiState._register_routes`).

## Base URL

- Default base path: `/api/v1` (configurable at server startup).
- Example full URL: `http://127.0.0.1:8000/api/v1/projects`.

## Authentication

- All endpoints require `Authorization: Bearer <access_token>` unless explicitly listed as public below.
- Public endpoints:
  - `GET /`
  - `GET /health`
  - `GET /capabilities`
  - `GET /server/stats`
  - `POST /auth/login`
  - `POST /auth/refresh`
- If `auth_disabled=true`, the server skips token checks and injects the default admin user.

## Request/Response Conventions

- JSON endpoints expect a JSON object body when body is required.
- If body is required and missing/empty, server returns `400 missing_body`.
- Invalid JSON returns `400 invalid_json`.
- Many list endpoints support pagination query params:
  - `limit` (int, defaults to 50, capped per endpoint)
  - `cursor` (int offset, defaults to `0`)
- Paginated responses use:
  - `items`: array
  - `next_cursor`: string or `null`

## Error Shape

All non-2xx responses use:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "request_id": "req_...",
    "retryable": false,
    "details": {}
  }
}
```

`details` is optional.

## Endpoint Reference

### Core (Public)

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/` | none | `ok` (bool), `name`, `version`, `base_path`, `endpoints[]` (`method`, `path`) |
| GET | `/health` | none | `ok` (bool), `version`, `build`, `uptime_s` (int), `time` (ISO-8601) |
| GET | `/capabilities` | none | `features` object, `limits` object |
| GET | `/server/stats` | query: `window_s?` (int 1..3600, default `60`) | `cpu.pct`, `ram.used_bytes`, `ram.total_bytes`, `gpu.pct`, `gpu.vram_used_bytes`, `gpu.vram_total_bytes`, `network.rx_bps`, `network.tx_bps`, `requests.rps`, `requests.p95_ms` |

### Auth / Identity

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| POST | `/auth/login` | body required: `method` (`password` or `api_key`); if `password`: `email`, `password`; if `api_key`: `api_key` | `access_token`, `refresh_token`, `expires_in` |
| POST | `/auth/refresh` | body required: `refresh_token` | `access_token`, `refresh_token`, `expires_in` |
| POST | `/auth/logout` | body required (can be empty object); optional `refresh_token` | `ok` (bool) |
| GET | `/me` | none | `user` (`id`, `name`, `email`, `roles[]`, `created_at`) |

### Providers

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/providers` | query: `limit?`, `cursor?` | `items[]` provider objects (`id`, `label`, `type`, `status`, `base_url`, `supports`, `last_checked_at`), `next_cursor` |
| POST | `/providers/scan` | body optional: `include?` (array of provider IDs) | `ok` (bool), `discovered[]` (provider IDs), `warnings[]` |
| GET | `/providers/{provider_id}/models` | path: `provider_id`; query: `q?`, `capability?`, `limit?`, `cursor?` | `items[]` model objects (`id`, `label`, `context_tokens`, `capabilities[]`, `pricing`), `next_cursor` |
| POST | `/providers/{provider_id}/test` | path: `provider_id`; body optional | `ok` (bool), `latency_ms` (int), `details` |

### Settings

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/settings` | none | `settings` object |
| PUT | `/settings` | body required: partial settings object (deep-merged into current settings) | `ok` (bool) |
| GET | `/settings/audit` | query: `limit?`, `cursor?` | `items[]` (`id`, `ts`, `actor_user_id`, `change.path`, `change.from`, `change.to`), `next_cursor` |

### Projects

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects` | query: `q?`, `status?`, `environment?`, `limit?`, `cursor?` | `items[]` project objects, `next_cursor` |
| POST | `/projects` | body required: `name`; optional `description`, `status`, `environment`, `repo` | `project` (`id`, `name`, `description`, `status`, `environment`, `last_commit`, `repo`, `stats`, `created_at`, `updated_at`) |
| GET | `/projects/{project_id}` | path: `project_id` | `project` |
| PATCH | `/projects/{project_id}` | path: `project_id`; body required: any of `name`, `description`, `environment`, `status`, `repo` | `ok` (bool) |
| DELETE | `/projects/{project_id}` | path: `project_id` | `ok` (bool) |

### Sessions / Messages / Runs

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/sessions` | path: `project_id`; query: `q?`, `status?`, `limit?`, `cursor?` | `items[]` session objects, `next_cursor` |
| POST | `/projects/{project_id}/sessions` | path: `project_id`; body required: `title`; optional `provider_id`, `model_id`, `status`, `config`, `memory`, `tags[]` | `session` (`id`, `project_id`, `title`, `status`, `provider_id`, `model_id`, `config`, `memory`, `tags`, `created_at`, `updated_at`) |
| GET | `/sessions/{session_id}` | path: `session_id` | `session` |
| PATCH | `/sessions/{session_id}` | path: `session_id`; body required: any of `title`, `status`, `provider_id`, `model_id`, `config`, `memory`, `tags` | `ok` (bool) |
| GET | `/sessions/{session_id}/messages` | path: `session_id`; query: `after_ts?` (ISO), `before_ts?` (ISO), `limit?`, `cursor?` | `items[]` message objects (`id`, `session_id`, `role`, `content[]`, `meta`, `ts`), `next_cursor` |
| POST | `/sessions/{session_id}/messages` | path: `session_id`; body required: `role`, `content[]`; optional `meta` | `message_id` |
| POST | `/sessions/{session_id}/runs` | path: `session_id`; body required: `mode`, `agent` (object), `input` (object) | `run_id` |
| GET | `/runs/{run_id}` | path: `run_id` | `run` (`id`, `session_id`, `status`, `progress`, `started_at`, `ended_at`, `result`, `usage`) |
| POST | `/runs/{run_id}/cancel` | path: `run_id` | `ok` (bool) |
| GET | `/runs/{run_id}/events` | path: `run_id`; query: `limit?`, `cursor?` | `items[]` run event objects, `next_cursor` |

### Tools

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/tools` | query: `scope?`, `q?`, `limit?`, `cursor?` | `items[]` (`id`, `name`, `scope`, `description`, `schema`, `created_at`), `next_cursor` |
| POST | `/tools` | body required: `name`, `scope`, `description`, `schema`, `handler` | `tool_id` |
| DELETE | `/tools/{tool_id}` | path: `tool_id` | `ok` (bool) |
| POST | `/tools/{tool_id}/invoke` | path: `tool_id`; body required: `args` (object); optional `context.project_id` | `ok` (bool), `result` (tool-defined object/value) |

### Files

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/files/tree` | path: `project_id`; query: `root?` (default `/`), `depth?` (1..20, default `4`), `include_hidden?` (bool) | `root`, `items[]` (`path`, `type`, `mtime`, `size_bytes`) |
| GET | `/projects/{project_id}/files/content` | path: `project_id`; query required: `path` | `path`, `encoding` (`utf-8`), `text`, `etag` |
| PUT | `/projects/{project_id}/files/content` | path: `project_id`; body required: `path`, `text`; optional `etag` (optimistic concurrency) | `ok` (bool), `etag` |
| POST | `/projects/{project_id}/files/batch` | path: `project_id`; body optional: `reads[]` (`path`), `writes[]` (`path`, `text`, `etag?`) | `reads[]` (`path`, `ok`, `text?`, `etag?`, `error?`), `writes[]` (`path`, `ok`, `etag?`, `error?`) |
| POST | `/projects/{project_id}/lint` | path: `project_id`; body required: `paths[]` | `diagnostics[]` (`path`, `line`, `col`, `severity`, `code`, `message`) |
| POST | `/projects/{project_id}/format` | path: `project_id`; body required (shape not enforced) | `ok` (bool) |
| POST | `/projects/{project_id}/search` | path: `project_id`; body required: `q`; optional `paths[]`, `case_sensitive?`, `regex?` | `matches[]` (`path`, `line`, `preview`) |

### Diffs

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/diffs` | path: `project_id`; query: `status?`, `limit?`, `cursor?` | `items[]` diff objects, `next_cursor` |
| POST | `/projects/{project_id}/diffs` | path: `project_id`; body required: `title`, `patch`; optional `base_rev` | `diff_id` |
| GET | `/diffs/{diff_id}` | path: `diff_id` | `diff` (`id`, `project_id`, `title`, `status`, `stats`, `files`, `base_rev`, `created_at`) |
| POST | `/diffs/{diff_id}/apply` | path: `diff_id`; body optional: `commit_message` | `ok` (bool), `commit` (hash string or empty string) |
| POST | `/diffs/{diff_id}/discard` | path: `diff_id` | `ok` (bool) |
| POST | `/diffs/{diff_id}/comment` | path: `diff_id`; body required: `path`, `line`, `comment` | `ok` (bool) |

### Repo

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/repo/status` | path: `project_id` | `branch`, `dirty` (bool), `ahead` (int), `behind` (int), `changes[]` (`path`, `status`) |
| POST | `/projects/{project_id}/repo/checkout` | path: `project_id`; body required: `branch` | `ok` (bool) |
| POST | `/projects/{project_id}/repo/pull` | path: `project_id` | `ok` (bool) |
| POST | `/projects/{project_id}/repo/commit` | path: `project_id`; body required: `message`; optional `paths[]` | `ok` (bool), `commit` (hash) |

### Terminal

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| POST | `/projects/{project_id}/terminal/sessions` | path: `project_id`; body required: `shell` (`bash`, `pwsh`, `cmd`, `zsh`); optional `cwd` (default `.`), `env` (object) | `terminal_id` |
| POST | `/projects/{project_id}/terminal/{terminal_id}/kill` | path: `project_id`, `terminal_id` | `ok` (bool) |

### Deployments

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/deployments` | path: `project_id`; query: `env?`, `status?`, `limit?`, `cursor?` | `items[]` deployment objects, `next_cursor` |
| POST | `/projects/{project_id}/deployments` | path: `project_id`; body required: `env`, `target`, `strategy`; optional `revision` (default `HEAD`) | `deployment_id` |
| GET | `/deployments/{deployment_id}` | path: `deployment_id` | `deployment` (`id`, `project_id`, `env`, `target`, `revision`, `strategy`, `status`, `progress`, `started_at`, `ended_at`, `steps[]`) |
| GET | `/deployments/{deployment_id}/logs` | path: `deployment_id`; query: `limit?`, `cursor?` | `items[]` (`ts`, `level`, `text`), `next_cursor` |
| POST | `/deployments/{deployment_id}/cancel` | path: `deployment_id` | `ok` (bool) |

### Telemetry

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/telemetry/streams` | path: `project_id`; query: `limit?`, `cursor?` | `items[]` stream objects (`id`, `label`, `type`, `bands[]`, `status`), `next_cursor` |
| POST | `/telemetry/query` | body required: `stream_id`, `time_range` (`from`, `to` ISO timestamps); optional `limit` | `series[]` (`ts`, `value`), `anomalies[]` |
| POST | `/telemetry/alerts` | body required: `name`, `stream_id`, `condition`, `actions` | `alert_id` |

### Workflows

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/workflows` | path: `project_id`; query: `limit?`, `cursor?` | `items[]` workflow objects, `next_cursor` |
| POST | `/projects/{project_id}/workflows` | path: `project_id`; body required: `name`; optional `description`, `tags[]` | `workflow_id` |
| GET | `/workflows/{workflow_id}` | path: `workflow_id` | `workflow` (`id`, `project_id`, `name`, `description`, `tags`, `graph`, `created_at`, `updated_at`) |
| PUT | `/workflows/{workflow_id}` | path: `workflow_id`; body required: `graph` (object) | `ok` (bool) |
| POST | `/workflows/{workflow_id}/runs` | path: `workflow_id`; body required: `inputs` | `run_id` |

### Artifacts / Uploads

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/projects/{project_id}/artifacts` | path: `project_id`; query: `type?`, `limit?`, `cursor?` | `items[]` artifact objects, `next_cursor` |
| POST | `/projects/{project_id}/artifacts` | path: `project_id`; body required: `type`; optional `label`, `paths[]` (used for `type=zip`) | `artifact_id`, `download_url` |
| GET | `/artifacts/{artifact_id}` | path: `artifact_id` | `artifact` (`id`, `project_id`, `type`, `label`, `size_bytes`, `download_url`, `created_at`) |
| POST | `/uploads` | body required: `filename`, `content_type`, `size_bytes` | `upload_id`, `method`, `url`, `headers`, `file_id` |
| PUT | `/uploads/{upload_id}` | path: `upload_id`; raw request body bytes (file data) | `ok` (bool) |
| POST | `/uploads/{upload_id}` | path: `upload_id`; raw request body bytes (file data) | `ok` (bool) |
| GET | `/files/{file_id}` | path: `file_id` | `file` (`id`, `filename`, `size_bytes`, `content_type`, `created_at`) |

### Notifications / Audit / Admin

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/notifications` | query: `limit?`, `cursor?` | `items[]` (`id`, `ts`, `level`, `title`, `body`, `acked`), `next_cursor` |
| POST | `/notifications/ack` | body required: `ids[]` | `ok` (bool) |
| GET | `/audit` | query: `project_id?`, `type?`, `limit?`, `cursor?` | `items[]` audit event objects (`id`, `ts`, `actor_user_id`, `project_id`, `type`, `data`), `next_cursor` |
| GET | `/admin/users` | query: `q?`, `limit?`, `cursor?` | `items[]` users (`id`, `name`, `email`, `roles[]`, `created_at`), `next_cursor` |
| POST | `/admin/users` | body required: `name`, `email`, `roles`; optional `password` | `user` (`id`, `name`, `email`, `roles[]`, `created_at`) |
| PATCH | `/admin/users/{user_id}` | path: `user_id`; body required with one or more of `name`, `roles[]`, `password`, `disabled` | `ok` (bool) |
| DELETE | `/admin/users/{user_id}` | path: `user_id` | `ok` (bool) |

### Streaming

| Method | Path | Expected Input Params | Output Params |
|---|---|---|---|
| GET | `/stream/sessions/{session_id}` | path: `session_id`; query: `run_id?`, `from_cursor?` (int, default `0`) | `text/event-stream` response. SSE events contain `id`, `event`, and `data` JSON envelope: `{ "type": "...", "ts": "...", "data": { ...event... } }`. If no events, emits `: keep-alive`. |
