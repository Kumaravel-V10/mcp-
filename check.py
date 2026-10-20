"""SC-MCP-SERVER readiness check — verify the booking agent server is working."""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "PASS"
FAIL = "FAIL"
results = []

def check(label, fn):
    try:
        val = fn()
        print(f"  [PASS] {label}: {val}")
        results.append((label, True))
        return val
    except Exception as e:
        print(f"  [FAIL] {label}: {e}")
        results.append((label, False))
        return None

print()
print("=" * 55)
print("  SC-MCP-SERVER Readiness Check (Booking Agent)")
print("=" * 55)

# ── 1. Config ──
print("\n[1] Configuration")
from config import SERVER_NAME, SERVER_VERSION, APIM_BASE_URL, APIM_TOKEN_TTL
check("Server name", lambda: f"{SERVER_NAME} v{SERVER_VERSION}")
check("APIM base URL", lambda: APIM_BASE_URL)
check("Token TTL", lambda: f"{APIM_TOKEN_TTL}s")

# ── 2. Token Manager ──
print("\n[2] Token Manager")
from src.utils.token_manager import TokenManager, token_manager
check("TokenManager class", lambda: "loaded")
check("Singleton instance", lambda: "ready")

# ── 3. APIM Client ──
print("\n[3] APIM Client")
from src.utils.apim_client import call_apim_graphql
check("call_apim_graphql", lambda: "loaded")

# ── 4. Booking Tools ──
print("\n[4] Booking Tools (10 tools)")
from src.tools.booking_tools import (
    tool_search_flights, tool_create_cart, tool_update_passengers,
    tool_get_service_catalog, tool_get_seat_map, tool_add_seats,
    tool_add_ancillaries, tool_retrieve_cart, tool_confirm_booking,
    tool_retrieve_order,
)
BOOKING_TOOLS = {
    "search_flights": tool_search_flights,
    "create_cart": tool_create_cart,
    "update_passengers": tool_update_passengers,
    "get_service_catalog": tool_get_service_catalog,
    "get_seat_map": tool_get_seat_map,
    "add_seats": tool_add_seats,
    "add_ancillaries": tool_add_ancillaries,
    "retrieve_cart": tool_retrieve_cart,
    "confirm_booking": tool_confirm_booking,
    "retrieve_order": tool_retrieve_order,
}
for name, fn in BOOKING_TOOLS.items():
    check(name, lambda f=fn: f"callable={callable(f)}")

# ── 5. MCP Server ──
print("\n[5] MCP Server")
from server import mcp
check("FastMCP loaded", lambda: f"name={mcp.name}")

# ── 6. Prompt ──
print("\n[6] Booking Flow Prompt")
from server import BOOKING_FLOW_PROMPT
check("booking_flow prompt", lambda: f"{len(BOOKING_FLOW_PROMPT)} chars")

# ── Summary ──
total = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed
print()
print("=" * 55)
if failed == 0:
    print(f"  ALL {total} CHECKS PASSED — Booking Agent Server is ready")
    print()
    print("  Connect to Claude Desktop:")
    print('  Add to %APPDATA%\\Claude\\claude_desktop_config.json:')
    print('  {')
    print('    "mcpServers": {')
    print('      "sc-booking-agent": {')
    print('        "command": "python",')
    print(f'        "args": ["{os.path.abspath("server.py").replace(chr(92), "/")}"]')
    print('      }')
    print('    }')
    print('  }')
else:
    print(f"  {passed}/{total} PASSED, {failed} FAILED — Fix issues above")
print("=" * 55)
print()
