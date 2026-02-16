# OpenAPI.md (OpenAPI 3.1)

This file contains an OpenAPI-compatible spec for the current API surface.

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "G4FAgent Dev Platform API",
    "version": "1.0.0",
    "description": "OpenAPI spec generated from docs/API.md and g4fagent/api_server.py route definitions."
  },
  "servers": [
    {
      "url": "http://127.0.0.1:8000/api/v1",
      "description": "Default local dev server"
    }
  ],
  "security": [
    {
      "bearerAuth": []
    }
  ],
  "components": {
    "securitySchemes": {
      "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    },
    "schemas": {
      "GenericObject": {
        "type": "object",
        "additionalProperties": true
      },
      "Error": {
        "type": "object",
        "properties": {
          "error": {
            "type": "object",
            "properties": {
              "code": {
                "type": "string"
              },
              "message": {
                "type": "string"
              },
              "request_id": {
                "type": "string"
              },
              "retryable": {
                "type": "boolean"
              },
              "details": {
                "type": "object",
                "additionalProperties": true
              }
            },
            "required": [
              "code",
              "message",
              "request_id",
              "retryable"
            ],
            "additionalProperties": true
          }
        },
        "required": [
          "error"
        ],
        "additionalProperties": false
      }
    }
  },
  "paths": {
    "/": {
      "get": {
        "operationId": "get_root",
        "tags": [
          "Core (Public)"
        ],
        "summary": "Core (Public): GET /",
        "description": "Expected input params: none\n\nExpected output params: `ok` (bool), `name`, `version`, `base_path`, `endpoints[]` (`method`, `path`)",
        "responses": {
          "200": {
            "description": "`ok` (bool), `name`, `version`, `base_path`, `endpoints[]` (`method`, `path`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "security": []
      }
    },
    "/health": {
      "get": {
        "operationId": "get_health",
        "tags": [
          "Core (Public)"
        ],
        "summary": "Core (Public): GET /health",
        "description": "Expected input params: none\n\nExpected output params: `ok` (bool), `version`, `build`, `uptime_s` (int), `time` (ISO-8601)",
        "responses": {
          "200": {
            "description": "`ok` (bool), `version`, `build`, `uptime_s` (int), `time` (ISO-8601)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "security": []
      }
    },
    "/capabilities": {
      "get": {
        "operationId": "get_capabilities",
        "tags": [
          "Core (Public)"
        ],
        "summary": "Core (Public): GET /capabilities",
        "description": "Expected input params: none\n\nExpected output params: `features` object, `limits` object",
        "responses": {
          "200": {
            "description": "`features` object, `limits` object",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "security": []
      }
    },
    "/server/stats": {
      "get": {
        "operationId": "get_server_stats",
        "tags": [
          "Core (Public)"
        ],
        "summary": "Core (Public): GET /server/stats",
        "description": "Expected input params: query: `window_s?` (int 1..3600, default `60`)\n\nExpected output params: `cpu.pct`, `ram.used_bytes`, `ram.total_bytes`, `gpu.pct`, `gpu.vram_used_bytes`, `gpu.vram_total_bytes`, `network.rx_bps`, `network.tx_bps`, `requests.rps`, `requests.p95_ms`",
        "responses": {
          "200": {
            "description": "`cpu.pct`, `ram.used_bytes`, `ram.total_bytes`, `gpu.pct`, `gpu.vram_used_bytes`, `gpu.vram_total_bytes`, `network.rx_bps`, `network.tx_bps`, `requests.rps`, `requests.p95_ms`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "window_s",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Stats time window in seconds."
          },
          {
            "name": "default",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Query parameter `default`."
          }
        ],
        "security": []
      }
    },
    "/auth/login": {
      "post": {
        "operationId": "post_auth_login",
        "tags": [
          "Auth / Identity"
        ],
        "summary": "Auth / Identity: POST /auth/login",
        "description": "Expected input params: body required: `method` (`password` or `api_key`); if `password`: `email`, `password`; if `api_key`: `api_key`\n\nExpected output params: `access_token`, `refresh_token`, `expires_in`",
        "responses": {
          "200": {
            "description": "`access_token`, `refresh_token`, `expires_in`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `method` (`password` or `api_key`); if `password`: `email`, `password`; if `api_key`: `api_key`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        },
        "security": []
      }
    },
    "/auth/refresh": {
      "post": {
        "operationId": "post_auth_refresh",
        "tags": [
          "Auth / Identity"
        ],
        "summary": "Auth / Identity: POST /auth/refresh",
        "description": "Expected input params: body required: `refresh_token`\n\nExpected output params: `access_token`, `refresh_token`, `expires_in`",
        "responses": {
          "200": {
            "description": "`access_token`, `refresh_token`, `expires_in`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `refresh_token`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        },
        "security": []
      }
    },
    "/auth/logout": {
      "post": {
        "operationId": "post_auth_logout",
        "tags": [
          "Auth / Identity"
        ],
        "summary": "Auth / Identity: POST /auth/logout",
        "description": "Expected input params: body required (can be empty object); optional `refresh_token`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required (can be empty object); optional `refresh_token`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/me": {
      "get": {
        "operationId": "get_me",
        "tags": [
          "Auth / Identity"
        ],
        "summary": "Auth / Identity: GET /me",
        "description": "Expected input params: none\n\nExpected output params: `user` (`id`, `name`, `email`, `roles[]`, `created_at`)",
        "responses": {
          "200": {
            "description": "`user` (`id`, `name`, `email`, `roles[]`, `created_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        }
      }
    },
    "/providers": {
      "get": {
        "operationId": "get_providers",
        "tags": [
          "Providers"
        ],
        "summary": "Providers: GET /providers",
        "description": "Expected input params: query: `limit?`, `cursor?`\n\nExpected output params: `items[]` provider objects (`id`, `label`, `type`, `status`, `base_url`, `supports`, `last_checked_at`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` provider objects (`id`, `label`, `type`, `status`, `base_url`, `supports`, `last_checked_at`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/providers/scan": {
      "post": {
        "operationId": "post_providers_scan",
        "tags": [
          "Providers"
        ],
        "summary": "Providers: POST /providers/scan",
        "description": "Expected input params: body optional: `include?` (array of provider IDs)\n\nExpected output params: `ok` (bool), `discovered[]` (provider IDs), `warnings[]`",
        "responses": {
          "200": {
            "description": "`ok` (bool), `discovered[]` (provider IDs), `warnings[]`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": false,
          "description": "body optional: `include?` (array of provider IDs)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/providers/{provider_id}/models": {
      "get": {
        "operationId": "get_providers_provider_id_models",
        "tags": [
          "Providers"
        ],
        "summary": "Providers: GET /providers/{provider_id}/models",
        "description": "Expected input params: path: `provider_id`; query: `q?`, `capability?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` model objects (`id`, `label`, `context_tokens`, `capabilities[]`, `pricing`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` model objects (`id`, `label`, `context_tokens`, `capabilities[]`, `pricing`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "provider_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `provider_id`."
          },
          {
            "name": "q",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Search query."
          },
          {
            "name": "capability",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Capability filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/providers/{provider_id}/test": {
      "post": {
        "operationId": "post_providers_provider_id_test",
        "tags": [
          "Providers"
        ],
        "summary": "Providers: POST /providers/{provider_id}/test",
        "description": "Expected input params: path: `provider_id`; body optional\n\nExpected output params: `ok` (bool), `latency_ms` (int), `details`",
        "responses": {
          "200": {
            "description": "`ok` (bool), `latency_ms` (int), `details`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "provider_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `provider_id`."
          }
        ],
        "requestBody": {
          "required": false,
          "description": "path: `provider_id`; body optional",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/settings": {
      "get": {
        "operationId": "get_settings",
        "tags": [
          "Settings"
        ],
        "summary": "Settings: GET /settings",
        "description": "Expected input params: none\n\nExpected output params: `settings` object",
        "responses": {
          "200": {
            "description": "`settings` object",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        }
      },
      "put": {
        "operationId": "put_settings",
        "tags": [
          "Settings"
        ],
        "summary": "Settings: PUT /settings",
        "description": "Expected input params: body required: partial settings object (deep-merged into current settings)\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: partial settings object (deep-merged into current settings)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/settings/audit": {
      "get": {
        "operationId": "get_settings_audit",
        "tags": [
          "Settings"
        ],
        "summary": "Settings: GET /settings/audit",
        "description": "Expected input params: query: `limit?`, `cursor?`\n\nExpected output params: `items[]` (`id`, `ts`, `actor_user_id`, `change.path`, `change.from`, `change.to`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` (`id`, `ts`, `actor_user_id`, `change.path`, `change.from`, `change.to`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/projects": {
      "get": {
        "operationId": "get_projects",
        "tags": [
          "Projects"
        ],
        "summary": "Projects: GET /projects",
        "description": "Expected input params: query: `q?`, `status?`, `environment?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` project objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` project objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "q",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Search query."
          },
          {
            "name": "status",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Status filter."
          },
          {
            "name": "environment",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Environment filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_projects",
        "tags": [
          "Projects"
        ],
        "summary": "Projects: POST /projects",
        "description": "Expected input params: body required: `name`; optional `description`, `status`, `environment`, `repo`\n\nExpected output params: `project` (`id`, `name`, `description`, `status`, `environment`, `last_commit`, `repo`, `stats`, `created_at`, `updated_at`)",
        "responses": {
          "200": {
            "description": "`project` (`id`, `name`, `description`, `status`, `environment`, `last_commit`, `repo`, `stats`, `created_at`, `updated_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `name`; optional `description`, `status`, `environment`, `repo`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}": {
      "get": {
        "operationId": "get_projects_project_id",
        "tags": [
          "Projects"
        ],
        "summary": "Projects: GET /projects/{project_id}",
        "description": "Expected input params: path: `project_id`\n\nExpected output params: `project`",
        "responses": {
          "200": {
            "description": "`project`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ]
      },
      "patch": {
        "operationId": "patch_projects_project_id",
        "tags": [
          "Projects"
        ],
        "summary": "Projects: PATCH /projects/{project_id}",
        "description": "Expected input params: path: `project_id`; body required: any of `name`, `description`, `environment`, `status`, `repo`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: any of `name`, `description`, `environment`, `status`, `repo`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      },
      "delete": {
        "operationId": "delete_projects_project_id",
        "tags": [
          "Projects"
        ],
        "summary": "Projects: DELETE /projects/{project_id}",
        "description": "Expected input params: path: `project_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ]
      }
    },
    "/projects/{project_id}/sessions": {
      "get": {
        "operationId": "get_projects_project_id_sessions",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: GET /projects/{project_id}/sessions",
        "description": "Expected input params: path: `project_id`; query: `q?`, `status?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` session objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` session objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "q",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Search query."
          },
          {
            "name": "status",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Status filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_projects_project_id_sessions",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: POST /projects/{project_id}/sessions",
        "description": "Expected input params: path: `project_id`; body required: `title`; optional `provider_id`, `model_id`, `status`, `config`, `memory`, `tags[]`\n\nExpected output params: `session` (`id`, `project_id`, `title`, `status`, `provider_id`, `model_id`, `config`, `memory`, `tags`, `created_at`, `updated_at`)",
        "responses": {
          "200": {
            "description": "`session` (`id`, `project_id`, `title`, `status`, `provider_id`, `model_id`, `config`, `memory`, `tags`, `created_at`, `updated_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `title`; optional `provider_id`, `model_id`, `status`, `config`, `memory`, `tags[]`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/sessions/{session_id}": {
      "get": {
        "operationId": "get_sessions_session_id",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: GET /sessions/{session_id}",
        "description": "Expected input params: path: `session_id`\n\nExpected output params: `session`",
        "responses": {
          "200": {
            "description": "`session`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `session_id`."
          }
        ]
      },
      "patch": {
        "operationId": "patch_sessions_session_id",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: PATCH /sessions/{session_id}",
        "description": "Expected input params: path: `session_id`; body required: any of `title`, `status`, `provider_id`, `model_id`, `config`, `memory`, `tags`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `session_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `session_id`; body required: any of `title`, `status`, `provider_id`, `model_id`, `config`, `memory`, `tags`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/sessions/{session_id}/messages": {
      "get": {
        "operationId": "get_sessions_session_id_messages",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: GET /sessions/{session_id}/messages",
        "description": "Expected input params: path: `session_id`; query: `after_ts?` (ISO), `before_ts?` (ISO), `limit?`, `cursor?`\n\nExpected output params: `items[]` message objects (`id`, `session_id`, `role`, `content[]`, `meta`, `ts`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` message objects (`id`, `session_id`, `role`, `content[]`, `meta`, `ts`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `session_id`."
          },
          {
            "name": "after_ts",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Filter items after this ISO timestamp."
          },
          {
            "name": "before_ts",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Filter items before this ISO timestamp."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_sessions_session_id_messages",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: POST /sessions/{session_id}/messages",
        "description": "Expected input params: path: `session_id`; body required: `role`, `content[]`; optional `meta`\n\nExpected output params: `message_id`",
        "responses": {
          "200": {
            "description": "`message_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `session_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `session_id`; body required: `role`, `content[]`; optional `meta`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/sessions/{session_id}/runs": {
      "post": {
        "operationId": "post_sessions_session_id_runs",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: POST /sessions/{session_id}/runs",
        "description": "Expected input params: path: `session_id`; body required: `mode`, `agent` (object), `input` (object)\n\nExpected output params: `run_id`",
        "responses": {
          "200": {
            "description": "`run_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `session_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `session_id`; body required: `mode`, `agent` (object), `input` (object)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/runs/{run_id}": {
      "get": {
        "operationId": "get_runs_run_id",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: GET /runs/{run_id}",
        "description": "Expected input params: path: `run_id`\n\nExpected output params: `run` (`id`, `session_id`, `status`, `progress`, `started_at`, `ended_at`, `result`, `usage`)",
        "responses": {
          "200": {
            "description": "`run` (`id`, `session_id`, `status`, `progress`, `started_at`, `ended_at`, `result`, `usage`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "run_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `run_id`."
          }
        ]
      }
    },
    "/runs/{run_id}/cancel": {
      "post": {
        "operationId": "post_runs_run_id_cancel",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: POST /runs/{run_id}/cancel",
        "description": "Expected input params: path: `run_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "run_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `run_id`."
          }
        ]
      }
    },
    "/runs/{run_id}/events": {
      "get": {
        "operationId": "get_runs_run_id_events",
        "tags": [
          "Sessions / Messages / Runs"
        ],
        "summary": "Sessions / Messages / Runs: GET /runs/{run_id}/events",
        "description": "Expected input params: path: `run_id`; query: `limit?`, `cursor?`\n\nExpected output params: `items[]` run event objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` run event objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "run_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `run_id`."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/tools": {
      "get": {
        "operationId": "get_tools",
        "tags": [
          "Tools"
        ],
        "summary": "Tools: GET /tools",
        "description": "Expected input params: query: `scope?`, `q?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` (`id`, `name`, `scope`, `description`, `schema`, `created_at`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` (`id`, `name`, `scope`, `description`, `schema`, `created_at`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "scope",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Tool scope filter."
          },
          {
            "name": "q",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Search query."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_tools",
        "tags": [
          "Tools"
        ],
        "summary": "Tools: POST /tools",
        "description": "Expected input params: body required: `name`, `scope`, `description`, `schema`, `handler`\n\nExpected output params: `tool_id`",
        "responses": {
          "200": {
            "description": "`tool_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `name`, `scope`, `description`, `schema`, `handler`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/tools/{tool_id}": {
      "delete": {
        "operationId": "delete_tools_tool_id",
        "tags": [
          "Tools"
        ],
        "summary": "Tools: DELETE /tools/{tool_id}",
        "description": "Expected input params: path: `tool_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "tool_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `tool_id`."
          }
        ]
      }
    },
    "/tools/{tool_id}/invoke": {
      "post": {
        "operationId": "post_tools_tool_id_invoke",
        "tags": [
          "Tools"
        ],
        "summary": "Tools: POST /tools/{tool_id}/invoke",
        "description": "Expected input params: path: `tool_id`; body required: `args` (object); optional `context.project_id`\n\nExpected output params: `ok` (bool), `result` (tool-defined object/value)",
        "responses": {
          "200": {
            "description": "`ok` (bool), `result` (tool-defined object/value)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "tool_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `tool_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `tool_id`; body required: `args` (object); optional `context.project_id`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/files/tree": {
      "get": {
        "operationId": "get_projects_project_id_files_tree",
        "tags": [
          "Files"
        ],
        "summary": "Files: GET /projects/{project_id}/files/tree",
        "description": "Expected input params: path: `project_id`; query: `root?` (default `/`), `depth?` (1..20, default `4`), `include_hidden?` (bool)\n\nExpected output params: `root`, `items[]` (`path`, `type`, `mtime`, `size_bytes`)",
        "responses": {
          "200": {
            "description": "`root`, `items[]` (`path`, `type`, `mtime`, `size_bytes`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "root",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Root path to list from."
          },
          {
            "name": "depth",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Traversal depth."
          },
          {
            "name": "default",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Query parameter `default`."
          },
          {
            "name": "include_hidden",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean"
            },
            "description": "Include dotfiles and hidden directories."
          }
        ]
      }
    },
    "/projects/{project_id}/files/content": {
      "get": {
        "operationId": "get_projects_project_id_files_content",
        "tags": [
          "Files"
        ],
        "summary": "Files: GET /projects/{project_id}/files/content",
        "description": "Expected input params: path: `project_id`; query required: `path`\n\nExpected output params: `path`, `encoding` (`utf-8`), `text`, `etag`",
        "responses": {
          "200": {
            "description": "`path`, `encoding` (`utf-8`), `text`, `etag`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "path",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Relative path."
          }
        ]
      },
      "put": {
        "operationId": "put_projects_project_id_files_content",
        "tags": [
          "Files"
        ],
        "summary": "Files: PUT /projects/{project_id}/files/content",
        "description": "Expected input params: path: `project_id`; body required: `path`, `text`; optional `etag` (optimistic concurrency)\n\nExpected output params: `ok` (bool), `etag`",
        "responses": {
          "200": {
            "description": "`ok` (bool), `etag`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `path`, `text`; optional `etag` (optimistic concurrency)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/files/batch": {
      "post": {
        "operationId": "post_projects_project_id_files_batch",
        "tags": [
          "Files"
        ],
        "summary": "Files: POST /projects/{project_id}/files/batch",
        "description": "Expected input params: path: `project_id`; body optional: `reads[]` (`path`), `writes[]` (`path`, `text`, `etag?`)\n\nExpected output params: `reads[]` (`path`, `ok`, `text?`, `etag?`, `error?`), `writes[]` (`path`, `ok`, `etag?`, `error?`)",
        "responses": {
          "200": {
            "description": "`reads[]` (`path`, `ok`, `text?`, `etag?`, `error?`), `writes[]` (`path`, `ok`, `etag?`, `error?`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": false,
          "description": "path: `project_id`; body optional: `reads[]` (`path`), `writes[]` (`path`, `text`, `etag?`)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/lint": {
      "post": {
        "operationId": "post_projects_project_id_lint",
        "tags": [
          "Files"
        ],
        "summary": "Files: POST /projects/{project_id}/lint",
        "description": "Expected input params: path: `project_id`; body required: `paths[]`\n\nExpected output params: `diagnostics[]` (`path`, `line`, `col`, `severity`, `code`, `message`)",
        "responses": {
          "200": {
            "description": "`diagnostics[]` (`path`, `line`, `col`, `severity`, `code`, `message`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `paths[]`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/format": {
      "post": {
        "operationId": "post_projects_project_id_format",
        "tags": [
          "Files"
        ],
        "summary": "Files: POST /projects/{project_id}/format",
        "description": "Expected input params: path: `project_id`; body required (shape not enforced)\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required (shape not enforced)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/search": {
      "post": {
        "operationId": "post_projects_project_id_search",
        "tags": [
          "Files"
        ],
        "summary": "Files: POST /projects/{project_id}/search",
        "description": "Expected input params: path: `project_id`; body required: `q`; optional `paths[]`, `case_sensitive?`, `regex?`\n\nExpected output params: `matches[]` (`path`, `line`, `preview`)",
        "responses": {
          "200": {
            "description": "`matches[]` (`path`, `line`, `preview`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `q`; optional `paths[]`, `case_sensitive?`, `regex?`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/diffs": {
      "get": {
        "operationId": "get_projects_project_id_diffs",
        "tags": [
          "Diffs"
        ],
        "summary": "Diffs: GET /projects/{project_id}/diffs",
        "description": "Expected input params: path: `project_id`; query: `status?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` diff objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` diff objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "status",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Status filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_projects_project_id_diffs",
        "tags": [
          "Diffs"
        ],
        "summary": "Diffs: POST /projects/{project_id}/diffs",
        "description": "Expected input params: path: `project_id`; body required: `title`, `patch`; optional `base_rev`\n\nExpected output params: `diff_id`",
        "responses": {
          "200": {
            "description": "`diff_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `title`, `patch`; optional `base_rev`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/diffs/{diff_id}": {
      "get": {
        "operationId": "get_diffs_diff_id",
        "tags": [
          "Diffs"
        ],
        "summary": "Diffs: GET /diffs/{diff_id}",
        "description": "Expected input params: path: `diff_id`\n\nExpected output params: `diff` (`id`, `project_id`, `title`, `status`, `stats`, `files`, `base_rev`, `created_at`)",
        "responses": {
          "200": {
            "description": "`diff` (`id`, `project_id`, `title`, `status`, `stats`, `files`, `base_rev`, `created_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "diff_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `diff_id`."
          }
        ]
      }
    },
    "/diffs/{diff_id}/apply": {
      "post": {
        "operationId": "post_diffs_diff_id_apply",
        "tags": [
          "Diffs"
        ],
        "summary": "Diffs: POST /diffs/{diff_id}/apply",
        "description": "Expected input params: path: `diff_id`; body optional: `commit_message`\n\nExpected output params: `ok` (bool), `commit` (hash string or empty string)",
        "responses": {
          "200": {
            "description": "`ok` (bool), `commit` (hash string or empty string)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "diff_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `diff_id`."
          }
        ],
        "requestBody": {
          "required": false,
          "description": "path: `diff_id`; body optional: `commit_message`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/diffs/{diff_id}/discard": {
      "post": {
        "operationId": "post_diffs_diff_id_discard",
        "tags": [
          "Diffs"
        ],
        "summary": "Diffs: POST /diffs/{diff_id}/discard",
        "description": "Expected input params: path: `diff_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "diff_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `diff_id`."
          }
        ]
      }
    },
    "/diffs/{diff_id}/comment": {
      "post": {
        "operationId": "post_diffs_diff_id_comment",
        "tags": [
          "Diffs"
        ],
        "summary": "Diffs: POST /diffs/{diff_id}/comment",
        "description": "Expected input params: path: `diff_id`; body required: `path`, `line`, `comment`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "diff_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `diff_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `diff_id`; body required: `path`, `line`, `comment`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/repo/status": {
      "get": {
        "operationId": "get_projects_project_id_repo_status",
        "tags": [
          "Repo"
        ],
        "summary": "Repo: GET /projects/{project_id}/repo/status",
        "description": "Expected input params: path: `project_id`\n\nExpected output params: `branch`, `dirty` (bool), `ahead` (int), `behind` (int), `changes[]` (`path`, `status`)",
        "responses": {
          "200": {
            "description": "`branch`, `dirty` (bool), `ahead` (int), `behind` (int), `changes[]` (`path`, `status`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ]
      }
    },
    "/projects/{project_id}/repo/checkout": {
      "post": {
        "operationId": "post_projects_project_id_repo_checkout",
        "tags": [
          "Repo"
        ],
        "summary": "Repo: POST /projects/{project_id}/repo/checkout",
        "description": "Expected input params: path: `project_id`; body required: `branch`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `branch`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/repo/pull": {
      "post": {
        "operationId": "post_projects_project_id_repo_pull",
        "tags": [
          "Repo"
        ],
        "summary": "Repo: POST /projects/{project_id}/repo/pull",
        "description": "Expected input params: path: `project_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ]
      }
    },
    "/projects/{project_id}/repo/commit": {
      "post": {
        "operationId": "post_projects_project_id_repo_commit",
        "tags": [
          "Repo"
        ],
        "summary": "Repo: POST /projects/{project_id}/repo/commit",
        "description": "Expected input params: path: `project_id`; body required: `message`; optional `paths[]`\n\nExpected output params: `ok` (bool), `commit` (hash)",
        "responses": {
          "200": {
            "description": "`ok` (bool), `commit` (hash)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `message`; optional `paths[]`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/terminal/sessions": {
      "post": {
        "operationId": "post_projects_project_id_terminal_sessions",
        "tags": [
          "Terminal"
        ],
        "summary": "Terminal: POST /projects/{project_id}/terminal/sessions",
        "description": "Expected input params: path: `project_id`; body required: `shell` (`bash`, `pwsh`, `cmd`, `zsh`); optional `cwd` (default `.`), `env` (object)\n\nExpected output params: `terminal_id`",
        "responses": {
          "200": {
            "description": "`terminal_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `shell` (`bash`, `pwsh`, `cmd`, `zsh`); optional `cwd` (default `.`), `env` (object)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/terminal/{terminal_id}/kill": {
      "post": {
        "operationId": "post_projects_project_id_terminal_terminal_id_kill",
        "tags": [
          "Terminal"
        ],
        "summary": "Terminal: POST /projects/{project_id}/terminal/{terminal_id}/kill",
        "description": "Expected input params: path: `project_id`, `terminal_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "terminal_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `terminal_id`."
          }
        ]
      }
    },
    "/projects/{project_id}/deployments": {
      "get": {
        "operationId": "get_projects_project_id_deployments",
        "tags": [
          "Deployments"
        ],
        "summary": "Deployments: GET /projects/{project_id}/deployments",
        "description": "Expected input params: path: `project_id`; query: `env?`, `status?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` deployment objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` deployment objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "env",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Environment filter."
          },
          {
            "name": "status",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Status filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_projects_project_id_deployments",
        "tags": [
          "Deployments"
        ],
        "summary": "Deployments: POST /projects/{project_id}/deployments",
        "description": "Expected input params: path: `project_id`; body required: `env`, `target`, `strategy`; optional `revision` (default `HEAD`)\n\nExpected output params: `deployment_id`",
        "responses": {
          "200": {
            "description": "`deployment_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `env`, `target`, `strategy`; optional `revision` (default `HEAD`)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/deployments/{deployment_id}": {
      "get": {
        "operationId": "get_deployments_deployment_id",
        "tags": [
          "Deployments"
        ],
        "summary": "Deployments: GET /deployments/{deployment_id}",
        "description": "Expected input params: path: `deployment_id`\n\nExpected output params: `deployment` (`id`, `project_id`, `env`, `target`, `revision`, `strategy`, `status`, `progress`, `started_at`, `ended_at`, `steps[]`)",
        "responses": {
          "200": {
            "description": "`deployment` (`id`, `project_id`, `env`, `target`, `revision`, `strategy`, `status`, `progress`, `started_at`, `ended_at`, `steps[]`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "deployment_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `deployment_id`."
          }
        ]
      }
    },
    "/deployments/{deployment_id}/logs": {
      "get": {
        "operationId": "get_deployments_deployment_id_logs",
        "tags": [
          "Deployments"
        ],
        "summary": "Deployments: GET /deployments/{deployment_id}/logs",
        "description": "Expected input params: path: `deployment_id`; query: `limit?`, `cursor?`\n\nExpected output params: `items[]` (`ts`, `level`, `text`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` (`ts`, `level`, `text`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "deployment_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `deployment_id`."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/deployments/{deployment_id}/cancel": {
      "post": {
        "operationId": "post_deployments_deployment_id_cancel",
        "tags": [
          "Deployments"
        ],
        "summary": "Deployments: POST /deployments/{deployment_id}/cancel",
        "description": "Expected input params: path: `deployment_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "deployment_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `deployment_id`."
          }
        ]
      }
    },
    "/projects/{project_id}/telemetry/streams": {
      "get": {
        "operationId": "get_projects_project_id_telemetry_streams",
        "tags": [
          "Telemetry"
        ],
        "summary": "Telemetry: GET /projects/{project_id}/telemetry/streams",
        "description": "Expected input params: path: `project_id`; query: `limit?`, `cursor?`\n\nExpected output params: `items[]` stream objects (`id`, `label`, `type`, `bands[]`, `status`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` stream objects (`id`, `label`, `type`, `bands[]`, `status`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/telemetry/query": {
      "post": {
        "operationId": "post_telemetry_query",
        "tags": [
          "Telemetry"
        ],
        "summary": "Telemetry: POST /telemetry/query",
        "description": "Expected input params: body required: `stream_id`, `time_range` (`from`, `to` ISO timestamps); optional `limit`\n\nExpected output params: `series[]` (`ts`, `value`), `anomalies[]`",
        "responses": {
          "200": {
            "description": "`series[]` (`ts`, `value`), `anomalies[]`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `stream_id`, `time_range` (`from`, `to` ISO timestamps); optional `limit`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/telemetry/alerts": {
      "post": {
        "operationId": "post_telemetry_alerts",
        "tags": [
          "Telemetry"
        ],
        "summary": "Telemetry: POST /telemetry/alerts",
        "description": "Expected input params: body required: `name`, `stream_id`, `condition`, `actions`\n\nExpected output params: `alert_id`",
        "responses": {
          "200": {
            "description": "`alert_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `name`, `stream_id`, `condition`, `actions`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/workflows": {
      "get": {
        "operationId": "get_projects_project_id_workflows",
        "tags": [
          "Workflows"
        ],
        "summary": "Workflows: GET /projects/{project_id}/workflows",
        "description": "Expected input params: path: `project_id`; query: `limit?`, `cursor?`\n\nExpected output params: `items[]` workflow objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` workflow objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_projects_project_id_workflows",
        "tags": [
          "Workflows"
        ],
        "summary": "Workflows: POST /projects/{project_id}/workflows",
        "description": "Expected input params: path: `project_id`; body required: `name`; optional `description`, `tags[]`\n\nExpected output params: `workflow_id`",
        "responses": {
          "200": {
            "description": "`workflow_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `name`; optional `description`, `tags[]`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/workflows/{workflow_id}": {
      "get": {
        "operationId": "get_workflows_workflow_id",
        "tags": [
          "Workflows"
        ],
        "summary": "Workflows: GET /workflows/{workflow_id}",
        "description": "Expected input params: path: `workflow_id`\n\nExpected output params: `workflow` (`id`, `project_id`, `name`, `description`, `tags`, `graph`, `created_at`, `updated_at`)",
        "responses": {
          "200": {
            "description": "`workflow` (`id`, `project_id`, `name`, `description`, `tags`, `graph`, `created_at`, `updated_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "workflow_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `workflow_id`."
          }
        ]
      },
      "put": {
        "operationId": "put_workflows_workflow_id",
        "tags": [
          "Workflows"
        ],
        "summary": "Workflows: PUT /workflows/{workflow_id}",
        "description": "Expected input params: path: `workflow_id`; body required: `graph` (object)\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "workflow_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `workflow_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `workflow_id`; body required: `graph` (object)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/workflows/{workflow_id}/runs": {
      "post": {
        "operationId": "post_workflows_workflow_id_runs",
        "tags": [
          "Workflows"
        ],
        "summary": "Workflows: POST /workflows/{workflow_id}/runs",
        "description": "Expected input params: path: `workflow_id`; body required: `inputs`\n\nExpected output params: `run_id`",
        "responses": {
          "200": {
            "description": "`run_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "workflow_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `workflow_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `workflow_id`; body required: `inputs`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/projects/{project_id}/artifacts": {
      "get": {
        "operationId": "get_projects_project_id_artifacts",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: GET /projects/{project_id}/artifacts",
        "description": "Expected input params: path: `project_id`; query: `type?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` artifact objects, `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` artifact objects, `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          },
          {
            "name": "type",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Type filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_projects_project_id_artifacts",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: POST /projects/{project_id}/artifacts",
        "description": "Expected input params: path: `project_id`; body required: `type`; optional `label`, `paths[]` (used for `type=zip`)\n\nExpected output params: `artifact_id`, `download_url`",
        "responses": {
          "200": {
            "description": "`artifact_id`, `download_url`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `project_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `project_id`; body required: `type`; optional `label`, `paths[]` (used for `type=zip`)",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/artifacts/{artifact_id}": {
      "get": {
        "operationId": "get_artifacts_artifact_id",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: GET /artifacts/{artifact_id}",
        "description": "Expected input params: path: `artifact_id`\n\nExpected output params: `artifact` (`id`, `project_id`, `type`, `label`, `size_bytes`, `download_url`, `created_at`)",
        "responses": {
          "200": {
            "description": "`artifact` (`id`, `project_id`, `type`, `label`, `size_bytes`, `download_url`, `created_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "artifact_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `artifact_id`."
          }
        ]
      }
    },
    "/uploads": {
      "post": {
        "operationId": "post_uploads",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: POST /uploads",
        "description": "Expected input params: body required: `filename`, `content_type`, `size_bytes`\n\nExpected output params: `upload_id`, `method`, `url`, `headers`, `file_id`",
        "responses": {
          "200": {
            "description": "`upload_id`, `method`, `url`, `headers`, `file_id`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `filename`, `content_type`, `size_bytes`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/uploads/{upload_id}": {
      "put": {
        "operationId": "put_uploads_upload_id",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: PUT /uploads/{upload_id}",
        "description": "Expected input params: path: `upload_id`; raw request body bytes (file data)\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "upload_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `upload_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `upload_id`; raw request body bytes (file data)",
          "content": {
            "application/octet-stream": {
              "schema": {
                "type": "string",
                "format": "binary"
              }
            }
          }
        }
      },
      "post": {
        "operationId": "post_uploads_upload_id",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: POST /uploads/{upload_id}",
        "description": "Expected input params: path: `upload_id`; raw request body bytes (file data)\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "upload_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `upload_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `upload_id`; raw request body bytes (file data)",
          "content": {
            "application/octet-stream": {
              "schema": {
                "type": "string",
                "format": "binary"
              }
            }
          }
        }
      }
    },
    "/files/{file_id}": {
      "get": {
        "operationId": "get_files_file_id",
        "tags": [
          "Artifacts / Uploads"
        ],
        "summary": "Artifacts / Uploads: GET /files/{file_id}",
        "description": "Expected input params: path: `file_id`\n\nExpected output params: `file` (`id`, `filename`, `size_bytes`, `content_type`, `created_at`)",
        "responses": {
          "200": {
            "description": "`file` (`id`, `filename`, `size_bytes`, `content_type`, `created_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "file_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `file_id`."
          }
        ]
      }
    },
    "/notifications": {
      "get": {
        "operationId": "get_notifications",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: GET /notifications",
        "description": "Expected input params: query: `limit?`, `cursor?`\n\nExpected output params: `items[]` (`id`, `ts`, `level`, `title`, `body`, `acked`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` (`id`, `ts`, `level`, `title`, `body`, `acked`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/notifications/ack": {
      "post": {
        "operationId": "post_notifications_ack",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: POST /notifications/ack",
        "description": "Expected input params: body required: `ids[]`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `ids[]`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/audit": {
      "get": {
        "operationId": "get_audit",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: GET /audit",
        "description": "Expected input params: query: `project_id?`, `type?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` audit event objects (`id`, `ts`, `actor_user_id`, `project_id`, `type`, `data`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` audit event objects (`id`, `ts`, `actor_user_id`, `project_id`, `type`, `data`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "project_id",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Project ID filter."
          },
          {
            "name": "type",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Type filter."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      }
    },
    "/admin/users": {
      "get": {
        "operationId": "get_admin_users",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: GET /admin/users",
        "description": "Expected input params: query: `q?`, `limit?`, `cursor?`\n\nExpected output params: `items[]` users (`id`, `name`, `email`, `roles[]`, `created_at`), `next_cursor`",
        "responses": {
          "200": {
            "description": "`items[]` users (`id`, `name`, `email`, `roles[]`, `created_at`), `next_cursor`",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "q",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Search query."
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination limit (default 50)."
          },
          {
            "name": "cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Pagination cursor/offset."
          }
        ]
      },
      "post": {
        "operationId": "post_admin_users",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: POST /admin/users",
        "description": "Expected input params: body required: `name`, `email`, `roles`; optional `password`\n\nExpected output params: `user` (`id`, `name`, `email`, `roles[]`, `created_at`)",
        "responses": {
          "200": {
            "description": "`user` (`id`, `name`, `email`, `roles[]`, `created_at`)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "requestBody": {
          "required": true,
          "description": "body required: `name`, `email`, `roles`; optional `password`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      }
    },
    "/admin/users/{user_id}": {
      "patch": {
        "operationId": "patch_admin_users_user_id",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: PATCH /admin/users/{user_id}",
        "description": "Expected input params: path: `user_id`; body required with one or more of `name`, `roles[]`, `password`, `disabled`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "user_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `user_id`."
          }
        ],
        "requestBody": {
          "required": true,
          "description": "path: `user_id`; body required with one or more of `name`, `roles[]`, `password`, `disabled`",
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": true
              }
            }
          }
        }
      },
      "delete": {
        "operationId": "delete_admin_users_user_id",
        "tags": [
          "Notifications / Audit / Admin"
        ],
        "summary": "Notifications / Audit / Admin: DELETE /admin/users/{user_id}",
        "description": "Expected input params: path: `user_id`\n\nExpected output params: `ok` (bool)",
        "responses": {
          "200": {
            "description": "`ok` (bool)",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GenericObject"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "user_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `user_id`."
          }
        ]
      }
    },
    "/stream/sessions/{session_id}": {
      "get": {
        "operationId": "get_stream_sessions_session_id",
        "tags": [
          "Streaming"
        ],
        "summary": "Streaming: GET /stream/sessions/{session_id}",
        "description": "Expected input params: path: `session_id`; query: `run_id?`, `from_cursor?` (int, default `0`)\n\nExpected output params: `text/event-stream` response. SSE events contain `id`, `event`, and `data` JSON envelope: `{ \"type\": \"...\", \"ts\": \"...\", \"data\": { ...event... } }`. If no events, emits `: keep-alive`.",
        "responses": {
          "200": {
            "description": "`text/event-stream` response. SSE events contain `id`, `event`, and `data` JSON envelope: `{ \"type\": \"...\", \"ts\": \"...\", \"data\": { ...event... } }`. If no events, emits `: keep-alive`.",
            "content": {
              "text/event-stream": {
                "schema": {
                  "type": "string"
                }
              }
            }
          },
          "default": {
            "description": "Error response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Error"
                }
              }
            }
          }
        },
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Path parameter `session_id`."
          },
          {
            "name": "run_id",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string"
            },
            "description": "Run ID filter."
          },
          {
            "name": "from_cursor",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer"
            },
            "description": "Stream cursor offset."
          },
          {
            "name": "default",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Query parameter `default`."
          }
        ]
      }
    }
  }
}
```
