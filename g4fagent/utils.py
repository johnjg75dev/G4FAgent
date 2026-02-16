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
import glob
import json
import os
import platform
import py_compile
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_VERIFICATION_PROGRAMS: List[str] = [
    "python",
    "pip",
    "pytest",
    "ruff",
    "mypy",
    "black",
    "node",
    "npm",
    "pnpm",
    "yarn",
    "eslint",
    "prettier",
    "jest",
    "vitest",
    "go",
    "golangci-lint",
    "cargo",
    "rustc",
    "rustfmt",
    "dotnet",
    "java",
    "javac",
    "mvn",
    "gradle",
]

PROGRAM_ALIASES: Dict[str, List[str]] = {
    "python": ["python", "python3", "py"],
    "pip": ["pip", "pip3"],
    "pytest": ["pytest"],
    "ruff": ["ruff"],
    "mypy": ["mypy"],
    "black": ["black"],
    "node": ["node"],
    "npm": ["npm"],
    "pnpm": ["pnpm"],
    "yarn": ["yarn"],
    "eslint": ["eslint"],
    "prettier": ["prettier"],
    "jest": ["jest"],
    "vitest": ["vitest"],
    "go": ["go"],
    "golangci-lint": ["golangci-lint"],
    "cargo": ["cargo"],
    "rustc": ["rustc"],
    "rustfmt": ["rustfmt"],
    "dotnet": ["dotnet"],
    "java": ["java"],
    "javac": ["javac"],
    "mvn": ["mvn", "mvn.cmd"],
    "gradle": ["gradle", "gradle.bat"],
}

PROGRAM_COMMAND_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "python": {
        "lint": ["{exe} -m ruff check .", "{exe} -m mypy ."],
        "test": ['{exe} -m pytest -q', '{exe} -m unittest discover -s tests -p "test_*.py"'],
    },
    "pip": {},
    "pytest": {"test": ["{exe} -q"]},
    "ruff": {"lint": ["{exe} check ."]},
    "mypy": {"lint": ["{exe} ."]},
    "black": {"lint": ["{exe} --check ."]},
    "node": {"test": ["{exe} --test"]},
    "npm": {"lint": ["{exe} run lint"], "test": ["{exe} test"]},
    "pnpm": {"lint": ["{exe} lint"], "test": ["{exe} test"]},
    "yarn": {"lint": ["{exe} lint"], "test": ["{exe} test"]},
    "eslint": {"lint": ["{exe} ."]},
    "prettier": {"lint": ["{exe} --check ."]},
    "jest": {"test": ["{exe}"]},
    "vitest": {"test": ["{exe} run"]},
    "go": {"lint": ["{exe} vet ./..."], "test": ["{exe} test ./..."]},
    "golangci-lint": {"lint": ["{exe} run"]},
    "cargo": {"lint": ["{exe} clippy --all-targets -- -D warnings"], "test": ["{exe} test"]},
    "rustc": {},
    "rustfmt": {"lint": ["{exe} --check src/**/*.rs"]},
    "dotnet": {"lint": ["{exe} format --verify-no-changes"], "test": ["{exe} test"]},
    "java": {},
    "javac": {},
    "mvn": {"test": ["{exe} test"]},
    "gradle": {"test": ["{exe} test"]},
}

KNOWN_PROGRAM_PATH_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "Windows": {
        "python": [
            r"C:\Python*\python.exe",
            r"%LOCALAPPDATA%\Programs\Python\Python*\python.exe",
            r"%ProgramFiles%\Python*\python.exe",
            r"%ProgramFiles(x86)%\Python*\python.exe",
        ],
        "pip": [
            r"C:\Python*\Scripts\pip.exe",
            r"%LOCALAPPDATA%\Programs\Python\Python*\Scripts\pip.exe",
            r"%ProgramFiles%\Python*\Scripts\pip.exe",
            r"%ProgramFiles(x86)%\Python*\Scripts\pip.exe",
        ],
        "node": [r"%ProgramFiles%\nodejs\node.exe", r"%ProgramFiles(x86)%\nodejs\node.exe"],
        "npm": [r"%ProgramFiles%\nodejs\npm.cmd", r"%ProgramFiles(x86)%\nodejs\npm.cmd"],
        "pnpm": [r"%APPDATA%\npm\pnpm.cmd", r"%LOCALAPPDATA%\pnpm\pnpm.exe"],
        "yarn": [r"%APPDATA%\npm\yarn.cmd"],
        "go": [r"%ProgramFiles%\Go\bin\go.exe"],
        "golangci-lint": [r"%USERPROFILE%\go\bin\golangci-lint.exe"],
        "cargo": [r"%USERPROFILE%\.cargo\bin\cargo.exe"],
        "rustc": [r"%USERPROFILE%\.cargo\bin\rustc.exe"],
        "rustfmt": [r"%USERPROFILE%\.cargo\bin\rustfmt.exe"],
        "dotnet": [r"%ProgramFiles%\dotnet\dotnet.exe", r"%ProgramFiles(x86)%\dotnet\dotnet.exe"],
        "java": [
            r"%ProgramFiles%\Java\*\bin\java.exe",
            r"%ProgramFiles%\Eclipse Adoptium\*\bin\java.exe",
            r"%ProgramFiles(x86)%\Java\*\bin\java.exe",
        ],
        "javac": [
            r"%ProgramFiles%\Java\*\bin\javac.exe",
            r"%ProgramFiles%\Eclipse Adoptium\*\bin\javac.exe",
            r"%ProgramFiles(x86)%\Java\*\bin\javac.exe",
        ],
    },
    "Linux": {
        "python": ["/usr/bin/python3", "/usr/local/bin/python3", "/usr/bin/python"],
        "pip": ["/usr/bin/pip3", "/usr/local/bin/pip3", "/usr/bin/pip"],
        "node": ["/usr/bin/node", "/usr/local/bin/node"],
        "npm": ["/usr/bin/npm", "/usr/local/bin/npm"],
        "pnpm": ["/usr/bin/pnpm", "/usr/local/bin/pnpm"],
        "yarn": ["/usr/bin/yarn", "/usr/local/bin/yarn"],
        "go": ["/usr/local/go/bin/go", "/usr/bin/go"],
        "cargo": ["~/.cargo/bin/cargo"],
        "rustc": ["~/.cargo/bin/rustc"],
        "rustfmt": ["~/.cargo/bin/rustfmt"],
        "dotnet": ["/usr/bin/dotnet", "/usr/local/bin/dotnet"],
        "java": ["/usr/bin/java", "/usr/local/bin/java"],
        "javac": ["/usr/bin/javac", "/usr/local/bin/javac"],
        "mvn": ["/usr/bin/mvn", "/usr/local/bin/mvn"],
        "gradle": ["/usr/bin/gradle", "/usr/local/bin/gradle"],
    },
    "Darwin": {
        "python": ["/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"],
        "pip": ["/usr/bin/pip3", "/usr/local/bin/pip3", "/opt/homebrew/bin/pip3"],
        "node": ["/usr/local/bin/node", "/opt/homebrew/bin/node"],
        "npm": ["/usr/local/bin/npm", "/opt/homebrew/bin/npm"],
        "pnpm": ["/usr/local/bin/pnpm", "/opt/homebrew/bin/pnpm"],
        "yarn": ["/usr/local/bin/yarn", "/opt/homebrew/bin/yarn"],
        "go": ["/usr/local/go/bin/go", "/opt/homebrew/bin/go"],
        "cargo": ["~/.cargo/bin/cargo"],
        "rustc": ["~/.cargo/bin/rustc"],
        "rustfmt": ["~/.cargo/bin/rustfmt"],
        "dotnet": ["/usr/local/share/dotnet/dotnet", "/usr/local/bin/dotnet", "/opt/homebrew/bin/dotnet"],
        "java": ["/usr/bin/java", "/usr/local/bin/java"],
        "javac": ["/usr/bin/javac", "/usr/local/bin/javac"],
        "mvn": ["/usr/local/bin/mvn", "/opt/homebrew/bin/mvn"],
        "gradle": ["/usr/local/bin/gradle", "/opt/homebrew/bin/gradle"],
    },
}


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


def _uniq_strs(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _quote_executable(path: str) -> str:
    if not path:
        return path
    if " " in path or "\t" in path:
        return f"\"{path}\""
    return path


def _expand_path_pattern(pattern: str) -> List[str]:
    expanded = os.path.expandvars(os.path.expanduser(pattern))
    matches = glob.glob(expanded)
    found: List[str] = []
    for m in matches:
        p = Path(m)
        if not p.exists() or not p.is_file():
            continue
        try:
            found.append(str(p.resolve()))
        except Exception:
            found.append(str(p))
    return _uniq_strs(found)


def detect_verification_program_paths(
    programs: Optional[Sequence[str]] = None,
    *,
    max_matches_per_program: int = 5,
) -> Dict[str, Any]:
    """Detect common language/tool executables and suggest lint/test commands.
    
    Inputs:
    - Function parameters defined in the function signature.
    Output:
    - The function return value as defined by its signature/annotations.
    Example:
    ```python
    result = detect_verification_program_paths(...)
    ```
    """
    requested = programs if programs is not None else DEFAULT_VERIFICATION_PROGRAMS
    normalized_programs = [str(p).strip().lower() for p in requested if str(p).strip()]
    normalized_programs = _uniq_strs(normalized_programs)

    platform_name = platform.system()
    platform_patterns = KNOWN_PROGRAM_PATH_PATTERNS.get(platform_name, {})
    max_matches = max(1, int(max_matches_per_program))

    results: List[Dict[str, Any]] = []
    lint_suggestions: List[str] = []
    test_suggestions: List[str] = []

    for program in normalized_programs:
        aliases = PROGRAM_ALIASES.get(program, [program])
        path_hits: List[str] = []
        found_via_alias: Dict[str, str] = {}
        for alias in aliases:
            resolved = shutil.which(alias)
            if not resolved:
                continue
            resolved_path = str(Path(resolved).resolve())
            path_hits.append(resolved_path)
            found_via_alias[alias] = resolved_path

        known_hits: List[str] = []
        checked_patterns: List[str] = []
        for pattern in platform_patterns.get(program, []):
            expanded = os.path.expandvars(os.path.expanduser(pattern))
            checked_patterns.append(expanded)
            known_hits.extend(_expand_path_pattern(pattern))

        path_hits = _uniq_strs(path_hits)
        known_hits = _uniq_strs(known_hits)
        all_hits = _uniq_strs(path_hits + known_hits)[:max_matches]
        preferred_path = path_hits[0] if path_hits else (known_hits[0] if known_hits else None)

        found = bool(all_hits)
        source: Optional[str] = None
        if path_hits:
            source = "PATH"
        elif known_hits:
            source = "KNOWN_PATH"

        lint_cmds: List[str] = []
        test_cmds: List[str] = []
        if found and preferred_path:
            templates = PROGRAM_COMMAND_TEMPLATES.get(program, {})
            quoted_exe = _quote_executable(preferred_path)
            lint_cmds = [tpl.format(exe=quoted_exe) for tpl in templates.get("lint", [])]
            test_cmds = [tpl.format(exe=quoted_exe) for tpl in templates.get("test", [])]
            lint_suggestions.extend(lint_cmds)
            test_suggestions.extend(test_cmds)

        results.append(
            {
                "program": program,
                "aliases_checked": aliases,
                "found": found,
                "preferred_path": preferred_path,
                "all_paths": all_hits,
                "source": source,
                "found_via_alias": found_via_alias,
                "known_path_patterns_checked": checked_patterns,
                "suggested_lint_commands": lint_cmds,
                "suggested_test_commands": test_cmds,
            }
        )

    lint_suggestions = _uniq_strs(lint_suggestions)
    test_suggestions = _uniq_strs(test_suggestions)
    found_count = sum(1 for r in results if r.get("found"))
    return {
        "scanned_at": now_iso(),
        "platform": platform_name,
        "total_programs": len(results),
        "found_count": found_count,
        "missing_count": len(results) - found_count,
        "lint_command_suggestions": lint_suggestions,
        "test_command_suggestions": test_suggestions,
        "results": results,
    }


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
