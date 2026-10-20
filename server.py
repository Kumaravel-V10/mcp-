"""SC-MCP-SERVER — Create Booking Agent MCP Server.

Exposes 10 booking tools + 2 refund tools against the APIM gateway.
Token management is automatic — JWT is fetched, cached, and refreshed transparently.

Transport: stdio (default) or HTTP (Streamable HTTP at /mcp, legacy SSE at /sse).
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import time
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config import (
    MCP_ALLOWED_HOSTS,
    SERVER_NAME,
    SERVER_VERSION,
    SERVER_HOST,
    SERVER_PORT,
    TRANSPORT_MODE,
)
from src.tools.booking_tools import (
    tool_search_flights,
    tool_create_cart,
    tool_update_passengers,
    tool_get_service_catalog,
    tool_get_seat_map,
    tool_add_seats,
    tool_add_ancillaries,
    tool_retrieve_cart,
    tool_confirm_booking,
    tool_retrieve_order,
)
from src.tools.refund_tools import tool_check_refund_eligibility, tool_cancel_and_refund

# ═══════════════════════════════════════════════════════════════════════
# MCP Server Instance
# ═══════════════════════════════════════════════════════════════════════

mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "Airline service center MCP server for the NevioServiceCenter system. "
        "Provides 10 booking tools to execute the complete booking flow: "
        "SearchFlights → CreateCart → UpdatePassengers → GetServiceCatalog → GetSeatMap → "
        "AddSeats → AddAncillaries → RetrieveCart → ConfirmBooking → RetrieveOrder, "
        "plus 2 refund tools: CheckRefundEligibility → CancelAndRefund. "
        "Token management is automatic — no auth handling needed. "
        "Always SearchFlights before CreateCart. Always UpdatePassengers before seats/services. "
        "Always RetrieveCart before ConfirmBooking. Thread checkoutId between steps 2-9. "
        "Always CheckRefundEligibility before CancelAndRefund."
    ),
    # Streamable HTTP (/mcp) settings for remote clients such as Azure AI Foundry Agent Service:
    # stateless + JSON responses so any replica can serve any request.
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(MCP_ALLOWED_HOSTS),
        allowed_hosts=MCP_ALLOWED_HOSTS,
    ),
)


# ═══════════════════════════════════════════════════════════════════════
# BOOKING FLOW TOOLS
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_flights(
    trip_type: str,
    departure_location: str,
    arrival_location: str,
    departure_date: str,
    passengers: list[dict[str, str]],
    fare_type: str = "Economy",
    return_date: str = "",
) -> str:
    """Search for flight offers between two locations. First step in the booking flow.

    Returns available flights with SKU IDs needed to create a cart.

    Args:
        trip_type: Trip type — 'OW' (one-way), 'RT' (round-trip), or 'MC' (multi-city).
        departure_location: Departure airport code (e.g. 'HEL', 'JFK').
        arrival_location: Arrival airport code (e.g. 'JFK', 'HEL').
        departure_date: Departure date in YYYY-MM-DD format.
        passengers: List of passenger dicts with 'passengerTypeCode' and 'discountCode'.
                    Example: [{"passengerTypeCode": "ADT", "discountCode": "ADT"}]
        fare_type: Fare cabin type (default 'Economy'). Options: 'Economy', 'Business', 'First'.
        return_date: Return date for round-trip in YYYY-MM-DD. Required if trip_type is 'RT'.
    """
    return tool_search_flights(
        trip_type, departure_location, arrival_location,
        departure_date, passengers, fare_type, return_date,
    )


@mcp.tool()
def create_cart(
    sku_ids: list[str],
    airline_id: str = "AY",
    agent_id: str = "MCP-Agent",
) -> str:
    """Create a booking cart from selected flight SKU IDs. Call after SearchFlights.

    Returns cartId, checkoutId, and passenger IDs for subsequent steps.

    Args:
        sku_ids: List of SKU IDs from SearchFlights results.
        airline_id: Airline code (default 'AY').
        agent_id: Agent identifier (default 'MCP-Agent').
    """
    return tool_create_cart(sku_ids, airline_id, agent_id)


@mcp.tool()
def update_passengers(
    checkout_id: str,
    passengers: list[dict],
) -> str:
    """Add or update passenger information for a checkout. Call after CreateCart.

    Each passenger must include id (from CreateCart), passengerTypeCode,
    and identityDetails (firstName, lastName, gender, dateOfBirth, title).
    At least one passenger must have contactDetails with email and mobile.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        passengers: List of passenger objects with identity and contact details.
    """
    return tool_update_passengers(checkout_id, passengers)


@mcp.tool()
def get_service_catalog(
    checkout_id: str,
    promotion_code: str = "",
) -> str:
    """Retrieve ancillary services catalogue (bags, meals, wifi, etc.) for a checkout.

    Call after UpdatePassengers. Returns available service SKUs per passenger with pricing.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        promotion_code: Optional promotion code (e.g. 'SCUISEATP').
    """
    return tool_get_service_catalog(checkout_id, promotion_code)


@mcp.tool()
def get_seat_map(
    checkout_id: str,
    flight_id: str,
    promotion_code: str = "",
) -> str:
    """Retrieve seat map for a flight showing seat availability and pricing.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        flight_id: Flight segment ID from CreateCart connections.flights[].id.
        promotion_code: Optional promotion code (e.g. 'SCUISEATP').
    """
    return tool_get_seat_map(checkout_id, flight_id, promotion_code)


@mcp.tool()
def add_seats(
    checkout_id: str,
    traveller: list[dict],
) -> str:
    """Assign seats to passengers. Call after GetSeatMap.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        traveller: List of seat assignments. Each: {id: passengerID, seat: [{flightId, seat, bundleId?}]}
    """
    return tool_add_seats(checkout_id, traveller)


@mcp.tool()
def add_ancillaries(
    checkout_id: str,
    traveller: list[dict],
) -> str:
    """Add ancillary services (bags, meals, wifi) to a checkout. Call after GetServiceCatalog.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        traveller: List of service selections. Each: {id: passengerID, services: [{id: SKU_id, quantity: int}]}
    """
    return tool_add_ancillaries(checkout_id, traveller)


@mcp.tool()
def retrieve_cart(checkout_id: str) -> str:
    """Retrieve full cart state for review before confirmation.

    Returns passengers, flights, seats, services, and total pricing.

    Args:
        checkout_id: The checkoutId from CreateCart response.
    """
    return tool_retrieve_cart(checkout_id)


@mcp.tool()
def confirm_booking(checkout_id: str) -> str:
    """Confirm the booking and create an order (generates PNR). IRREVERSIBLE.

    Call only after all passengers, seats, and services are added and cart is reviewed.
    Returns orderId and booking confirmation details.

    Args:
        checkout_id: The checkoutId from CreateCart response.
    """
    return tool_confirm_booking(checkout_id)


@mcp.tool()
def retrieve_order(order_id: str) -> str:
    """Retrieve a confirmed booking order with full details.

    Returns PNR, passengers, flights, services, seats, payment, and eligibilities.

    Args:
        order_id: The order ID from ConfirmBooking response (e.g. '8LUTXS').
    """
    return tool_retrieve_order(order_id)


# ═══════════════════════════════════════════════════════════════════════
# REFUND TOOLS
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def check_refund_eligibility(order_id: str, last_name: str) -> str:
    """Check whether a booking can be cancelled and refunded. Read-only.

    Returns refundStatus ('refundable' / 'non-refundable'), totals for refund, paid,
    used and penalty amounts, a per-traveler breakdown, refundProposalReferences
    (required by cancel_and_refund) and nonEligibilityReasons.

    Args:
        order_id: The 6-character PNR / order ID (e.g. '9DVWPJ').
        last_name: Last name of the primary traveler on the booking.
    """
    return tool_check_refund_eligibility(order_id, last_name)


@mcp.tool()
def cancel_and_refund(order_id: str, last_name: str, refund_proposal_ids: list[str]) -> str:
    """Cancel a booking and execute the refund. IRREVERSIBLE.

    Call only after check_refund_eligibility returned refundStatus 'refundable' and the
    customer explicitly accepted the refund breakdown.

    Args:
        order_id: The 6-character PNR / order ID (e.g. '9DVWPJ').
        last_name: Last name of the primary traveler on the booking.
        refund_proposal_ids: refundProposalReferences[].refundProposalId values from
            check_refund_eligibility.
    """
    return tool_cancel_and_refund(order_id, last_name, refund_proposal_ids)


# ═══════════════════════════════════════════════════════════════════════
# HTTP TOOL REGISTRY (for SSE /api/tools endpoint)
# ═══════════════════════════════════════════════════════════════════════

HTTP_TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "search_flights": search_flights,
    "create_cart": create_cart,
    "update_passengers": update_passengers,
    "get_service_catalog": get_service_catalog,
    "get_seat_map": get_seat_map,
    "add_seats": add_seats,
    "add_ancillaries": add_ancillaries,
    "retrieve_cart": retrieve_cart,
    "confirm_booking": confirm_booking,
    "retrieve_order": retrieve_order,
    "check_refund_eligibility": check_refund_eligibility,
    "cancel_and_refund": cancel_and_refund,
}


def _coerce_http_argument(value: Any, parameter: inspect.Parameter) -> Any:
    annotation = parameter.annotation

    if annotation is inspect._empty or value is None:
        return value

    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        return value

    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"Expected boolean for '{parameter.name}'.")

    if annotation in {int, float, str}:
        try:
            return annotation(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Expected {annotation.__name__} for '{parameter.name}'.") from exc

    return value


def _prepare_http_tool_arguments(tool_name: str, raw_arguments: dict[str, Any]) -> dict[str, Any]:
    func = HTTP_TOOL_REGISTRY[tool_name]
    signature = inspect.signature(func)
    prepared: dict[str, Any] = {}

    for name, parameter in signature.parameters.items():
        if name in raw_arguments:
            prepared[name] = _coerce_http_argument(raw_arguments[name], parameter)
        elif parameter.default is inspect._empty:
            raise ValueError(f"Missing required argument '{name}'.")

    unexpected = sorted(set(raw_arguments) - set(signature.parameters))
    if unexpected:
        raise ValueError(f"Unexpected arguments: {', '.join(unexpected)}.")

    return prepared


def _parse_tool_result(result: str) -> Any:
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return result


def _describe_http_tools() -> list[dict[str, Any]]:
    descriptions: list[dict[str, Any]] = []
    for name, func in HTTP_TOOL_REGISTRY.items():
        signature = inspect.signature(func)
        descriptions.append({
            "name": name,
            "description": inspect.getdoc(func) or "",
            "arguments": [
                {
                    "name": parameter.name,
                    "required": parameter.default is inspect._empty,
                    "default": None if parameter.default is inspect._empty else parameter.default,
                    "type": (
                        "any"
                        if parameter.annotation is inspect._empty
                        else getattr(parameter.annotation, "__name__", str(parameter.annotation))
                    ),
                }
                for parameter in signature.parameters.values()
            ],
        })
    return descriptions


# ═══════════════════════════════════════════════════════════════════════
# PROMPT — Booking Flow Guide
# ═══════════════════════════════════════════════════════════════════════

BOOKING_FLOW_PROMPT = """\
# Create Booking Agent — Tool Sequence

Follow this exact order to execute a complete flight booking:

## Required Flow
1. **search_flights** → Get available flights and SKU IDs
2. **create_cart** → Create cart with selected SKU IDs → receive checkoutId + passenger IDs
3. **update_passengers** → Add passenger identity & contact details (use IDs from step 2)
4. **get_service_catalog** *(optional)* → Browse ancillary services (bags, meals, wifi)
5. **get_seat_map** *(optional)* → View seat availability for each flight segment
6. **add_seats** *(optional)* → Assign seats to passengers
7. **add_ancillaries** *(optional)* → Add bags, meals, etc.
8. **retrieve_cart** → Review full cart before confirming
9. **confirm_booking** → Create the order (PNR). **IRREVERSIBLE**
10. **retrieve_order** → Fetch confirmed order details

## Rules
- Thread `checkoutId` from step 2 through steps 3-9.
- Steps 4-7 are optional — skip if the passenger doesn't want extras.
- ALWAYS call retrieve_cart (step 8) before confirm_booking (step 9).
- confirm_booking is irreversible — confirm with the user first.
- Passenger dates use YYYY-MM-DD format.
- At least one passenger must have contactDetails (email + mobile).
"""


@mcp.prompt()
def booking_flow() -> str:
    """Guide for the Create Booking Agent — correct tool sequence and rules
    for executing a complete flight booking from search to confirmation.
    """
    return BOOKING_FLOW_PROMPT


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def main():
    import signal

    parser = argparse.ArgumentParser(description=f"{SERVER_NAME} v{SERVER_VERSION}")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=TRANSPORT_MODE,
        help="Transport mode: stdio (default) or sse (HTTP/SSE)",
    )
    parser.add_argument("--host", default=SERVER_HOST, help="Host for SSE transport")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Port for SSE transport")
    args = parser.parse_args()

    from config import MCP_API_KEY, logger
    logger.info(f"Starting {SERVER_NAME} v{SERVER_VERSION}")
    logger.info(f"Transport: {args.transport}")

    # ── Graceful shutdown ──
    def _handle_shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} — shutting down gracefully")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    if args.transport == "sse":
        # ── Enforce API key for SSE mode ──
        if not MCP_API_KEY:
            logger.error(
                "MCP_API_KEY is not set. SSE mode requires an API key for security. "
                "Set MCP_API_KEY in your .env file or environment variables."
            )
            sys.exit(1)

        logger.info("API key enforcement: ACTIVE")
        _run_sse(args.host, args.port)
    else:
        mcp.run(transport="stdio")


def _run_sse(host: str, port: int) -> None:
    """Start in HTTP mode: Streamable HTTP (/mcp), legacy SSE (/sse), REST API for tools,
    rate limiting, and optional HTTPS."""
    import contextlib
    import uvicorn
    from collections import defaultdict
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route, Mount

    try:
        from mcp.server.sse import SseServerTransport
    except ImportError:
        from config import logger
        logger.error("mcp.server.sse not available — upgrade mcp package.")
        sys.exit(1)

    from config import MCP_API_KEY, RATE_LIMIT_PER_MINUTE, SSL_CERTFILE, SSL_KEYFILE, ALLOW_MUTATIONS, logger

    # ── Rate Limiting Middleware ──
    _request_timestamps: dict[str, list[float]] = defaultdict(list)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip rate limiting for health endpoint
            if request.url.path in ("/", "/health"):
                return await call_next(request)

            # Behind a proxy (Container Apps ingress, Nginx) every request comes from the
            # proxy's IP, so bucket by the original client from X-Forwarded-For.
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else "unknown"
            now = time.time()

            # Clean old entries (older than 60 seconds)
            _request_timestamps[client_ip] = [
                t for t in _request_timestamps[client_ip] if now - t < 60
            ]

            if len(_request_timestamps[client_ip]) >= RATE_LIMIT_PER_MINUTE:
                logger.warning(f"Rate limited client {client_ip}")
                return JSONResponse(
                    {"error": "Rate limit exceeded. Try again later."},
                    status_code=429,
                )

            _request_timestamps[client_ip].append(now)
            return await call_next(request)

    def _authorize_request(request: Request) -> JSONResponse | None:
        if not MCP_API_KEY:
            return None

        import hmac

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        token = auth[len("Bearer "):]
        if not hmac.compare_digest(token.encode(), MCP_API_KEY.encode()):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        return None

    sse_transport = SseServerTransport("/sse/messages")
    server_inst = mcp._mcp_server

    async def handle_sse(request):
        auth_error = _authorize_request(request)
        if auth_error is not None:
            return auth_error

        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server_inst.run(
                streams[0], streams[1],
                server_inst.create_initialization_options(),
            )
        # Starlette expects a response object once the SSE stream closes.
        return Response()

    # ── Streamable HTTP transport (/mcp) — used by Azure AI Foundry MCP tool ──
    streamable_starlette = mcp.streamable_http_app()  # also initializes mcp.session_manager
    streamable_asgi = next(
        r.endpoint for r in streamable_starlette.routes
        if getattr(r, "path", None) == mcp.settings.streamable_http_path
    )

    class AuthenticatedMcpEndpoint:
        """ASGI wrapper enforcing the Bearer API key before the MCP transport."""

        async def __call__(self, scope, receive, send):
            auth_error = _authorize_request(Request(scope))
            if auth_error is not None:
                await auth_error(scope, receive, send)
                return
            await streamable_asgi(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    async def health(request):
        return JSONResponse({
            "status": "healthy",
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "tools": len(HTTP_TOOL_REGISTRY),
            "mutations_enabled": ALLOW_MUTATIONS,
            "endpoints": {
                "health": "/health",
                "tools_list": "GET /api/tools",
                "tool_call": "POST /api/tools/{tool_name}",
                "mcp_streamable_http": "/mcp",
                "sse": "/sse",
            },
        })

    async def list_http_tools(request: Request):
        auth_error = _authorize_request(request)
        if auth_error is not None:
            return auth_error

        return JSONResponse({
            "tools": _describe_http_tools(),
            "total": len(HTTP_TOOL_REGISTRY),
        })

    async def call_http_tool(request: Request):
        auth_error = _authorize_request(request)
        if auth_error is not None:
            return auth_error

        tool_name = request.path_params["tool_name"]
        func = HTTP_TOOL_REGISTRY.get(tool_name)
        if func is None:
            return JSONResponse({
                "error": f"Unknown tool '{tool_name}'.",
                "available_tools": sorted(HTTP_TOOL_REGISTRY),
            }, status_code=404)

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)

        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request body must be a JSON object."}, status_code=400)

        raw_arguments = payload.get("arguments", payload)
        if not isinstance(raw_arguments, dict):
            return JSONResponse({"error": "'arguments' must be a JSON object."}, status_code=400)

        try:
            prepared_arguments = _prepare_http_tool_arguments(tool_name, raw_arguments)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        started_at = time.perf_counter()
        try:
            raw_result = func(**prepared_arguments)
        except Exception as exc:
            logger.error(f"Tool {tool_name} failed: {exc}")
            return JSONResponse({
                "tool": tool_name,
                "arguments": prepared_arguments,
                "error": str(exc),
            }, status_code=500)

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(f"Tool {tool_name} completed in {duration_ms}ms")
        return JSONResponse({
            "tool": tool_name,
            "arguments": prepared_arguments,
            "duration_ms": duration_ms,
            "result": _parse_tool_result(raw_result),
        })

    app = Starlette(
        routes=[
            Route("/", health),
            Route("/health", health),
            Route("/api/tools", list_http_tools, methods=["GET"]),
            Route("/api/tools/{tool_name}", call_http_tool, methods=["POST"]),
            Route(mcp.settings.streamable_http_path, endpoint=AuthenticatedMcpEndpoint()),
            Route("/sse", handle_sse),
            Mount("/sse/messages", app=sse_transport.handle_post_message),
        ],
        middleware=[Middleware(RateLimitMiddleware)],
        lifespan=lifespan,
    )

    # ── HTTPS / TLS support ──
    ssl_kwargs = {}
    if SSL_CERTFILE and SSL_KEYFILE:
        ssl_kwargs["ssl_certfile"] = SSL_CERTFILE
        ssl_kwargs["ssl_keyfile"] = SSL_KEYFILE
        protocol = "https"
        logger.info(f"TLS enabled: cert={SSL_CERTFILE}")
    else:
        protocol = "http"
        logger.warning("TLS disabled — running plain HTTP. Set SSL_CERTFILE and SSL_KEYFILE for production.")

    logger.info(f"SSE server on {protocol}://{host}:{port}")
    logger.info(f"Mutations enabled: {ALLOW_MUTATIONS}")
    logger.info(f"Rate limit: {RATE_LIMIT_PER_MINUTE} req/min per IP")
    uvicorn.run(app, host=host, port=port, log_level="info", **ssl_kwargs)


if __name__ == "__main__":
    main()

