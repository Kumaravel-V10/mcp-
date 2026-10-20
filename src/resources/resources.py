"""MCP Resources — structured data endpoints exposed to AI clients."""

from __future__ import annotations

import json
import os

from config import WORKSPACE_ROOT, README_PATH, ARCHITECTURE_DIAGRAM_PATH
from src.registry.services import SERVICE_REGISTRY, list_all_services
from src.utils.prisma_parser import get_prisma_schema, parse_prisma_models
from src.utils.graphql_parser import get_graphql_typedefs


def resource_architecture() -> str:
    """Full architecture diagram (ARCHITECTURE-DIAGRAM.md content)."""
    if os.path.isfile(ARCHITECTURE_DIAGRAM_PATH):
        with open(ARCHITECTURE_DIAGRAM_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "ARCHITECTURE-DIAGRAM.md not found."


def resource_readme() -> str:
    """Project README documentation."""
    if os.path.isfile(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "README.md not found."


def resource_services_registry() -> str:
    """Complete service registry as JSON."""
    return json.dumps(list_all_services(), indent=2)


def resource_service_detail(service_name: str) -> str:
    """Per-service detail: metadata + prisma models + graphql types."""
    from src.registry.services import find_service
    svc = find_service(service_name)
    if not svc:
        return json.dumps({"error": f"Service '{service_name}' not found."})

    result: dict = {
        "name": svc.name,
        "folder": svc.folder,
        "type": svc.service_type,
        "tech": svc.tech,
        "description": svc.description,
        "port": svc.port,
    }

    if svc.has_prisma:
        result["prisma_models"] = parse_prisma_models(svc.folder)

    if svc.has_graphql:
        result["graphql_typedefs"] = get_graphql_typedefs(svc.folder)[:5000]

    return json.dumps(result, indent=2)


def resource_feature_flags() -> str:
    """Feature flag mappings from SC-API-App-Config."""
    flag_path = os.path.join(WORKSPACE_ROOT, "SC-API-App-Config", "default-feature-mapping.json")
    if os.path.isfile(flag_path):
        with open(flag_path, "r", encoding="utf-8") as f:
            return f.read()
    return json.dumps({"error": "default-feature-mapping.json not found."})


def resource_role_mapping() -> str:
    """Role-feature mapping from SC-API-App-Config."""
    role_path = os.path.join(WORKSPACE_ROOT, "SC-API-App-Config", "role-feature-mapping.json")
    if os.path.isfile(role_path):
        with open(role_path, "r", encoding="utf-8") as f:
            return f.read()
    return json.dumps({"error": "role-feature-mapping.json not found."})


def resource_prisma_schema(service_name: str) -> str:
    """Raw Prisma schema for a specific service."""
    from src.registry.services import find_service
    svc = find_service(service_name)
    if not svc:
        return f"Service '{service_name}' not found."
    if not svc.has_prisma:
        return f"Service '{svc.name}' does not use Prisma."
    schema = get_prisma_schema(svc.folder)
    return schema if schema else f"Prisma schema not found for '{svc.name}'."


def resource_graphql_schema(service_name: str) -> str:
    """Merged GraphQL SDL for a specific service."""
    from src.registry.services import find_service
    svc = find_service(service_name)
    if not svc:
        return f"Service '{service_name}' not found."
    if not svc.has_graphql:
        return f"Service '{svc.name}' does not use GraphQL."
    typedefs = get_graphql_typedefs(svc.folder)
    return typedefs if typedefs else f"No GraphQL typedefs found for '{svc.name}'."
