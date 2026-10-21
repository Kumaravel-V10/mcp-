"""JWT Token Manager — auto-fetches and caches APIM auth tokens.

Two-phase flow (mirrors the Postman collection):
  1. POST {APIM_BASE_URL}/token          → JWT from AuthToken cookie
  2. POST {APIM_BASE_URL}/token/amadeus  → Amadeus token from response body

The token returned by get_token() is the raw JWT value (no "Bearer " prefix);
the APIM gateway expects it sent as-is in the Authorization header.
"""

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
        logger.info("JWT token invalidated — will re-fetch on next call")
        self._jwt_token = None
        self._token_fetched_at = 0.0

    def _is_expired(self) -> bool:
        if self._jwt_token is None:
            return True
        return (time.time() - self._token_fetched_at) >= APIM_TOKEN_TTL

    # ── Phase 1: fetch JWT from /token ──────────────────────────────────
    def _fetch_jwt(self) -> str:
        """POST /token and extract the JWT from cookies / body / Set-Cookie."""
        url = f"{APIM_BASE_URL}/token"
        logger.info(f"[TokenManager] Phase 1 — POST {url}")

        with httpx.Client(timeout=API_REQUEST_TIMEOUT) as client:
            response = client.post(
                url,
                json={"organization": "ay", "environment": "pdt"},
                headers={"Content-Type": "application/json"},
            )

        logger.info(
            f"[TokenManager] /token response: status={response.status_code}, "
            f"cookies={dict(response.cookies)}, "
            f"set-cookie={response.headers.get('set-cookie', '(none)')}"
        )
        response.raise_for_status()

        # 1) Try cookie first (Postman extracts from AuthToken cookie)
        token = response.cookies.get("AuthToken")

        # 2) Fallback: check response body
        if not token:
            try:
                body = response.json()
                logger.info(f"[TokenManager] /token body keys: {list(body.keys()) if isinstance(body, dict) else type(body)}")
                if isinstance(body, dict):
                    token = (
                        body.get("token")
                        or body.get("accessToken")
                        or body.get("jwt")
                        or body.get("JWT_Token")
                        or body.get("access_token")
                    )
            except Exception:
                pass

        # 3) Fallback: parse Set-Cookie header directly
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
                "but no token found in cookies, body, or Set-Cookie header. "
                f"Response body: {response.text[:300]}"
            )

        logger.info(f"[TokenManager] Phase 1 OK — JWT acquired (length={len(token)})")
        return token

    # ── Phase 2 (REQUIRED): exchange JWT for Amadeus token ─────────────
    def _fetch_amadeus_token(self, jwt: str) -> Optional[str]:
        """POST /token/amadeus with the JWT to get an Amadeus-scoped token.

        The APIM /shop/flights gateway validates the Amadeus token, NOT the
        Azure AD JWT. If this exchange fails, API calls will return 401.
        """
        url = f"{APIM_BASE_URL}/token/amadeus"
        logger.info(f"[TokenManager] Phase 2 — POST {url}")

        try:
            with httpx.Client(timeout=API_REQUEST_TIMEOUT) as client:
                response = client.post(
                    url,
                    json={"accessToken": jwt},
                    headers={"Content-Type": "application/json"},
                )

            logger.info(f"[TokenManager] /token/amadeus response: status={response.status_code}")

            if response.status_code >= 400:
                logger.info(
                    f"[TokenManager] /token/amadeus returned {response.status_code} "
                    f"— using organization JWT (matching Postman collection)"
                )
                return None

            body = response.json()
            amadeus_token = (
                body.get("amadeusToken")
                or body.get("token")
                or body.get("accessToken")
                or body.get("access_token")
            )

            if amadeus_token:
                logger.info(f"[TokenManager] Phase 2 OK — Amadeus token acquired (length={len(amadeus_token)})")
                return amadeus_token

            logger.warning(f"[TokenManager] /token/amadeus body has no token field: {list(body.keys())}")
            return None

        except Exception as exc:
            logger.warning(f"[TokenManager] Phase 2 skipped — {exc}")
            return None

    # ── Main fetch orchestrator ─────────────────────────────────────────
    def _fetch_token(self) -> None:
        """Fetch a new token using the two-phase flow."""
        try:
            jwt = self._fetch_jwt()

            # Phase 2: try to exchange for Amadeus token (some APIM setups need it)
            amadeus_token = self._fetch_amadeus_token(jwt)

            # Use the Amadeus token if available, otherwise use the raw JWT
            self._jwt_token = amadeus_token or jwt
            self._token_fetched_at = time.time()

            logger.info(
                f"[TokenManager] Token ready (type={'amadeus' if amadeus_token else 'jwt'}, "
                f"TTL={APIM_TOKEN_TTL}s)"
            )

        except httpx.HTTPStatusError as exc:
            logger.error(f"Token fetch failed: HTTP {exc.response.status_code}")
            raise RuntimeError(
                f"Token endpoint returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.ConnectError as exc:
            logger.error(f"Token fetch failed: cannot connect to {APIM_BASE_URL}/token")
            raise RuntimeError(
                f"Cannot connect to token endpoint {APIM_BASE_URL}/token — is APIM reachable?"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.error(f"Token fetch failed: timeout after {API_REQUEST_TIMEOUT}s")
            raise RuntimeError(
                f"Token endpoint timed out after {API_REQUEST_TIMEOUT}s."
            ) from exc


# Module-level singleton
token_manager = TokenManager()
