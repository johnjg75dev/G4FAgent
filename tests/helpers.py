from __future__ import annotations

import copy
from typing import Any, Dict

from g4fagent.constants import DEFAULT_AGENTS, DEFAULT_CONFIG


def make_runtime_cfg() -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["loaded_agents"] = copy.deepcopy(DEFAULT_AGENTS)
    cfg["_meta"] = {
        "config_path": "config.json",
        "agents_dir": "agents",
    }
    return cfg

