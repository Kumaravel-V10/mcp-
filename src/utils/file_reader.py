"""Safe file reading utilities with path traversal protection."""

from __future__ import annotations

import os
from typing import Optional

from config import ALLOWED_FILE_ROOT, WORKSPACE_ROOT


def safe_read_file(file_path: str) -> str:
    """Read a file within the workspace root. Prevents path traversal."""
    resolved = os.path.normpath(os.path.join(WORKSPACE_ROOT, file_path))
    allowed = os.path.normpath(ALLOWED_FILE_ROOT)

    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise PermissionError("Access denied: path is outside workspace root")

    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def safe_read_lines(file_path: str, start: int = 1, end: int = 100) -> dict:
    """Read specific line range from a file (1-indexed)."""
    resolved = os.path.normpath(os.path.join(WORKSPACE_ROOT, file_path))
    allowed = os.path.normpath(ALLOWED_FILE_ROOT)

    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return {"error": "Access denied: path is outside workspace root"}

    if not os.path.isfile(resolved):
        return {"error": f"File not found: {file_path}"}

    start = max(1, start)
    end = min(end, start + 499)  # cap at 500 lines

    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total = len(lines)
    selected = lines[start - 1: end]

    return {
        "path": file_path,
        "total_lines": total,
        "start_line": start,
        "end_line": min(end, total),
        "content": "".join(selected),
    }


def path_exists(file_path: str) -> bool:
    """Check if a path exists within the workspace."""
    resolved = os.path.normpath(os.path.join(WORKSPACE_ROOT, file_path))
    allowed = os.path.normpath(ALLOWED_FILE_ROOT)
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return False
    return os.path.exists(resolved)


def list_files(
    dir_path: str,
    extensions: Optional[list[str]] = None,
    recursive: bool = False,
) -> list[str]:
    """List files in a directory within the workspace."""
    resolved = os.path.normpath(os.path.join(WORKSPACE_ROOT, dir_path))
    allowed = os.path.normpath(ALLOWED_FILE_ROOT)

    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return []

    if not os.path.isdir(resolved):
        return []

    results: list[str] = []

    if recursive:
        for root, _dirs, files in os.walk(resolved):
            for fname in files:
                if extensions and not any(fname.endswith(ext) for ext in extensions):
                    continue
                rel = os.path.relpath(os.path.join(root, fname), WORKSPACE_ROOT)
                results.append(rel.replace("\\", "/"))
    else:
        for fname in os.listdir(resolved):
            full = os.path.join(resolved, fname)
            if os.path.isfile(full):
                if extensions and not any(fname.endswith(ext) for ext in extensions):
                    continue
                rel = os.path.relpath(full, WORKSPACE_ROOT)
                results.append(rel.replace("\\", "/"))

    return sorted(results)
