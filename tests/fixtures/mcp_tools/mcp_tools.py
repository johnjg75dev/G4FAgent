from __future__ import annotations

import os
from pathlib import Path

from g4fagent.tools import ToolCategory, ToolResult, tool


def _ensure_rel_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        raise ValueError(f"Absolute paths not allowed: {path}")
    norm = Path(os.path.normpath(str(p)))
    if str(norm).startswith(".."):
        raise ValueError(f"Path escapes project root: {path}")
    return norm


class MCPTools(ToolCategory):
    @tool("mcp_ping")
    def mcp_ping(self) -> str:
        return "pong"

    @tool("mcp_echo")
    def mcp_echo(self, text: str = "") -> str:
        return text

    @tool("mcp_note_write")
    def mcp_note_write(self, path: str, content: str = "") -> ToolResult:
        rel = _ensure_rel_path(path)
        abs_path = (self.root / rel).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        return ToolResult(True, f"Wrote {path} ({len(content)} chars)")

