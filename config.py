"""SC-MCP-SERVER configuration — Create Booking Agent."""

import logging
import os
from dotenv import load_dotenv

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Server identity
SERVER_NAME = "sc-mcp-server"
SERVER_VERSION = "2.1.0"
SERVER_PORT = int(os.environ.get("MCP_PORT", "3100"))
SERVER_HOST = os.environ.get("MCP_HOST", "127.0.0.1")

# Transport: "stdio" or "sse"
TRANSPORT_MODE = os.environ.get("MCP_TRANSPORT", "stdio")

# Security — Bearer token auth for HTTP transport
MCP_API_KEY: str = os.environ.get("MCP_API_KEY", "")

# ─── Safety — Mutation Guard ───────────────────────────────────────
# Set to "true" to allow irreversible operations (confirm_booking).
# Default "false" blocks PNR creation to prevent accidental bookings.
ALLOW_MUTATIONS: bool = os.environ.get("ALLOW_MUTATIONS", "false").lower() == "true"

# ─── APIM (Booking Agent) ──────────────────────────────────────────
APIM_BASE_URL: str = os.environ.get(
    "APIM_BASE_URL",
    "https://nevioservicecenterapim.azure-api.net"
).rstrip("/")

# Cancel & Refund GraphQL endpoint (RetriveOrderRefundEligiblities / CancellationAndRefund)
APIM_REFUND_PATH: str = os.environ.get("APIM_REFUND_PATH", "/cancelAndRefund")

# Token TTL in seconds (~28 min, matching Amadeus OAuth token lifetime)
APIM_TOKEN_TTL: int = int(os.environ.get("APIM_TOKEN_TTL", "1700"))

# HTTP request timeout
API_REQUEST_TIMEOUT: int = int(os.environ.get("API_REQUEST_TIMEOUT", "30"))

# ─── HTTPS / TLS ──────────────────────────────────────────────────
# Set paths to enable HTTPS for SSE transport. Leave empty for plain HTTP.
SSL_CERTFILE: str = os.environ.get("SSL_CERTFILE", "")
SSL_KEYFILE: str = os.environ.get("SSL_KEYFILE", "")

# ─── Rate Limiting ────────────────────────────────────────────────
# Max requests per IP per minute for HTTP endpoints.
RATE_LIMIT_PER_MINUTE: int = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "100"))

# ─── Hosting behind a reverse proxy / Azure Container Apps ingress ──
# Comma-separated Host header values accepted by the /mcp endpoint. When empty,
# DNS-rebinding protection is off and the endpoint relies on MCP_API_KEY alone.
MCP_ALLOWED_HOSTS: list[str] = [
    h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
]

# ─── Structured Logging ──────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(SERVER_NAME)
