"""Codebase search utility using recursive file scanning."""

from __future__ import annotations

import os
import re
from typing import Optional

from config import WORKSPACE_ROOT


def search_codebase(
    query: str,
    scope: Optional[str] = None,
    max_results: int = 30,
    extensions: Optional[list[str]] = None,
) -> list[dict]:
    """Search across all source files for a query string.

    Args:
        query: Text or regex pattern to search for.
        scope: Optional subfolder to limit search (e.g. 'SC-API-Create-Cart').
        max_results: Maximum number of matches to return.
        extensions: File extensions to include (default: .ts, .tsx, .graphql, .prisma, .json).
    """
    if extensions is None:
        extensions = [".ts", ".tsx", ".graphql", ".gql", ".prisma", ".json", ".py"]

    search_root = WORKSPACE_ROOT
    if scope:
        search_root = os.path.join(WORKSPACE_ROOT, scope)
        if not os.path.isdir(search_root):
            return []

    results: list[dict] = []
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        # Fallback to literal match if regex is invalid
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    skip_dirs = {"node_modules", ".git", "dist", "build", ".next", "__pycache__", "coverage"}

    for root, dirs, files in os.walk(search_root):
        # Skip unwanted directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for fname in files:
            if not any(fname.endswith(ext) for ext in extensions):
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, WORKSPACE_ROOT).replace("\\", "/")

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except (OSError, IOError):
                continue

            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    results.append({
                        "file": rel_path,
                        "line": i,
                        "content": line.rstrip()[:200],
                    })
                    if len(results) >= max_results:
                        return results

    return results


def find_related_tests(module_path: str) -> list[str]:
    """Given a source file or module path, find related test files."""
    # Normalize path
    module_path = module_path.replace("\\", "/")

    # Extract the key parts: service folder + module name
    parts = module_path.split("/")
    service_folder = parts[0] if parts else ""
    module_name = ""

    # Try to find the module/file name
    for part in reversed(parts):
        if part and part != "src" and part != "modules":
            module_name = part.replace(".ts", "").replace(".tsx", "")
            break

    test_files: list[str] = []

    # Search in the service's test/ directory
    test_dir = os.path.join(WORKSPACE_ROOT, service_folder, "test")
    if os.path.isdir(test_dir):
        for root, _dirs, files in os.walk(test_dir):
            for fname in files:
                if module_name.lower() in fname.lower():
                    rel = os.path.relpath(os.path.join(root, fname), WORKSPACE_ROOT)
                    test_files.append(rel.replace("\\", "/"))

    # Also check if there's a __tests__ directory or .test. / .spec. files nearby
    src_dir = os.path.join(WORKSPACE_ROOT, service_folder, "src")
    if os.path.isdir(src_dir):
        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                if (".test." in fname or ".spec." in fname) and module_name.lower() in fname.lower():
                    rel = os.path.relpath(os.path.join(root, fname), WORKSPACE_ROOT)
                    test_files.append(rel.replace("\\", "/"))

    return sorted(set(test_files))
