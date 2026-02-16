# g4fagent SDK

`g4fagent` is the importable library layer for building stage-based, role-driven agent workflows on top of `g4f`.

## Public API

- `G4FManager`: primary interface
- `Pipeline`: ordered stages
- `Stage`: stage-level role binding and overrides
- `Agent`: role definition and request/message builders
- `Project`: accepted data, chat history, runtime state, and tracked files
- `ProjectFile`: per-file tracked metadata stored under `Project.files`
- `LLMConfig`: runtime execution settings

## Basic usage

```python
from g4fagent import G4FManager
from g4fagent.constants import APP_ROOT

manager = G4FManager.from_config(
    config_rel_path="config.json",
    base_dir=APP_ROOT,
)

planning_stage, writing_stage = manager.default_stage_names()
print(planning_stage, writing_stage)
```

## Stage execution example

```python
response = manager.chat_stage(
    stage_name="planning",
    template_context={"user_prompt": "Build a CLI todo app"},
)
print(response)
```

## Vision/image prompt example

```python
response = manager.chat_stage(
    stage_name="writing",
    template_context={
        "project_context_json": "{}",
        "file_path": "README.md",
    },
    image="https://example.com/screenshot.png",
    image_name="screenshot.png",
)
print(response)
```

## Tool runtime

```python
from pathlib import Path
from g4fagent.tools import ToolRuntime

runtime = ToolRuntime(
    root=Path("."),
    extra_tool_dirs=["./custom_tools"],  # optional
)
print(runtime.available_tools())
```

## Configuration model

- Runtime config comes from `config.json`.
- Role definitions come from `agents/<RoleName>.json`.
- `Pipeline.order` controls default stage execution order.
- Per-stage overrides can change model/provider/params without modifying role files.
