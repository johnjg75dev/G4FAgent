from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Type


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: Optional[Any] = None


_TOOL_REGISTRY: Dict[str, Tuple[Type["ToolCategory"], str]] = {}
_LOADED_EXTERNAL_TOOL_FILES: set[str] = set()


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


def _ensure_builtin_tools_loaded() -> None:
    # Import side effect registers built-in tool categories.
    importlib.import_module("g4fagent.tools.files")


def _module_name_for_tool_file(path: Path) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_]", "_", path.stem)
    digest = abs(hash(str(path.resolve())))
    return f"g4fagent.external_tools.{stem}_{digest}"


def load_tool_modules_from_dir(tools_dir: Path) -> list[str]:
    tools_path = Path(tools_dir).resolve()
    if not tools_path.exists():
        raise FileNotFoundError(f"Tools directory not found: {tools_path}")
    if not tools_path.is_dir():
        raise NotADirectoryError(f"Tools path is not a directory: {tools_path}")

    loaded: list[str] = []
    for py_file in sorted(tools_path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        file_key = str(py_file.resolve())
        if file_key in _LOADED_EXTERNAL_TOOL_FILES:
            continue

        module_name = _module_name_for_tool_file(py_file)
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load tool module from: {py_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        _LOADED_EXTERNAL_TOOL_FILES.add(file_key)
        loaded.append(module_name)

    return loaded


class ToolRuntime:
    def __init__(self, root: Path, extra_tool_dirs: Optional[Iterable[Path | str]] = None):
        _ensure_builtin_tools_loaded()
        self.root = Path(root).resolve()
        self._instances: Dict[Type[ToolCategory], ToolCategory] = {}
        self._loaded_tool_modules: list[str] = []

        if extra_tool_dirs:
            for tools_dir in extra_tool_dirs:
                self.load_tool_dir(Path(tools_dir))

    def load_tool_dir(self, tools_dir: Path | str) -> list[str]:
        loaded = load_tool_modules_from_dir(Path(tools_dir))
        self._loaded_tool_modules.extend(loaded)
        return loaded

    def loaded_modules(self) -> list[str]:
        return list(self._loaded_tool_modules)

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
