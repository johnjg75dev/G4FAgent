from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: Optional[Any] = None


_TOOL_REGISTRY: Dict[str, Tuple[Type["ToolCategory"], str]] = {}


def tool(name: Optional[str] = None):
    def decorator(func):
        setattr(func, "_tool_name", name or func.__name__)
        return func
    return decorator


class ToolCategoryMeta(type):
    def __new__(mcls, name, bases, namespace):
        cls = super().__new__(mcls, name, bases, namespace)
        for attr_name, attr_value in namespace.items():
            tool_name = getattr(attr_value, "_tool_name", None)
            if not tool_name:
                continue
            if tool_name in _TOOL_REGISTRY:
                existing_cls, existing_attr = _TOOL_REGISTRY[tool_name]
                raise ValueError(
                    f"Duplicate tool registration for '{tool_name}': "
                    f"{existing_cls.__name__}.{existing_attr} and {name}.{attr_name}"
                )
            _TOOL_REGISTRY[tool_name] = (cls, attr_name)
        return cls


class ToolCategory(metaclass=ToolCategoryMeta):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()


class ToolRuntime:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._instances: Dict[Type[ToolCategory], ToolCategory] = {}

    def available_tools(self) -> list[str]:
        return sorted(_TOOL_REGISTRY.keys())

    def execute(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> ToolResult:
        args = args or {}
        spec = _TOOL_REGISTRY.get(tool_name)
        if spec is None:
            return ToolResult(False, f"Unknown tool: {tool_name}")

        cls, method_name = spec
        instance = self._instances.get(cls)
        if instance is None:
            instance = cls(self.root)
            self._instances[cls] = instance

        method = getattr(instance, method_name)
        try:
            result = method(**args)
        except TypeError as e:
            return ToolResult(False, f"Invalid args for '{tool_name}': {e}")
        except Exception as e:
            return ToolResult(False, f"{tool_name} error: {e}")

        if isinstance(result, ToolResult):
            return result
        return ToolResult(True, str(result), result)
