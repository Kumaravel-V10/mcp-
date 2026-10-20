"""JWT Token Manager — auto-fetches and caches APIM auth tokens."""

from __future__ import annotations

import time
from typing import Optional

import httpx

from config import APIM_BASE_URL, APIM_TOKEN_TTL, API_REQUEST_TIMEOUT, logger


class TokenManager:
    """Manages JWT token lifecycle for APIM calls.

    Fetches token from POST {APIM_BASE_URL}/token, caches it for
    APIM_TOKEN_TTL seconds, and auto-refreshes on expiry or 401.
    """

    def __init__(self) -> None:
        self._jwt_token: Optional[str] = None
        self._token_fetched_at: float = 0.0

    def get_token(self) -> str:
        """Return a valid JWT token, fetching a new one if expired."""
        if self._is_expired():
            logger.info("JWT token expired or missing — fetching new token")
            self._fetch_token()
        return self._jwt_token or ""

    def invalidate(self) -> None:
        """Force re-fetch on next get_token() call."""
        self._jwt_token = None
        self._token_fetched_at = 0.0

    def _is_expired(self) -> bool:
        if self._jwt_token is None:
            return True
        return (time.time() - self._token_fetched_at) >= APIM_TOKEN_TTL

    def _fetch_token(self) -> None:
        """Fetch a new JWT from the APIM token endpoint."""
        url = f"{APIM_BASE_URL}/token"
        try:
            with httpx.Client(timeout=API_REQUEST_TIMEOUT) as client:
                response = client.post(
                    url,
                    json={},
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            # Try cookie first (Postman extracts from AuthToken cookie)
            token = response.cookies.get("AuthToken")

            # Fallback: check response body
            if not token:
                try:
                    body = response.json()
                    token = (
                        body.get("token")
                        or body.get("accessToken")
                        or body.get("jwt")
                        or body.get("JWT_Token")
                    )
                except Exception:
                    pass

            # Fallback: check Set-Cookie header directly
            if not token:
                set_cookie = response.headers.get("set-cookie", "")
                if "AuthToken=" in set_cookie:
                    for part in set_cookie.split(";"):
                        part = part.strip()
                        if part.startswith("AuthToken="):
                            token = part[len("AuthToken="):]
                            break

            if not token:
                raise RuntimeError(
                    f"Token endpoint {url} returned status {response.status_code} "
                    "but no token found in cookies, body, or Set-Cookie header."
                )

            self._jwt_token = token
            self._token_fetched_at = time.time()
            logger.info(f"JWT token acquired (TTL={APIM_TOKEN_TTL}s)")

        except httpx.HTTPStatusError as exc:
            logger.error(f"Token fetch failed: HTTP {exc.response.status_code}")
            raise RuntimeError(
                f"Token endpoint returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.ConnectError as exc:
            logger.error(f"Token fetch failed: cannot connect to {url}")
            raise RuntimeError(
                f"Cannot connect to token endpoint {url} — is APIM reachable?"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.error(f"Token fetch failed: timeout after {API_REQUEST_TIMEOUT}s")
            raise RuntimeError(
                f"Token endpoint {url} timed out after {API_REQUEST_TIMEOUT}s."
            ) from exc


# Module-level singleton
token_manager = TokenManager()
