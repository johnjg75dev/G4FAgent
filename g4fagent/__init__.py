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
from .core import (
    ModelScanResult,
    ModelScanSummary,
    list_known_model_names,
    list_known_model_names_for_provider,
    list_known_provider_names,
    resolve_provider_name,
    scan_models,
)
from .database import (
    DATABASE_BACKENDS,
    Database,
    JSONDatabase,
    MariaDatabase,
    MongoDatabase,
    MySQLDatabase,
    PostgresDatabase,
    SQLiteDatabase,
    create_database,
)
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
    "resolve_provider_name",
    "list_known_model_names",
    "list_known_provider_names",
    "list_known_model_names_for_provider",
    "scan_models",
    "ModelScanResult",
    "ModelScanSummary",
    "detect_verification_program_paths",
    "Database",
    "JSONDatabase",
    "SQLiteDatabase",
    "MySQLDatabase",
    "MariaDatabase",
    "PostgresDatabase",
    "MongoDatabase",
    "create_database",
    "DATABASE_BACKENDS",
]
