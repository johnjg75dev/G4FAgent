from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, List, Optional

from .registry import ToolCategory, ToolResult, tool


def _pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _ensure_rel_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        raise ValueError(f"Absolute paths not allowed: {path}")
    norm = Path(os.path.normpath(str(p)))
    if str(norm).startswith(".."):
        raise ValueError(f"Path escapes project root: {path}")
    return norm


def _apply_unified_diff(old_lines: List[str], diff_text: str) -> Optional[List[str]]:
    lines = diff_text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = [ln for ln in lines if not ln.strip().startswith("```")]

    i = 0
    while i < len(lines) and not lines[i].startswith("@@"):
        i += 1
    if i >= len(lines):
        return None

    new_lines: List[str] = []
    old_idx = 0
    hunk_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")

    while i < len(lines):
        m = hunk_re.match(lines[i])
        if not m:
            i += 1
            continue

        old_start = int(m.group(1)) - 1
        i += 1

        if old_start < old_idx or old_start > len(old_lines):
            return None
        new_lines.extend(old_lines[old_idx:old_start])
        old_idx = old_start

        while i < len(lines) and not lines[i].startswith("@@"):
            ln = lines[i]
            if ln.startswith(" "):
                ctx = ln[1:] + "\n"
                if old_idx >= len(old_lines) or old_lines[old_idx] != ctx:
                    return None
                new_lines.append(ctx)
                old_idx += 1
            elif ln.startswith("-"):
                rem = ln[1:] + "\n"
                if old_idx >= len(old_lines) or old_lines[old_idx] != rem:
                    return None
                old_idx += 1
            elif ln.startswith("+"):
                add = ln[1:] + "\n"
                new_lines.append(add)
            elif ln.startswith("\\"):
                pass
            else:
                return None
            i += 1

    new_lines.extend(old_lines[old_idx:])
    return new_lines


class Files(ToolCategory):
    @tool("list_dir")
    def list_dir(self, path: str = ".") -> ToolResult:
        try:
            abs_path = self._abs(path)
            if not abs_path.exists():
                return ToolResult(False, f"Path not found: {path}")
            if not abs_path.is_dir():
                return ToolResult(False, f"Not a directory: {path}")
            items = []
            for child in sorted(abs_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                items.append({"name": child.name, "type": "dir" if child.is_dir() else "file"})
            return ToolResult(True, _pretty_json(items), items)
        except Exception as e:
            return ToolResult(False, f"list_dir error: {e}")

    @tool("read_file")
    def read_file(self, path: str) -> ToolResult:
        try:
            abs_path = self._abs(path)
            if not abs_path.exists():
                return ToolResult(False, f"File not found: {path}")
            if not abs_path.is_file():
                return ToolResult(False, f"Not a file: {path}")
            txt = abs_path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(True, txt, txt)
        except Exception as e:
            return ToolResult(False, f"read_file error: {e}")

    @tool("write_file")
    def write_file(self, path: str, content: str = "", overwrite: bool = True) -> ToolResult:
        try:
            abs_path = self._abs(path)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            if abs_path.exists() and not overwrite:
                return ToolResult(False, f"Refused overwrite: {path}")
            abs_path.write_text(content, encoding="utf-8")
            return ToolResult(True, f"Wrote {path} ({len(content)} chars)")
        except Exception as e:
            return ToolResult(False, f"write_file error: {e}")

    @tool("delete_file")
    def delete_file(self, path: str) -> ToolResult:
        try:
            abs_path = self._abs(path)
            if not abs_path.exists():
                return ToolResult(False, f"Not found: {path}")
            if abs_path.is_dir():
                return ToolResult(False, f"Refusing to delete directory via delete_file: {path}")
            abs_path.unlink()
            return ToolResult(True, f"Deleted {path}")
        except Exception as e:
            return ToolResult(False, f"delete_file error: {e}")

    @tool("apply_patch")
    def apply_patch(self, path: str, diff: str = "") -> ToolResult:
        try:
            abs_path = self._abs(path)
            if not abs_path.exists() or not abs_path.is_file():
                return ToolResult(False, f"File not found for patch: {path}")

            old = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            patched = _apply_unified_diff(old, diff)
            if patched is None:
                return ToolResult(False, "Failed to apply patch (hunks did not match). Ask model to rebase patch.")
            abs_path.write_text("".join(patched), encoding="utf-8")
            return ToolResult(True, f"Patched {path}")
        except Exception as e:
            return ToolResult(False, f"apply_patch error: {e}")

    def _abs(self, path: str) -> Path:
        rel_path = _ensure_rel_path(path)
        return (self.root / rel_path).resolve()
