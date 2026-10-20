"""APIM HTTP client — calls APIM GraphQL endpoints with auto-injected JWT auth.

Token flow (mirrors the Postman collection):
  1. TokenManager fetches JWT from POST /token  (cookie or body)
  2. Optionally exchanges it for an Amadeus token via POST /token/amadeus
  3. This client injects the token as ``Authorization: <token>`` (NO "Bearer "
     prefix — the APIM gateway expects the raw JWT value, matching Postman).

On a 401 the client invalidates the cached token and retries once.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import httpx

from config import APIM_BASE_URL, API_REQUEST_TIMEOUT, logger
from src.utils.token_manager import token_manager


def call_apim_graphql(
    endpoint_path: str,
    query: str,
    variables: Optional[dict[str, Any]] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Send a GraphQL request to an APIM endpoint with auto JWT auth.

    Automatically fetches/caches the JWT token and injects it as the
    Authorization header. Retries once on 401 after token refresh.

    Args:
        endpoint_path: Path relative to APIM base URL (e.g. '/shop/flights').
        query: GraphQL query or mutation string.
        variables: Optional variables dict.
        extra_headers: Optional additional headers.

    Returns:
        Dict with keys: endpoint, url, status, duration_ms, data, errors.
    """
    url = f"{APIM_BASE_URL}{endpoint_path}"

    for attempt in range(2):
        # ── Step 1: acquire a valid token ────────────────────────────────
        try:
            jwt = token_manager.get_token()
        except RuntimeError as exc:
            logger.error(f"[APIM] Token acquisition failed for {endpoint_path}: {exc}")
            return {"endpoint": endpoint_path, "url": url, "error": f"Token error: {exc}"}

        if not jwt:
            logger.error(f"[APIM] Empty token for {endpoint_path} — cannot call API")
            return {"endpoint": endpoint_path, "url": url, "error": "Token is empty after fetch."}

        # ── Step 2: build headers (matching Postman) ─────────────────────
        # Postman sends:  Authorization: {{JWT_Token}}   (raw, NO "Bearer " prefix)
        #                 X-Trace-Id: <unique-id>
        trace_id = uuid.uuid4().hex[:18]
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": jwt,
            "X-Trace-Id": trace_id,
        }
        if extra_headers:
            headers.update(extra_headers)

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        logger.info(
            f"[APIM] {endpoint_path} attempt {attempt + 1}/2 — "
            f"token_len={len(jwt)}, trace={trace_id}"
        )

        # ── Step 3: make the request ────────────────────────────────────
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=API_REQUEST_TIMEOUT) as client:
                response = client.post(url, json=payload, headers=headers)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            # On 401, invalidate token and retry once
            if response.status_code == 401 and attempt == 0:
                logger.warning(
                    f"[APIM] 401 on {endpoint_path} (attempt 1) — "
                    f"invalidating token and retrying. "
                    f"Body: {response.text[:300]}"
                )
                token_manager.invalidate()
                continue

            try:
                body = response.json()
            except (json.JSONDecodeError, ValueError):
                body = response.text

            result = {
                "endpoint": endpoint_path,
                "url": url,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "data": body.get("data") if isinstance(body, dict) else None,
                "errors": body.get("errors") if isinstance(body, dict) else None,
                "raw_body": body if not isinstance(body, dict) else None,
            }

            if response.status_code >= 400:
                logger.error(
                    f"[APIM] {endpoint_path} returned HTTP {response.status_code} "
                    f"in {duration_ms}ms — {json.dumps(result.get('errors') or result.get('raw_body', ''))[:300]}"
                )
            else:
                logger.info(f"[APIM] {endpoint_path} → {response.status_code} in {duration_ms}ms")

            return result

        except httpx.TimeoutException:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(f"[APIM] {endpoint_path} timed out after {API_REQUEST_TIMEOUT}s")
            return {
                "endpoint": endpoint_path,
                "url": url,
                "error": f"Request timed out after {API_REQUEST_TIMEOUT}s.",
                "duration_ms": duration_ms,
            }
        except httpx.ConnectError:
            logger.error(f"[APIM] Connection refused: {APIM_BASE_URL}")
            return {
                "endpoint": endpoint_path,
                "url": url,
                "error": f"Connection refused — is APIM reachable at {APIM_BASE_URL}?",
            }
        except httpx.HTTPError as exc:
            return {"endpoint": endpoint_path, "url": url, "error": str(exc)}

    # Should not reach here, but just in case
    return {"endpoint": endpoint_path, "url": url, "error": "Token refresh failed after retry."}
