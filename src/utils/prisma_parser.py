"""Prisma schema parsing utilities."""

from __future__ import annotations

import os
import re

from config import WORKSPACE_ROOT


def get_prisma_schema(service_folder: str) -> str:
    """Read the prisma/schema.prisma file for a service."""
    schema_path = os.path.join(WORKSPACE_ROOT, service_folder, "prisma", "schema.prisma")
    if not os.path.isfile(schema_path):
        return ""
    with open(schema_path, "r", encoding="utf-8") as f:
        return f.read()


def parse_prisma_models(service_folder: str) -> list[dict]:
    """Parse prisma schema and extract model definitions."""
    schema = get_prisma_schema(service_folder)
    if not schema:
        return []

    models: list[dict] = []
    # Match model blocks
    for match in re.finditer(r"model\s+(\w+)\s*\{([^}]+)\}", schema):
        model_name = match.group(1)
        body = match.group(2)

        fields: list[dict] = []
        for line in body.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("@@"):
                continue
            # Parse field: name Type @attributes
            field_match = re.match(r"(\w+)\s+(\S+)(.*)", line)
            if field_match:
                fname = field_match.group(1)
                ftype = field_match.group(2)
                attrs = field_match.group(3).strip()
                fields.append({
                    "name": fname,
                    "type": ftype,
                    "attributes": attrs if attrs else None,
                })

        models.append({
            "name": model_name,
            "fields": fields,
            "field_count": len(fields),
        })

    return models


def get_prisma_enums(service_folder: str) -> list[dict]:
    """Extract enum definitions from prisma schema."""
    schema = get_prisma_schema(service_folder)
    if not schema:
        return []

    enums: list[dict] = []
    for match in re.finditer(r"enum\s+(\w+)\s*\{([^}]+)\}", schema):
        enum_name = match.group(1)
        values = [v.strip() for v in match.group(2).strip().split("\n") if v.strip() and not v.strip().startswith("//")]
        enums.append({"name": enum_name, "values": values})

    return enums
