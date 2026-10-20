"""Utilities for parsing GraphQL typedefs from service source files."""

from __future__ import annotations

import os
import re
from typing import Optional

from config import WORKSPACE_ROOT


def get_graphql_typedefs(service_folder: str) -> str:
    """Read and merge all GraphQL typedef files from a service's src/modules/ directory.

    Looks for:
    - .graphql files
    - TypeScript files containing gql`` template literals or typeDefs exports
    """
    src_modules = os.path.join(WORKSPACE_ROOT, service_folder, "src", "modules")
    if not os.path.isdir(src_modules):
        src_modules = os.path.join(WORKSPACE_ROOT, service_folder, "src")
        if not os.path.isdir(src_modules):
            return ""

    typedefs: list[str] = []

    for root, _dirs, files in os.walk(src_modules):
        for fname in sorted(files):
            full_path = os.path.join(root, fname)

            if fname.endswith(".graphql") or fname.endswith(".gql"):
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                if content:
                    typedefs.append(f"# --- {os.path.relpath(full_path, WORKSPACE_ROOT)} ---\n{content}")

            elif fname.endswith(".ts") and ("typedef" in fname.lower() or "schema" in fname.lower()):
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                # Extract gql`` or typeDefs string
                extracted = _extract_gql_from_ts(content)
                if extracted:
                    typedefs.append(
                        f"# --- {os.path.relpath(full_path, WORKSPACE_ROOT)} ---\n{extracted}"
                    )

    return "\n\n".join(typedefs)


def get_graphql_resolvers(service_folder: str) -> list[dict]:
    """Extract resolver function names from a service."""
    src_modules = os.path.join(WORKSPACE_ROOT, service_folder, "src", "modules")
    if not os.path.isdir(src_modules):
        src_modules = os.path.join(WORKSPACE_ROOT, service_folder, "src")
        if not os.path.isdir(src_modules):
            return []

    resolvers: list[dict] = []

    for root, _dirs, files in os.walk(src_modules):
        for fname in sorted(files):
            if "resolver" not in fname.lower():
                continue
            if not fname.endswith(".ts"):
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, WORKSPACE_ROOT).replace("\\", "/")

            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Match exported resolver functions/objects
            # Pattern: Query: { functionName, ... } or Mutation: { functionName, ... }
            for match in re.finditer(r"(Query|Mutation)\s*:\s*\{([^}]+)\}", content):
                resolver_type = match.group(1)
                body = match.group(2)
                names = re.findall(r"(\w+)\s*[:(,]", body)
                for name in names:
                    if name not in ("async", "await", "return", "const", "let", "var"):
                        resolvers.append({
                            "name": name,
                            "type": resolver_type,
                            "file": rel_path,
                        })

            # Match standalone exported async functions that look like resolvers
            for match in re.finditer(
                r"export\s+(?:const|async\s+function)\s+(\w+)", content
            ):
                name = match.group(1)
                if name not in [r["name"] for r in resolvers]:
                    resolvers.append({
                        "name": name,
                        "type": "export",
                        "file": rel_path,
                    })

    return resolvers


def _extract_gql_from_ts(content: str) -> Optional[str]:
    """Extract GraphQL SDL from TypeScript template literals."""
    # Match gql`...` or /* GraphQL */ `...`
    patterns = [
        r'gql\s*`([\s\S]*?)`',
        r'typeDefs\s*=\s*`([\s\S]*?)`',
        r'typeDefs\s*=\s*"([\s\S]*?)"',
        r'#graphql\s*`([\s\S]*?)`',
    ]
    results = []
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            text = match.group(1).strip()
            if text and ("type " in text or "input " in text or "query " in text.lower()):
                results.append(text)

    return "\n\n".join(results) if results else None
