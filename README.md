# SC-MCP-SERVER — Create Booking Agent

MCP server for AI agents to execute the complete **NevioServiceCenter** flight booking flow. Provides **10 tools** against the live APIM gateway with automatic JWT token management.

---

## Quick Start

```bash
cd SC-MCP-SERVER
pip install -r requirements.txt
python check.py          # verify all 18 checks pass
python server.py         # start in stdio mode
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AI Assistant                          │
│            (Claude / Copilot / Custom Agent)             │
└──────────────────────┬──────────────────────────────────┘
                       │ MCP Protocol (stdio / SSE)
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  SC-MCP-SERVER v2.0                      │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │           10 Booking Agent Tools                  │   │
│  │    + 1 Prompt (booking_flow guide)                │   │
│  └──────────────────────┬───────────────────────────┘   │
│                         │                                │
│                  ┌──────┴───────┐                        │
│                  │ APIM Client  │                        │
│                  │ + Token Mgr  │                        │
│                  └──────┬───────┘                        │
└─────────────────────────┼────────────────────────────────┘
                          │ HTTPS + JWT
                          ▼
            ┌──────────────────────────┐
            │  APIM Gateway            │
            │  (Azure API Management)  │
            │                          │
            │  /token                  │
            │  /shop/flights           │
            │  /create-cart            │
            │  /checkout/passengers    │
            │  /services               │
            │  /seatmap                │
            │  /seat/services          │
            │  /cart/retrieve          │
            │  /checkoutConfirm        │
            │  /orders/retrieve        │
            └──────────────────────────┘
```

---

## Booking Flow (10 Tools)

Token management is automatic — the server fetches, caches (~28 min), and refreshes JWT tokens transparently.

### Flow Sequence

```
SearchFlights → CreateCart → UpdatePassengers → [GetServiceCatalog] → [GetSeatMap]
     │               │              │                   │                   │
  SKU IDs      checkoutId    passenger IDs         service SKUs        seat grid
                    │              │                   │                   │
                    └──────────────┴───────────────────┴───────────────────┘
                                          │
                              [AddAncillaries] / [AddSeats]
                                          │
                                    RetrieveCart
                                          │
                                    ConfirmBooking
                                          │
                                     orderId / PNR
                                          │
                                    RetrieveOrder
```

Steps in `[ ]` are optional.

### Tool Reference

| # | Tool | Endpoint | Purpose |
|---|------|----------|---------|
| 1 | `search_flights` | `/shop/flights` | Search flight offers |
| 2 | `create_cart` | `/create-cart` | Create booking cart from SKU IDs |
| 3 | `update_passengers` | `/checkout/passengers` | Add passenger identity & contact |
| 4 | `get_service_catalog` | `/services` | Browse ancillary services |
| 5 | `get_seat_map` | `/seatmap` | View seat availability |
| 6 | `add_seats` | `/seat/services` | Assign seats |
| 7 | `add_ancillaries` | `/seat/services` | Add bags, meals, wifi |
| 8 | `retrieve_cart` | `/cart/retrieve` | Review cart before confirm |
| 9 | `confirm_booking` | `/checkoutConfirm` | Create order (PNR) — **irreversible** |
| 10 | `retrieve_order` | `/orders/retrieve` | Fetch confirmed order |

### Rules

- Thread `checkoutId` from step 2 through steps 3–9
- Always call `retrieve_cart` before `confirm_booking`
- `confirm_booking` is irreversible — confirm with user first
- At least one passenger must have `contactDetails` (email + mobile)
- Dates use `YYYY-MM-DD` format

---

### 1. `search_flights`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `trip_type` | string | Yes | `OW`, `RT`, or `MC` |
| `departure_location` | string | Yes | IATA code (e.g. `HEL`) |
| `arrival_location` | string | Yes | IATA code (e.g. `JFK`) |
| `departure_date` | string | Yes | `YYYY-MM-DD` |
| `passengers` | list | Yes | `[{"passengerTypeCode": "ADT", "discountCode": "ADT"}]` |
| `fare_type` | string | No | `Economy` (default), `Business`, `First` |
| `return_date` | string | No | Required for `RT` trips |

### 2. `create_cart`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sku_ids` | list[str] | Yes | SKU IDs from search results |
| `airline_id` | string | No | Default `AY` |
| `agent_id` | string | No | Default `MCP-Agent` |

**Key outputs:** `checkoutId` (steps 3–9), `passengers[].passengerId` (step 3), `connections[].flights[].id` (step 5)

### 3. `update_passengers`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |
| `passengers` | list[dict] | Yes | Identity + contact details |

### 4. `get_service_catalog`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |
| `promotion_code` | string | No | e.g. `SCUISEATP` |

### 5. `get_seat_map`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |
| `flight_id` | string | Yes | Flight segment ID from `create_cart` |
| `promotion_code` | string | No | e.g. `SCUISEATP` |

### 6. `add_seats`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |
| `traveller` | list[dict] | Yes | `[{id, seat: [{flightId, seat, bundleId?}]}]` |

### 7. `add_ancillaries`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |
| `traveller` | list[dict] | Yes | `[{id, services: [{id, quantity}]}]` |

### 8. `retrieve_cart`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |

### 9. `confirm_booking`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checkout_id` | string | Yes | From `create_cart` |

### 10. `retrieve_order`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | string | Yes | From `confirm_booking` (e.g. `8LUTXS`) |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APIM_BASE_URL` | `https://nevioservicecenterapim.azure-api.net` | APIM gateway URL |
| `APIM_TOKEN_TTL` | `1700` | JWT token cache TTL in seconds |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `sse` |
| `MCP_PORT` | `3100` | HTTP port (SSE mode) |
| `MCP_HOST` | `127.0.0.1` | HTTP host (SSE mode) |
| `MCP_API_KEY` | (empty) | Bearer token for HTTP auth |
| `API_REQUEST_TIMEOUT` | `30` | HTTP request timeout in seconds |

---

## Connection Guides

### Claude Desktop

```json
{
  "mcpServers": {
    "sc-booking-agent": {
      "command": "python",
      "args": ["C:/path/to/SC-MCP-SERVER/server.py"]
    }
  }
}
```

### GitHub Copilot (VS Code)

Add to `.vscode/mcp.json`:
```json
{
  "servers": {
    "sc-booking-agent": {
      "command": "python",
      "args": ["C:/path/to/SC-MCP-SERVER/server.py"]
    }
  }
}
```

### HTTP/SSE

```bash
python server.py --transport sse --port 3100
```

```json
{
  "mcpServers": {
    "sc-booking-agent": {
      "url": "http://localhost:3100/sse"
    }
  }
}
```

### REST API (SSE mode)

```bash
# List tools
curl http://localhost:3100/api/tools

# Call a tool
curl -X POST http://localhost:3100/api/tools/search_flights \
  -H "Content-Type: application/json" \
  -d '{"trip_type":"OW","departure_location":"HEL","arrival_location":"JFK","departure_date":"2026-07-24","passengers":[{"passengerTypeCode":"ADT","discountCode":"ADT"}]}'
```

---

## Project Structure

```
SC-MCP-SERVER/
├── server.py              # Entry point — 10 tools, 1 prompt, SSE/stdio
├── config.py              # APIM + transport configuration
├── check.py               # Readiness check (18 checks)
├── requirements.txt       # Python dependencies
├── README.md              # This file
└── src/
    └── tools/
    │   └── booking_tools.py   # 10 booking tool implementations
    └── utils/
        ├── apim_client.py     # APIM HTTP client with auto JWT auth
        └── token_manager.py   # JWT token fetch, cache, refresh
```

---

## Token Management

1. First API call → `TokenManager` calls `POST {APIM_BASE_URL}/token`
2. JWT extracted from `AuthToken` cookie (fallback: response body, `Set-Cookie` header)
3. Cached for `APIM_TOKEN_TTL` seconds (default ~28 min)
4. Auto-refreshes on expiry
5. On HTTP 401, invalidates token and retries once with a fresh token

No manual token handling needed.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp>=1.0.0` | Model Context Protocol framework |
| `httpx>=0.27.0` | HTTP client for APIM calls |
| `uvicorn[standard]>=0.30.0` | ASGI server (SSE transport) |
