"""HTTP client for calling live SC microservice APIs (GraphQL + REST)."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx

from config import API_REQUEST_TIMEOUT, ALLOW_MUTATIONS, get_service_base_url


# ═══════════════════════════════════════════════════════════════════════
# GraphQL client
# ═══════════════════════════════════════════════════════════════════════

def call_graphql(
    service_name: str,
    query: str,
    variables: Optional[dict[str, Any]] = None,
    allow_mutation: bool = False,
) -> dict[str, Any]:
    """Send a GraphQL request to a service and return the parsed response.

    Args:
        service_name: Canonical service name (e.g. 'SC-API-SearchPanel').
        query: GraphQL query/mutation string.
        variables: Optional variables dict.
        allow_mutation: Override to allow mutations even if ALLOW_MUTATIONS is False.

    Returns:
        Dict with keys: service, url, status, duration_ms, data, errors.
    """
    # Safety: block mutations unless explicitly allowed
    if not allow_mutation and not ALLOW_MUTATIONS:
        query_trimmed = query.strip().lower()
        if query_trimmed.startswith("mutation"):
            return {
                "service": service_name,
                "error": "Mutations are blocked by default. Set ALLOW_MUTATIONS=true or pass allow_mutation=true.",
            }

    base_url = get_service_base_url(service_name)
    if not base_url:
        return {"service": service_name, "error": f"No base URL configured for '{service_name}'."}

    url = f"{base_url}/graphql"
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=API_REQUEST_TIMEOUT) as client:
            response = client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = response.text

        return {
            "service": service_name,
            "url": url,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "data": body.get("data") if isinstance(body, dict) else None,
            "errors": body.get("errors") if isinstance(body, dict) else None,
            "raw_body": body if not isinstance(body, dict) else None,
        }

    except httpx.TimeoutException:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"service": service_name, "url": url, "error": "Request timed out.", "duration_ms": duration_ms}
    except httpx.ConnectError:
        return {"service": service_name, "url": url, "error": f"Connection refused — is {service_name} running on {base_url}?"}
    except httpx.HTTPError as exc:
        return {"service": service_name, "url": url, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════
# REST client
# ═══════════════════════════════════════════════════════════════════════

def call_rest(
    service_name: str,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    allow_mutation: bool = False,
) -> dict[str, Any]:
    """Send a REST request to a service and return the parsed response.

    Args:
        service_name: Canonical service name (e.g. 'SC-API-Token').
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        path: Path relative to service base URL (e.g. '/api/token').
        body: Optional JSON body for POST/PUT/PATCH.
        headers: Optional extra headers.
        allow_mutation: Override to allow write methods even if ALLOW_MUTATIONS is False.

    Returns:
        Dict with keys: service, url, method, status, duration_ms, data, error.
    """
    method_upper = method.upper()
    write_methods = {"POST", "PUT", "DELETE", "PATCH"}

    if not allow_mutation and not ALLOW_MUTATIONS and method_upper in write_methods:
        return {
            "service": service_name,
            "error": f"Write method '{method_upper}' blocked. Set ALLOW_MUTATIONS=true or pass allow_mutation=true.",
        }

    base_url = get_service_base_url(service_name)
    if not base_url:
        return {"service": service_name, "error": f"No base URL configured for '{service_name}'."}

    # Ensure path starts with /
    if path and not path.startswith("/"):
        path = "/" + path

    url = f"{base_url}{path}"

    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=API_REQUEST_TIMEOUT) as client:
            response = client.request(
                method=method_upper,
                url=url,
                json=body if method_upper in write_methods else None,
                params=body if method_upper == "GET" and body else None,
                headers=req_headers,
            )
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        try:
            resp_body = response.json()
        except (json.JSONDecodeError, ValueError):
            resp_body = response.text

        return {
            "service": service_name,
            "url": url,
            "method": method_upper,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "data": resp_body,
        }

    except httpx.TimeoutException:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"service": service_name, "url": url, "method": method_upper, "error": "Request timed out.", "duration_ms": duration_ms}
    except httpx.ConnectError:
        return {"service": service_name, "url": url, "method": method_upper, "error": f"Connection refused — is {service_name} running on {base_url}?"}
    except httpx.HTTPError as exc:
        return {"service": service_name, "url": url, "method": method_upper, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════
# Introspection helper
# ═══════════════════════════════════════════════════════════════════════

_INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      name
      kind
      fields {
        name
        type { name kind ofType { name kind } }
      }
    }
  }
}
"""


def introspect_service(service_name: str) -> dict[str, Any]:
    """Run a GraphQL introspection query against a live service.

    Returns the schema types/fields or an error dict.
    """
    return call_graphql(service_name, _INTROSPECTION_QUERY, allow_mutation=False)


# ═══════════════════════════════════════════════════════════════════════
# Health probe
# ═══════════════════════════════════════════════════════════════════════

def check_service_health(service_name: str) -> dict[str, Any]:
    """Quick health/connectivity check for a service.

    Tries GET / or GET /health. Returns reachable status + latency.
    """
    base_url = get_service_base_url(service_name)
    if not base_url:
        return {"service": service_name, "reachable": False, "error": "No base URL configured."}

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(f"{base_url}/health")
            if response.status_code == 404:
                response = client.get(base_url)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "service": service_name,
            "reachable": response.status_code < 500,
            "status": response.status_code,
            "latency_ms": duration_ms,
        }
    except (httpx.ConnectError, httpx.TimeoutException):
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"service": service_name, "reachable": False, "latency_ms": duration_ms, "error": "Connection failed."}
    except httpx.HTTPError as exc:
        return {"service": service_name, "reachable": False, "error": str(exc)}
