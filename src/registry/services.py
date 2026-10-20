"""Service registry — central metadata for all SC microservices."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from config import WORKSPACE_ROOT


@dataclass
class ServiceInfo:
    name: str
    folder: str
    service_type: str  # "frontend" or "backend"
    tech: list[str] = field(default_factory=list)
    description: str = ""
    has_prisma: bool = False
    has_graphql: bool = False
    port: Optional[int] = None

    @property
    def path(self) -> str:
        return os.path.join(WORKSPACE_ROOT, self.folder)

    @property
    def exists(self) -> bool:
        return os.path.isdir(self.path)

    @property
    def prisma_schema_path(self) -> str:
        return os.path.join(self.path, "prisma", "schema.prisma")

    @property
    def src_path(self) -> str:
        return os.path.join(self.path, "src")


SERVICE_REGISTRY: list[ServiceInfo] = [
    ServiceInfo(
        name="SC-UI-ServiceCenterMain",
        folder="SC-UI-ServiceCenterMain",
        service_type="frontend",
        tech=["Next.js 14", "React 18", "TypeScript", "Apollo Client", "Zustand", "NextAuth"],
        description="Main flight booking UI for airline service center agents",
        has_prisma=False,
        has_graphql=False,
        port=3000,
    ),
    ServiceInfo(
        name="SC-API-Token",
        folder="SC-API-Token-main",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Express", "REST"],
        description="OAuth token management & authentication service",
        has_prisma=True,
        has_graphql=False,
        port=7071,
    ),
    ServiceInfo(
        name="SC-API-SearchPanel",
        folder="SC-API-SearchPanel",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Dropdown reference data (airlines, airports, cabins, passenger types)",
        has_prisma=True,
        has_graphql=True,
        port=7072,
    ),
    ServiceInfo(
        name="SC-API-App-Config",
        folder="SC-API-App-Config",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Admin console configuration management (features, themes, roles, currencies)",
        has_prisma=True,
        has_graphql=True,
        port=7073,
    ),
    ServiceInfo(
        name="SC-API-Create-Cart",
        folder="SC-API-Create-Cart",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Cart initialization & SKU validation",
        has_prisma=True,
        has_graphql=True,
        port=7074,
    ),
    ServiceInfo(
        name="SC-API-Retrieve-Cart",
        folder="SC-API-Retrieve-Cart",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Cart state retrieval",
        has_prisma=True,
        has_graphql=True,
        port=7075,
    ),
    ServiceInfo(
        name="SC-API-Checkout-Passengers",
        folder="SC-API-Checkout-Passengers-main",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Passenger form validation & PII collection",
        has_prisma=True,
        has_graphql=True,
        port=7076,
    ),
    ServiceInfo(
        name="SC-API-Checkout-Confirm",
        folder="SC-API-Checkout-Confirm",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Payment processing & booking confirmation (PNR generation)",
        has_prisma=True,
        has_graphql=True,
        port=7077,
    ),
    ServiceInfo(
        name="SC-API-Seat-Map",
        folder="SC-API-Seat-Map",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Seat availability & pricing visualization",
        has_prisma=True,
        has_graphql=True,
        port=7078,
    ),
    ServiceInfo(
        name="SC-API-Seat-Services",
        folder="SC-API-Seat-Services",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Seat selection & ancillary services management",
        has_prisma=True,
        has_graphql=True,
        port=7079,
    ),
    ServiceInfo(
        name="SC-API-Services",
        folder="SC-API-Services",
        service_type="backend",
        tech=["Azure Functions", "TypeScript", "Apollo Server", "GraphQL", "Prisma"],
        description="Ancillary service catalog (baggage, meals, WiFi, etc.)",
        has_prisma=True,
        has_graphql=True,
        port=7080,
    ),
]


def find_service(query: str) -> Optional[ServiceInfo]:
    """Find a service by name (case-insensitive, partial match)."""
    q = query.lower().replace("-", "").replace("_", "").replace(" ", "")
    for svc in SERVICE_REGISTRY:
        name_norm = svc.name.lower().replace("-", "").replace("_", "").replace(" ", "")
        if q in name_norm or name_norm in q:
            return svc
    return None


def list_all_services() -> list[dict]:
    """Return all services as serializable dicts."""
    return [
        {
            "name": s.name,
            "folder": s.folder,
            "type": s.service_type,
            "tech": s.tech,
            "description": s.description,
            "has_prisma": s.has_prisma,
            "has_graphql": s.has_graphql,
            "port": s.port,
            "exists_on_disk": s.exists,
        }
        for s in SERVICE_REGISTRY
    ]
