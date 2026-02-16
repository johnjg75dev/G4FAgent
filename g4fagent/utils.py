"""General utility helpers shared by the g4fagent SDK and CLI wrapper.

Inputs:
- Plain Python values such as strings, paths, dictionaries, and message content.
Output:
- Normalized values, parsed structures, formatted text, and helper diagnostics.
Example:
```python
from g4fagent.utils import pretty_json
print(pretty_json({"ok": True}))
```
"""

from __future__ import annotations

import copy
import datetime as _dt
import difflib
import json
import os
import py_compile
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def now_iso() -> str:
    """Return the current local timestamp as an ISO-8601 string.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = now_iso(...)
    ```
    """
    return _dt.datetime.now().isoformat(timespec="seconds")


def print_hr(char: str = "─", n: int = 80) -> None:
    """Print a horizontal rule with a repeated character.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = print_hr(...)
    ```
    """
    print(char * n)


def clamp(s: str, limit: int = 4000) -> str:
    """Clamp a string length for logging/debug display.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = clamp(...)
    ```
    """
    s = s or ""
    return s if len(s) <= limit else s[:limit] + "\n...<truncated>..."


def prompt_multiline(title: str) -> str:
    """Prompt for multi-line user input terminated by a line containing END.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = prompt_multiline(...)
    ```
    """
    print_hr()
    print(title)
    print("Enter text. End with a single line containing:  END")
    lines: List[str] = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def ask_choice(prompt: str, choices: Dict[str, str], default_key: str) -> str:
    """Prompt the user for a key from a choices mapping.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = ask_choice(...)
    ```
    """
    keys = "/".join(choices.keys())
    while True:
        desc = " | ".join([f"{k}={v}" for k, v in choices.items()])
        resp = input(f"{prompt} [{keys}] (default {default_key})  {desc}\n> ").strip().lower()
        if not resp:
            return default_key
        if resp in choices:
            return resp
        print("Invalid choice. Try again.")


def ensure_rel_path(p: str) -> Path:
    """Validate and normalize a safe relative path.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = ensure_rel_path(...)
    ```
    """
    pp = Path(p)
    if pp.is_absolute():
        raise ValueError(f"Absolute paths not allowed: {p}")
    norm = Path(os.path.normpath(str(pp)))
    if str(norm).startswith(".."):
        raise ValueError(f"Path escapes project root: {p}")
    return norm


def pretty_json(obj: Any) -> str:
    """Serialize an object to pretty-printed JSON.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = pretty_json(...)
    ```
    """
    return json.dumps(obj, indent=2, ensure_ascii=False)


def msg(role: str, content: str) -> Dict[str, str]:
    """Construct a simple chat message dictionary.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = msg(...)
    ```
    """
    return {"role": role, "content": content}


def sanitize_generated_file_content(text: str) -> str:
    """Extract probable file contents from model output text.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = sanitize_generated_file_content(...)
    ```
    """
    s = (text or "").strip()
    if not s:
        return s

    fenced_blocks = re.findall(r"```(?:[^\n`]*)\n(.*?)```", s, flags=re.DOTALL)
    if fenced_blocks:
        return fenced_blocks[0].strip("\n")

    if "\n\n" in s:
        head, rest = s.split("\n\n", 1)
        head_l = head.lower()
        if any(p in head_l for p in ("understood", "sure", "i will", "i'll", "here is", "based on")):
            return rest.lstrip()

    lines = s.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            return "\n".join(lines[i:]).strip()

    return s


def final_verify_written_files(root: Path, expected_files: Sequence[str]) -> Tuple[bool, str]:
    """Verify expected files exist, are non-empty, and Python files compile.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = final_verify_written_files(...)
    ```
    """
    missing: List[str] = []
    empty: List[str] = []
    py_errors: List[str] = []

    for rel in expected_files:
        p = root / rel
        if not p.exists() or not p.is_file():
            missing.append(rel)
            continue
        try:
            if p.stat().st_size == 0:
                empty.append(rel)
        except OSError:
            empty.append(rel)

        if p.suffix == ".py":
            try:
                py_compile.compile(str(p), doraise=True)
            except py_compile.PyCompileError as e:
                py_errors.append(f"{rel}: {e.msg}")
            except Exception as e:
                py_errors.append(f"{rel}: {e}")

    ok = not missing and not empty and not py_errors
    lines: List[str] = []
    if missing:
        lines.append("Missing files:")
        lines.extend([f"- {x}" for x in missing])
    if empty:
        lines.append("Empty files:")
        lines.extend([f"- {x}" for x in empty])
    if py_errors:
        lines.append("Python compile errors:")
        lines.extend([f"- {x}" for x in py_errors])
    if ok:
        lines.append("All planned files exist, are non-empty, and Python files compile.")
    return ok, "\n".join(lines)


def deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries, returning a deep-copied result.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = deep_merge_dict(...)
    ```
    """
    merged = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = deep_merge_dict(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def format_template(template: str, context: Dict[str, Any]) -> str:
    """Format a template while leaving unknown placeholders intact.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = format_template(...)
    ```
    """
    class SafeDict(dict):
        """Dictionary that echoes unknown keys as placeholders.
        
        Inputs:
        - Constructor fields and initialization parameters defined for this class.
        Output:
        - SafeDict: A configured `SafeDict` instance.
        Example:
        ```python
        obj = SafeDict(...)
        ```
        """

        def __missing__(self, key):
            """Return a placeholder marker for unknown template keys.
            
            Inputs:
            - Method parameters defined in the function signature (excluding `self`).
            Output:
            - The method return value as defined by its signature/annotations.
            Example:
            ```python
            value = instance.__missing__(...)
            ```
            """
            return "{" + key + "}"

    return (template or "").format_map(SafeDict(context))


def extract_plan_json(text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Extract and parse the <PLAN_JSON> payload from model output text.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = extract_plan_json(...)
    ```
    """
    m = re.search(r"<PLAN_JSON>\s*(\{.*?\})\s*</PLAN_JSON>", text, re.DOTALL)
    if not m:
        return text, None
    js = m.group(1)
    try:
        obj = json.loads(js)
    except Exception:
        obj = None
    cleaned = (text[: m.start()] + text[m.end() :]).strip()
    return cleaned, obj


def parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse a strict JSON tool-call envelope from model output.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = parse_tool_call(...)
    ```
    """
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if "tool" not in obj or "args" not in obj:
        return None
    return obj


def show_tree(root: Path) -> str:
    """Return a newline-separated file tree for a directory.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = show_tree(...)
    ```
    """
    lines: List[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_dir():
            continue
        lines.append(str(rel))
    return "\n".join(lines) if lines else "(empty)"


def unified_diff_str(old: str, new: str, path: str) -> str:
    """Return a unified diff string for two text contents.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = unified_diff_str(...)
    ```
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "\n".join(diff)
