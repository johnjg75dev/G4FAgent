"""Configuration loading and runtime resolution for the g4fagent SDK.

Inputs:
- Base directory and config-relative paths provided by callers.
Output:
- Fully resolved runtime configuration dictionaries and helper path utilities.
Example:
```python
from g4fagent.config import load_runtime_config
cfg = load_runtime_config(base_dir, "config.json")
```
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .constants import DEFAULT_AGENTS, DEFAULT_AGENTS_REL_DIR, DEFAULT_CONFIG
from .utils import deep_merge_dict, ensure_rel_path, pretty_json


def write_json(path: Path, obj: Any) -> None:
    """Write an object to disk as UTF-8 JSON with stable formatting.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = write_json(...)
    ```
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pretty_json(obj) + "\n", encoding="utf-8")


def load_json_object(path: Path) -> Dict[str, Any]:
    """Load and validate that a JSON file contains an object.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = load_json_object(...)
    ```
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def resolve_pipeline_stages(runtime_cfg: Dict[str, Any]) -> Tuple[str, str]:
    """Resolve default planning and writing stage names from pipeline order.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = resolve_pipeline_stages(...)
    ```
    """
    pipeline = (runtime_cfg.get("pipeline", {}) or {})
    order = pipeline.get("order", [])
    if isinstance(order, list):
        clean = [str(x) for x in order if isinstance(x, str) and x]
    else:
        clean = []
    planning_stage = clean[0] if len(clean) > 0 else "planning"
    writing_stage = clean[1] if len(clean) > 1 else "writing"
    return planning_stage, writing_stage


def ensure_runtime_config_files(base_dir: Path, config_rel_path: str) -> Path:
    """Create default config and agent files if missing, then return config path.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = ensure_runtime_config_files(...)
    ```
    """
    config_path = (base_dir / ensure_rel_path(config_rel_path)).resolve()
    if not config_path.exists():
        write_json(config_path, DEFAULT_CONFIG)

    agents_dir = (base_dir / DEFAULT_AGENTS_REL_DIR).resolve()
    agents_dir.mkdir(parents=True, exist_ok=True)
    for role, definition in DEFAULT_AGENTS.items():
        role_path = agents_dir / f"{role}.json"
        if not role_path.exists():
            write_json(role_path, definition)
    return config_path


def load_runtime_config(base_dir: Path, config_rel_path: str) -> Dict[str, Any]:
    """Load runtime config and fully resolve referenced agent definitions.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = load_runtime_config(...)
    ```
    """
    config_path = ensure_runtime_config_files(base_dir, config_rel_path)
    config_obj = deep_merge_dict(DEFAULT_CONFIG, load_json_object(config_path))

    agents_dir_rel = config_obj.get("agents_dir", DEFAULT_AGENTS_REL_DIR)
    agents_dir = (base_dir / ensure_rel_path(str(agents_dir_rel))).resolve()
    stages = (config_obj.get("pipeline", {}) or {}).get("stages", {}) or {}

    loaded_agents: Dict[str, Dict[str, Any]] = {}
    missing_roles: List[str] = []
    for stage in stages.values():
        if not isinstance(stage, dict):
            continue
        role = stage.get("role")
        if not role or not isinstance(role, str):
            continue
        if role in loaded_agents:
            continue
        role_file = agents_dir / f"{role}.json"
        if not role_file.exists():
            missing_roles.append(role)
            continue
        loaded_agents[role] = deep_merge_dict(DEFAULT_AGENTS.get(role, {}), load_json_object(role_file))

    if missing_roles:
        raise FileNotFoundError(
            f"Missing agent definition files in {agents_dir}: "
            + ", ".join([f"{r}.json" for r in missing_roles])
        )

    planning_stage, writing_stage = resolve_pipeline_stages(config_obj)
    if planning_stage not in stages or writing_stage not in stages:
        raise KeyError(
            f"Pipeline stages from order are missing in pipeline.stages: "
            f"{planning_stage!r}, {writing_stage!r}"
        )

    config_obj["_meta"] = {
        "config_path": str(config_path),
        "agents_dir": str(agents_dir),
    }
    config_obj["loaded_agents"] = loaded_agents
    return config_obj
