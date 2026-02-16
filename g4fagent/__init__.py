"""Public package exports for the g4fagent SDK.

Inputs:
- Standard Python imports from downstream application code.
Output:
- Public SDK symbols (`Agent`, `Stage`, `Pipeline`, `Project`, `ProjectFile`, `LLMConfig`, `G4FManager`).
Example:
```python
from g4fagent import G4FManager
manager = G4FManager.from_config()
```
"""

from .core import Agent, G4FManager, LLMConfig, Pipeline, Project, ProjectFile, Stage, resolve_model_name
from .core import ModelScanResult, ModelScanSummary, list_known_model_names, scan_models
from .utils import detect_verification_program_paths

__all__ = [
    "Agent",
    "Stage",
    "Pipeline",
    "Project",
    "ProjectFile",
    "LLMConfig",
    "G4FManager",
    "resolve_model_name",
    "list_known_model_names",
    "scan_models",
    "ModelScanResult",
    "ModelScanSummary",
    "detect_verification_program_paths",
]
