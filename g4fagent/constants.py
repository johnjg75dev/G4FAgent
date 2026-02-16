"""Default constants and configuration templates used by g4fagent.

Inputs:
- Static values defined in module source.
Output:
- Reusable constants for config defaults, prompt templates, and runtime settings.
Example:
```python
from g4fagent.constants import DEFAULT_CONFIG
print(DEFAULT_CONFIG["pipeline"]["order"])
```
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_REL_PATH = "assets/config.json"
DEFAULT_AGENTS_REL_DIR = "assets/agents"

G4F_SUPPORTED_CHAT_PARAMS = {
    "stream",
    "image",
    "image_name",
    "ignore_working",
    "ignore_stream",
    "media",
    "modalities",
    "temperature",
    "presence_penalty",
    "frequency_penalty",
    "top_p",
    "max_tokens",
    "stop",
    "api_key",
    "base_url",
    "web_search",
    "proxy",
    "conversation",
    "timeout",
    "stream_timeout",
    "tool_calls",
    "reasoning_effort",
    "logit_bias",
    "audio",
    "response_format",
    "download_media",
    "raw",
    "extra_body",
    "tool_emulation",
    "images",
    "tools",
    "parallel_tool_calls",
    "tool_choice",
    "conversation_id",
}

DEFAULT_SYSTEM_PROMPT = """You are a senior software architect + implementer.
You will work interactively with a human.

Hard rules:
- In the PLANNING phase, do NOT write code. Produce: TODO list, program layout (folders/files), and a spec for each file.
- In the WRITING phase, write ONLY the single requested file.
- Prefer small edits using tools (apply_patch) instead of rewriting entire files when asked to change something.
- When proposing a change, be explicit and concrete.

Tool calling:
- If you want to use a tool, respond with ONLY a JSON object like:
  {"tool":"read_file","args":{"path":"relative/path.txt"}}
  {"tool":"write_file","args":{"path":"src/main.py","content":"...","overwrite":true}}
  {"tool":"apply_patch","args":{"path":"src/main.py","diff":"*** unified diff ***"}}
  {"tool":"list_dir","args":{"path":"."}}
  {"tool":"delete_file","args":{"path":"old.txt"}}
- Otherwise respond normally in plain text.

You are allowed to ask the human for clarification ONLY if absolutely necessary.
"""

DEFAULT_PLANNING_USER_PROMPT_TEMPLATE = """User project request:
{user_prompt}

Given the user's project request, produce:

1) A prioritized TODO list (milestones + tasks)
2) A project tree (folders and files)
3) For EACH file: a concise spec that includes:
   - purpose
   - key functions/classes
   - inputs/outputs
   - edge cases
   - dependencies

Constraints:
- No actual code yet.
- Keep it practical and implementable.
- Choose sensible defaults.

Also include a machine-readable JSON block at the END in this exact format:

<PLAN_JSON>
{{
  "todo": ["..."],
  "files": [
    {{
      "path": "relative/path.ext",
      "spec": "short spec string"
    }}
  ]
}}
</PLAN_JSON>

The JSON must be valid.
"""

DEFAULT_WRITING_USER_PROMPT_TEMPLATE = """Project context:
{project_context_json}

Now write ONLY the file: {file_path}

Use the file spec and overall architecture.
If you need to see existing files, call tools (read_file/list_dir).
If a file already exists and you are revising it, prefer apply_patch with a unified diff.

Output rules:
- If not using a tool: output the full content of {file_path}, and nothing else.
- No surrounding markdown fences unless the user asks.
"""

DEFAULT_DEBUG_USER_PROMPT_TEMPLATE = """Project context:
{project_context_json}

Quality-check outputs (stdout/stderr, errors, warnings):
{quality_report_json}

Fix instructions:
- Fix the reported issues so lint/tests pass.
- Use tools to inspect and modify files.
- Make focused, minimal edits tied to the reported outputs.
- If checks show warnings, address meaningful warnings where practical.

Output rules:
- If using a tool, respond with ONLY the JSON tool-call envelope.
- If not using a tool, summarize what was changed and what to re-run.
"""

DEFAULT_AGENTS: Dict[str, Dict[str, Any]] = {
    "PlanningAgent": {
        "role": "PlanningAgent",
        "description": "Builds the implementation plan and structured file specs.",
        "model": "default",
        "provider": None,
        "prompt": DEFAULT_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_PLANNING_USER_PROMPT_TEMPLATE,
        "g4f_params": {
            "temperature": 0.2,
        },
    },
    "WritingAgent": {
        "role": "WritingAgent",
        "description": "Writes or revises individual files with tool-call support.",
        "model": "default",
        "provider": None,
        "prompt": DEFAULT_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_WRITING_USER_PROMPT_TEMPLATE,
        "g4f_params": {
            "temperature": 0.2,
        },
    },
    "DebugAgent": {
        "role": "DebugAgent",
        "description": "Fixes lint/test failures using command output context and tools.",
        "model": "default",
        "provider": None,
        "prompt": DEFAULT_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_DEBUG_USER_PROMPT_TEMPLATE,
        "g4f_params": {
            "temperature": 0.1,
        },
    },
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "agents_dir": DEFAULT_AGENTS_REL_DIR,
    "pipeline": {
        "order": ["planning", "writing", "debug"],
        "stages": {
            "planning": {
                "role": "PlanningAgent",
                "overrides": {
                    "model": None,
                    "provider": None,
                    "g4f_params": {},
                },
            },
            "writing": {
                "role": "WritingAgent",
                "overrides": {
                    "model": None,
                    "provider": None,
                    "g4f_params": {},
                },
            },
            "debug": {
                "role": "DebugAgent",
                "overrides": {
                    "model": None,
                    "provider": None,
                    "g4f_params": {},
                },
            },
        },
    },
    "quality_checks": {
        "lint_commands": [],
        "test_commands": [],
        "max_debug_rounds": 2,
        "debug_max_tool_steps": 10,
    },
    "g4f_defaults": {
        "max_retries": 2,
        "stream": False,
        "image": None,
        "image_name": None,
        "ignore_working": False,
        "ignore_stream": False,
        "media": None,
        "modalities": None,
        "temperature": 0.2,
        "presence_penalty": None,
        "frequency_penalty": None,
        "top_p": None,
        "max_tokens": None,
        "stop": None,
        "api_key": None,
        "base_url": None,
        "web_search": None,
        "proxy": None,
        "conversation": None,
        "timeout": None,
        "stream_timeout": None,
        "tool_calls": [],
        "reasoning_effort": None,
        "logit_bias": None,
        "audio": None,
        "response_format": None,
        "download_media": False,
        "raw": False,
        "extra_body": None,
        "tool_emulation": None,
        "images": None,
        "tools": None,
        "parallel_tool_calls": None,
        "tool_choice": None,
        "conversation_id": None,
        "extra_kwargs": {},
    },
}
