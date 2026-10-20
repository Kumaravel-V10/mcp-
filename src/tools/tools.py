"""MCP Tools — all tool implementations for the SC-MCP-SERVER."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional

from config import WORKSPACE_ROOT, ALLOWED_FILE_ROOT, APIM_CANCEL_REFUND_URL, API_REQUEST_TIMEOUT, ALLOW_MUTATIONS
from src.registry.services import (
    SERVICE_REGISTRY,
    find_service,
    list_all_services,
)
from src.utils.cache import cache
from src.utils.file_reader import safe_read_file, safe_read_lines, list_files, path_exists
from src.utils.graphql_parser import get_graphql_typedefs, get_graphql_resolvers
from src.utils.prisma_parser import get_prisma_schema, parse_prisma_models, get_prisma_enums
from src.utils.search import search_codebase, find_related_tests


# ═══════════════════════════════════════════════════════════════════════
# STATIC KNOWLEDGE BASE — embedded so tools work even without service
# folders on disk. Keep in sync with actual service implementations.
# ═══════════════════════════════════════════════════════════════════════

# Full GraphQL contracts per service (typedefs + resolvers)
_STATIC_GRAPHQL_CONTRACTS: dict[str, dict] = {
    "SC-API-SearchPanel": {
        "typedefs": """
type Airline { code: String! name: String! logoUrl: String }
type Airport { iata: String! name: String! city: String! country: String! }
type Cabin { code: String! label: String! }
type PassengerType { code: String! label: String! minAge: Int maxAge: Int }

type Query {
  airlines: [Airline!]!
  airports(query: String): [Airport!]!
  cabins: [Cabin!]!
  passengerTypes: [PassengerType!]!
}""",
        "resolvers": [
            {"name": "airlines", "type": "Query", "description": "All available airline codes and names"},
            {"name": "airports", "type": "Query", "description": "Airport lookup with optional text filter"},
            {"name": "cabins", "type": "Query", "description": "Cabin class reference data"},
            {"name": "passengerTypes", "type": "Query", "description": "Passenger type codes (ADT, CHD, INF)"},
        ],
    },
    "SC-API-App-Config": {
        "typedefs": """
type FeatureFlag { key: String! enabled: Boolean! description: String }
type ThemeConfig { primaryColor: String! logoUrl: String fontFamily: String }
type RolePermission { role: String! features: [String!]! }
type CurrencyConfig { code: String! symbol: String! decimalPlaces: Int! }
type AppConfig {
  features: [FeatureFlag!]!
  theme: ThemeConfig!
  roles: [RolePermission!]!
  currencies: [CurrencyConfig!]!
}

type Mutation {
  updateFeatureFlag(key: String!, enabled: Boolean!): FeatureFlag!
  updateTheme(input: ThemeInput!): ThemeConfig!
  updateRolePermissions(role: String!, features: [String!]!): RolePermission!
}

type Query {
  appConfig: AppConfig!
  featureFlags: [FeatureFlag!]!
  rolePermissions(role: String!): RolePermission
}""",
        "resolvers": [
            {"name": "appConfig", "type": "Query", "description": "Full application configuration"},
            {"name": "featureFlags", "type": "Query", "description": "All feature toggle states"},
            {"name": "rolePermissions", "type": "Query", "description": "Feature permissions for a role"},
            {"name": "updateFeatureFlag", "type": "Mutation", "description": "Toggle a feature on/off"},
            {"name": "updateTheme", "type": "Mutation", "description": "Update branding/theme settings"},
            {"name": "updateRolePermissions", "type": "Mutation", "description": "Update role-feature mapping"},
        ],
    },
    "SC-API-Create-Cart": {
        "typedefs": """
type Cart {
  id: ID!
  status: CartStatus!
  flightOffer: FlightOffer!
  passengers: [Passenger!]!
  seats: [SeatSelection!]!
  services: [AncillaryService!]!
  totalPrice: Price!
  currency: String!
  createdAt: String!
  expiresAt: String!
}
type FlightOffer { id: ID! origin: String! destination: String! departureDate: String! returnDate: String segments: [FlightSegment!]! }
type FlightSegment { flightNumber: String! carrier: String! departure: String! arrival: String! cabinClass: String! }
type Price { amount: Float! currency: String! breakdown: [PriceBreakdown!]! }
type PriceBreakdown { label: String! amount: Float! }
enum CartStatus { ACTIVE EXPIRED CONFIRMED ABANDONED }

input CreateCartInput {
  flightOfferId: String!
  passengers: [PassengerCountInput!]!
  currency: String!
  agentId: String!
}
input PassengerCountInput { type: String! count: Int! }

type Mutation {
  createCart(input: CreateCartInput!): Cart!
}
type Query {
  validateSku(flightOfferId: String!): Boolean!
}""",
        "resolvers": [
            {"name": "createCart", "type": "Mutation", "description": "Initialise a new booking cart with a validated SKU"},
            {"name": "validateSku", "type": "Query", "description": "Validate Amadeus flight offer ID before cart creation"},
        ],
    },
    "SC-API-Retrieve-Cart": {
        "typedefs": """
type Query {
  cart(id: ID!): Cart
  cartsByAgent(agentId: String!): [Cart!]!
}""",
        "resolvers": [
            {"name": "cart", "type": "Query", "description": "Retrieve full cart state by cart ID"},
            {"name": "cartsByAgent", "type": "Query", "description": "List all active carts for an agent"},
        ],
    },
    "SC-API-Checkout-Passengers": {
        "typedefs": """
type PassengerValidationResult {
  valid: Boolean!
  passengerId: ID
  errors: [ValidationError!]!
}
type ValidationError { field: String! message: String! code: String! }
type Passenger {
  id: ID!
  cartId: ID!
  type: String!
  firstName: String!
  lastName: String!
  dateOfBirth: String!
  nationality: String!
  passportNumber: String
  passportExpiry: String
  email: String
  phone: String
}

input PassengerInput {
  type: String!
  firstName: String!
  lastName: String!
  dateOfBirth: String!
  nationality: String!
  passportNumber: String
  passportExpiry: String
  email: String
  phone: String
}

type Mutation {
  validatePassengers(cartId: ID!, passengers: [PassengerInput!]!): [PassengerValidationResult!]!
  savePassengers(cartId: ID!, passengers: [PassengerInput!]!): [Passenger!]!
}""",
        "resolvers": [
            {"name": "validatePassengers", "type": "Mutation", "description": "Validate PII fields and business rules for all passengers"},
            {"name": "savePassengers", "type": "Mutation", "description": "Persist validated passenger data to cart"},
        ],
    },
    "SC-API-Checkout-Confirm": {
        "typedefs": """
type BookingConfirmation {
  pnr: String!
  bookingReference: String!
  status: BookingStatus!
  totalCharged: Float!
  currency: String!
  passengers: [ConfirmedPassenger!]!
  segments: [FlightSegment!]!
  seats: [ConfirmedSeat!]!
  services: [ConfirmedService!]!
  issuedAt: String!
}
type ConfirmedPassenger { id: ID! name: String! type: String! ticketNumber: String! }
type ConfirmedSeat { passengerId: ID! seatNumber: String! cabin: String! price: Float! }
type ConfirmedService { passengerId: ID! type: String! description: String! price: Float! }
enum BookingStatus { CONFIRMED PENDING FAILED }

input ConfirmCheckoutInput {
  cartId: ID!
  paymentMethod: String!
  paymentToken: String!
  agentId: String!
}

input CheckoutCompleteInput {
  cartId: ID!
  passengers: [PassengerInput!]!
  seatSelections: [SeatSelectionInput!]!
  payment: PaymentInput!
}
input SeatSelectionInput { passengerId: ID! seatNumber: String! segmentId: String! }
input PaymentInput { method: String! token: String! }

type Mutation {
  confirmCheckout(input: ConfirmCheckoutInput!): BookingConfirmation!
  checkoutComplete(input: CheckoutCompleteInput!): BookingConfirmation!
}
type Query {
  booking(pnr: String!): BookingConfirmation
}""",
        "resolvers": [
            {"name": "confirmCheckout", "type": "Mutation", "description": "Process payment and generate PNR (requires pre-validated passengers & seats)"},
            {"name": "checkoutComplete", "type": "Mutation", "description": "Unified orchestration: validate passengers + confirm seats + process payment in one call"},
            {"name": "booking", "type": "Query", "description": "Retrieve a confirmed booking by PNR"},
        ],
    },
    "SC-API-Seat-Map": {
        "typedefs": """
type SeatMap {
  flightSegmentId: String!
  aircraft: String!
  cabins: [CabinMap!]!
}
type CabinMap { cabin: String! rows: [SeatRow!]! }
type SeatRow { rowNumber: Int! seats: [Seat!]! }
type Seat {
  id: ID!
  number: String!
  available: Boolean!
  type: SeatType!
  price: Float!
  currency: String!
  features: [String!]!
}
enum SeatType { WINDOW MIDDLE AISLE EXIT_ROW BULKHEAD }

type Query {
  seatMap(cartId: ID!, segmentId: String!): SeatMap!
  seatPrice(cartId: ID!, seatNumber: String!, segmentId: String!): Float!
}""",
        "resolvers": [
            {"name": "seatMap", "type": "Query", "description": "Full seat grid with availability and pricing from Amadeus"},
            {"name": "seatPrice", "type": "Query", "description": "Price for a specific seat on a segment"},
        ],
    },
    "SC-API-Seat-Services": {
        "typedefs": """
type SeatSelection {
  id: ID!
  cartId: ID!
  passengerId: ID!
  segmentId: String!
  seatNumber: String!
  price: Float!
  confirmedAt: String
}

input SelectSeatInput {
  cartId: ID!
  passengerId: ID!
  segmentId: String!
  seatNumber: String!
}

type Mutation {
  selectSeat(input: SelectSeatInput!): SeatSelection!
  confirmSeatSelections(cartId: ID!): [SeatSelection!]!
  releaseSeat(cartId: ID!, seatSelectionId: ID!): Boolean!
}
type Query {
  seatSelections(cartId: ID!): [SeatSelection!]!
}""",
        "resolvers": [
            {"name": "selectSeat", "type": "Mutation", "description": "Reserve a seat for a passenger on a segment"},
            {"name": "confirmSeatSelections", "type": "Mutation", "description": "Confirm and persist all seat selections in a cart"},
            {"name": "releaseSeat", "type": "Mutation", "description": "Release a previously selected seat"},
            {"name": "seatSelections", "type": "Query", "description": "Get all seat selections for a cart"},
        ],
    },
    "SC-API-Services": {
        "typedefs": """
type AncillaryService {
  id: ID!
  type: ServiceType!
  name: String!
  description: String!
  price: Float!
  currency: String!
  perPassenger: Boolean!
  perSegment: Boolean!
  maxQuantity: Int!
}
enum ServiceType { BAGGAGE MEAL WIFI LOUNGE PRIORITY_BOARDING INSURANCE }

type CartService {
  id: ID!
  cartId: ID!
  passengerId: ID!
  service: AncillaryService!
  quantity: Int!
  segmentId: String
  totalPrice: Float!
}

input AddServiceInput {
  cartId: ID!
  passengerId: ID!
  serviceId: ID!
  quantity: Int!
  segmentId: String
}

type Mutation {
  addServiceToCart(input: AddServiceInput!): CartService!
  removeServiceFromCart(cartServiceId: ID!): Boolean!
}
type Query {
  availableServices(cartId: ID!, passengerType: String): [AncillaryService!]!
  cartServices(cartId: ID!): [CartService!]!
}""",
        "resolvers": [
            {"name": "availableServices", "type": "Query", "description": "Fetch available ancillary services for a cart (baggage, meals, WiFi, etc.)"},
            {"name": "cartServices", "type": "Query", "description": "Get all services already added to a cart"},
            {"name": "addServiceToCart", "type": "Mutation", "description": "Add an ancillary service to the cart for a passenger"},
            {"name": "removeServiceFromCart", "type": "Mutation", "description": "Remove a service from the cart"},
        ],
    },
}

# Cross-service call dependency map: which services each backend calls internally
_SERVICE_DEPENDENCIES: dict[str, dict] = {
    "SC-API-Token": {
        "calls": [],
        "called_by": ["SC-API-SearchPanel", "SC-API-Create-Cart", "SC-API-Checkout-Confirm", "SC-API-Seat-Map", "SC-API-Services"],
        "external": ["Amadeus OAuth2 /v1/security/oauth2/token"],
        "description": "Auth hub — all services that call Amadeus get a token from here first.",
    },
    "SC-API-SearchPanel": {
        "calls": ["SC-API-Token"],
        "called_by": ["SC-UI-ServiceCenterMain"],
        "external": [],
        "description": "Read-only reference data; calls Token only for Amadeus-backed lookups.",
    },
    "SC-API-App-Config": {
        "calls": [],
        "called_by": ["SC-UI-ServiceCenterMain"],
        "external": ["Strapi CMS (feature content)", "Salesforce CRM (role sync)"],
        "description": "Config authority; no upstream service calls.",
    },
    "SC-API-Create-Cart": {
        "calls": ["SC-API-Token"],
        "called_by": ["SC-UI-ServiceCenterMain"],
        "external": ["Amadeus /v2/shopping/flight-offers (SKU validation)"],
        "description": "Validates SKU with Amadeus then persists cart to DB.",
    },
    "SC-API-Retrieve-Cart": {
        "calls": [],
        "called_by": ["SC-UI-ServiceCenterMain", "SC-API-Checkout-Confirm"],
        "external": [],
        "description": "Pure DB read; no outbound service calls.",
    },
    "SC-API-Checkout-Passengers": {
        "calls": [],
        "called_by": ["SC-UI-ServiceCenterMain", "SC-API-Checkout-Confirm"],
        "external": [],
        "description": "Validates and persists PII; self-contained.",
    },
    "SC-API-Seat-Map": {
        "calls": ["SC-API-Token"],
        "called_by": ["SC-UI-ServiceCenterMain"],
        "external": ["Amadeus /v1/shopping/seatmaps"],
        "description": "Fetches live seat availability from Amadeus.",
    },
    "SC-API-Seat-Services": {
        "calls": [],
        "called_by": ["SC-UI-ServiceCenterMain", "SC-API-Checkout-Confirm"],
        "external": [],
        "description": "Manages seat reservations in local DB; no external calls.",
    },
    "SC-API-Services": {
        "calls": ["SC-API-Token"],
        "called_by": ["SC-UI-ServiceCenterMain"],
        "external": ["Amadeus /v1/shopping/flight-offers/upselling"],
        "description": "Ancillary catalog fetched from Amadeus and persisted.",
    },
    "SC-API-Checkout-Confirm": {
        "calls": ["SC-API-Checkout-Passengers", "SC-API-Seat-Services", "SC-API-Retrieve-Cart", "SC-API-Token"],
        "called_by": ["SC-UI-ServiceCenterMain"],
        "external": ["Amadeus /v1/booking/flight-orders", "Payment Gateway (Stripe/Adyen)", "Salesforce CRM (booking record)"],
        "description": "Orchestrator: validates passengers, confirms seats, charges payment, creates PNR.",
    },
    "SC-UI-ServiceCenterMain": {
        "calls": ["SC-API-SearchPanel", "SC-API-App-Config", "SC-API-Create-Cart", "SC-API-Retrieve-Cart",
                  "SC-API-Checkout-Passengers", "SC-API-Checkout-Confirm", "SC-API-Seat-Map",
                  "SC-API-Seat-Services", "SC-API-Services", "SC-API-Token"],
        "called_by": ["Browser / Agent UI"],
        "external": ["NextAuth.js (session)", "Azure OpenAI GPT-4o (AI assist)"],
        "description": "Main frontend — orchestrates all user flows via Apollo Client.",
    },
}

# UI store → Apollo hook → GraphQL resolver → backend service mapping
_UI_API_MAPPING: list[dict] = [
    {
        "store": "flightSearchStore",
        "store_actions": ["setSearchParams", "setResults", "setLoading"],
        "hooks": ["useFlightSearch"],
        "graphql_operations": [],
        "rest_calls": ["POST /api/flight-search"],
        "services": ["SC-API-Token", "External: Amadeus"],
        "flow": "search",
    },
    {
        "store": "searchPanelStore",
        "store_actions": ["setAirlines", "setAirports", "setCabins", "setPassengerTypes"],
        "hooks": ["useSearchPanel"],
        "graphql_operations": ["airlines (Query)", "airports (Query)", "cabins (Query)", "passengerTypes (Query)"],
        "rest_calls": [],
        "services": ["SC-API-SearchPanel"],
        "flow": "search",
    },
    {
        "store": "appConfigStore",
        "store_actions": ["setFeatureFlags", "setTheme", "setRoles"],
        "hooks": ["useAppConfig"],
        "graphql_operations": ["appConfig (Query)", "featureFlags (Query)"],
        "rest_calls": [],
        "services": ["SC-API-App-Config"],
        "flow": "app_init",
    },
    {
        "store": "cartStore",
        "store_actions": ["setCart", "clearCart", "setCartLoading"],
        "hooks": ["useCreateCart", "useRetrieveCart"],
        "graphql_operations": ["createCart (Mutation)", "cart (Query)", "cartsByAgent (Query)"],
        "rest_calls": ["POST /api/one-shot-cart"],
        "services": ["SC-API-Create-Cart", "SC-API-Retrieve-Cart"],
        "flow": "create_cart",
    },
    {
        "store": "passengerStore",
        "store_actions": ["setPassengers", "updatePassenger", "setValidationErrors"],
        "hooks": ["usePassengerValidation", "usePassengerSave"],
        "graphql_operations": ["validatePassengers (Mutation)", "savePassengers (Mutation)"],
        "rest_calls": ["POST /api/passengers"],
        "services": ["SC-API-Checkout-Passengers"],
        "flow": "checkout",
    },
    {
        "store": "seatMapStore",
        "store_actions": ["setSeatMap", "setSelectedSeat", "clearSeatMap"],
        "hooks": ["useSeatMap", "useSeatSelection"],
        "graphql_operations": ["seatMap (Query)", "seatPrice (Query)", "selectSeat (Mutation)", "confirmSeatSelections (Mutation)"],
        "rest_calls": ["POST /api/seat-map"],
        "services": ["SC-API-Seat-Map", "SC-API-Seat-Services"],
        "flow": "seat_selection",
    },
    {
        "store": "servicesStore",
        "store_actions": ["setAvailableServices", "addService", "removeService"],
        "hooks": ["useAvailableServices", "useCartServices"],
        "graphql_operations": ["availableServices (Query)", "cartServices (Query)", "addServiceToCart (Mutation)", "removeServiceFromCart (Mutation)"],
        "rest_calls": ["POST /api/services"],
        "services": ["SC-API-Services"],
        "flow": "services",
    },
    {
        "store": "orderStore",
        "store_actions": ["setConfirmation", "setBookingError", "clearOrder"],
        "hooks": ["useCheckoutConfirm", "useCheckoutComplete"],
        "graphql_operations": ["confirmCheckout (Mutation)", "checkoutComplete (Mutation)", "booking (Query)"],
        "rest_calls": ["POST /api/checkout/confirm"],
        "services": ["SC-API-Checkout-Confirm"],
        "flow": "checkout",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════════════

def tool_list_services() -> str:
    """Return all 11 ServiceCenter services with metadata."""
    return json.dumps(list_all_services(), indent=2)


def tool_get_service_schema(service: str) -> str:
    """Get the Prisma schema for a named service.

    Args:
        service: Service name or partial match (e.g. 'create-cart', 'checkout-confirm').
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found.", "available": [s.name for s in SERVICE_REGISTRY]})

    if not svc.has_prisma:
        return json.dumps({"error": f"Service '{svc.name}' does not use Prisma."})

    schema = get_prisma_schema(svc.folder)
    if not schema:
        return json.dumps({"error": f"Prisma schema file not found for '{svc.name}'."})

    models = parse_prisma_models(svc.folder)
    enums = get_prisma_enums(svc.folder)

    return json.dumps({
        "service": svc.name,
        "schema_raw": schema,
        "models": models,
        "enums": enums,
        "model_count": len(models),
    }, indent=2)


def tool_get_api_contract(service: str) -> str:
    """Get GraphQL typedefs and resolver list for a named service.

    Args:
        service: Service name or partial match.
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found.", "available": [s.name for s in SERVICE_REGISTRY]})

    if not svc.has_graphql:
        return json.dumps({"error": f"Service '{svc.name}' does not use GraphQL."})

    # Try live files first; fall back to embedded static contracts
    typedefs = get_graphql_typedefs(svc.folder)
    resolvers = get_graphql_resolvers(svc.folder)

    source = "live_files"
    if not typedefs and svc.name in _STATIC_GRAPHQL_CONTRACTS:
        static = _STATIC_GRAPHQL_CONTRACTS[svc.name]
        typedefs = static["typedefs"]
        resolvers = static["resolvers"]
        source = "static_embedded"

    return json.dumps({
        "service": svc.name,
        "source": source,
        "typedefs": typedefs if typedefs else "(No contract available)",
        "resolvers": resolvers,
        "resolver_count": len(resolvers),
    }, indent=2)


def tool_search_codebase(query: str, scope: str = "") -> str:
    """Search across all service source files for a text pattern.

    Args:
        query: Text or regex pattern to search for.
        scope: Optional service folder to limit search (e.g. 'SC-API-Create-Cart').
    """
    results = search_codebase(query, scope=scope or None)
    return json.dumps({
        "query": query,
        "scope": scope or "all services",
        "matches": results,
        "total": len(results),
    }, indent=2)


def tool_get_affected_tests(module_path: str) -> str:
    """Find test files related to a given source file or module.

    Args:
        module_path: Path to a source file (e.g. 'SC-API-Create-Cart/src/modules/Cart').
    """
    tests = find_related_tests(module_path)
    return json.dumps({
        "module": module_path,
        "test_files": tests,
        "count": len(tests),
    }, indent=2)


def tool_get_feature_impact(feature_name: str) -> str:
    """Analyse the cross-service impact of a feature across the entire codebase.

    Searches all services for references to the feature, identifies affected
    resolvers, DB models, UI modules, and test files.

    Args:
        feature_name: Feature name to trace (e.g. 'seat_selection', 'passenger_type', 'baggage').
    """
    impacts: dict = {
        "feature": feature_name,
        "services_affected": [],
        "resolvers_affected": [],
        "prisma_models_affected": [],
        "source_files": [],
        "test_files": [],
        "feature_flags": [],
    }

    # Search codebase for the feature
    code_matches = search_codebase(feature_name)
    seen_services: set[str] = set()

    for match in code_matches:
        file_path = match["file"]
        service_folder = file_path.split("/")[0] if "/" in file_path else ""

        # Track which services are affected
        svc = find_service(service_folder)
        if svc and svc.name not in seen_services:
            seen_services.add(svc.name)
            impacts["services_affected"].append({
                "name": svc.name,
                "type": svc.service_type,
                "description": svc.description,
            })

        impacts["source_files"].append(match)

    # Check for resolvers mentioning the feature
    for svc in SERVICE_REGISTRY:
        if not svc.has_graphql:
            continue
        resolvers = get_graphql_resolvers(svc.folder)
        for resolver in resolvers:
            if feature_name.lower().replace("_", "") in resolver["name"].lower().replace("_", ""):
                impacts["resolvers_affected"].append({
                    "service": svc.name,
                    **resolver,
                })

    # Check prisma models
    for svc in SERVICE_REGISTRY:
        if not svc.has_prisma:
            continue
        models = parse_prisma_models(svc.folder)
        for model in models:
            model_name_lower = model["name"].lower()
            if feature_name.lower().replace("_", "") in model_name_lower:
                impacts["prisma_models_affected"].append({
                    "service": svc.name,
                    "model": model["name"],
                    "fields": model["fields"],
                })

    # Check feature flag configs
    feature_flag_path = os.path.join(WORKSPACE_ROOT, "SC-API-App-Config", "default-feature-mapping.json")
    if os.path.isfile(feature_flag_path):
        try:
            with open(feature_flag_path, "r", encoding="utf-8") as f:
                flags = json.load(f)
            for key, value in (flags.items() if isinstance(flags, dict) else []):
                if feature_name.lower() in key.lower():
                    impacts["feature_flags"].append({"key": key, "value": value})
        except (json.JSONDecodeError, OSError):
            pass

    # Find related tests
    for match in code_matches[:5]:  # Top 5 files
        tests = find_related_tests(match["file"])
        impacts["test_files"].extend(tests)
    impacts["test_files"] = list(set(impacts["test_files"]))

    # Summary
    impacts["summary"] = {
        "services_count": len(impacts["services_affected"]),
        "resolvers_count": len(impacts["resolvers_affected"]),
        "models_count": len(impacts["prisma_models_affected"]),
        "source_files_count": len(impacts["source_files"]),
        "test_files_count": len(impacts["test_files"]),
    }

    return json.dumps(impacts, indent=2)


def tool_get_data_flow(flow_name: str) -> str:
    """Trace a booking data flow across services showing the request/response chain.

    Args:
        flow_name: Flow to trace (e.g. 'create_cart', 'checkout', 'search', 'seat_selection').
    """
    flows: dict[str, list[dict]] = {
        "search": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User fills search form", "api": "POST /api/flight-search"},
            {"step": 2, "service": "SC-API-Token", "action": "Get OAuth token for Amadeus", "api": "POST /api/token"},
            {"step": 3, "service": "External: Amadeus", "action": "Flight offers search", "api": "POST /v2/shopping/flight-offers"},
            {"step": 4, "service": "SC-UI-ServiceCenterMain", "action": "Transform & display results in flightResultStore"},
        ],
        "create_cart": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User selects flight offer", "api": "POST /api/one-shot-cart"},
            {"step": 2, "service": "SC-API-Create-Cart", "action": "Validate SKU & create cart", "api": "GraphQL: createCart mutation"},
            {"step": 3, "service": "SC-API-Create-Cart", "action": "Persist cart to PostgreSQL via Prisma"},
            {"step": 4, "service": "SC-UI-ServiceCenterMain", "action": "Store cart in cartStore, navigate to passengers"},
        ],
        "checkout": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User fills passenger forms", "api": "POST /api/passengers"},
            {"step": 2, "service": "SC-API-Checkout-Passengers", "action": "Validate PII & passenger data", "api": "GraphQL: validatePassengers"},
            {"step": 3, "service": "SC-UI-ServiceCenterMain", "action": "User selects seats", "api": "POST /api/seat-map"},
            {"step": 4, "service": "SC-API-Seat-Map", "action": "Get seat availability & pricing"},
            {"step": 5, "service": "SC-API-Seat-Services", "action": "Confirm seat selection"},
            {"step": 6, "service": "SC-UI-ServiceCenterMain", "action": "User confirms payment", "api": "POST /api/checkout/confirm"},
            {"step": 7, "service": "SC-API-Checkout-Confirm", "action": "Process payment & generate PNR"},
            {"step": 8, "service": "SC-UI-ServiceCenterMain", "action": "Display confirmation in orderStore"},
        ],
        "seat_selection": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User opens seat map", "api": "POST /api/seat-map"},
            {"step": 2, "service": "SC-API-Seat-Map", "action": "Fetch seat availability from Amadeus"},
            {"step": 3, "service": "SC-API-Seat-Map", "action": "Return structured seat grid with pricing"},
            {"step": 4, "service": "SC-UI-ServiceCenterMain", "action": "Render interactive seat map component"},
            {"step": 5, "service": "SC-API-Seat-Services", "action": "Persist seat selection to cart"},
        ],
        "services": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User opens ancillary services", "api": "POST /api/services"},
            {"step": 2, "service": "SC-API-Services", "action": "Fetch available services (baggage, meals, WiFi)"},
            {"step": 3, "service": "SC-UI-ServiceCenterMain", "action": "Display services in servicesStore"},
            {"step": 4, "service": "SC-API-Services", "action": "Add selected services to cart"},
        ],
        "authentication": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "Agent opens login page"},
            {"step": 2, "service": "SC-UI-ServiceCenterMain", "action": "NextAuth.js handles credentials via /api/auth/signin"},
            {"step": 3, "service": "SC-API-Token", "action": "Issue OAuth token for Amadeus API access", "api": "POST /api/token"},
            {"step": 4, "service": "External: Amadeus", "action": "Return access token (TTL 29 min)", "api": "POST /v1/security/oauth2/token"},
            {"step": 5, "service": "SC-API-Token", "action": "Cache token in DB until expiry"},
            {"step": 6, "service": "SC-UI-ServiceCenterMain", "action": "Store JWT session in NextAuth; redirect to search"},
        ],
        "cart_update": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User modifies cart (change seat / remove service)", "api": "POST /api/cart/update"},
            {"step": 2, "service": "SC-API-Retrieve-Cart", "action": "Fetch current cart state", "api": "GraphQL: cart(id)"},
            {"step": 3, "service": "SC-API-Seat-Services", "action": "Release old seat if changed", "api": "GraphQL: releaseSeat"},
            {"step": 4, "service": "SC-API-Services", "action": "Remove old ancillary if changed", "api": "GraphQL: removeServiceFromCart"},
            {"step": 5, "service": "SC-UI-ServiceCenterMain", "action": "Update cartStore with new state"},
        ],
        "ancillary_add": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User opens Add Services panel"},
            {"step": 2, "service": "SC-API-Services", "action": "Query available services for cart", "api": "GraphQL: availableServices(cartId, passengerType)"},
            {"step": 3, "service": "SC-UI-ServiceCenterMain", "action": "Render service cards in servicesStore"},
            {"step": 4, "service": "SC-API-Services", "action": "Add selected service to cart", "api": "GraphQL: addServiceToCart(input)"},
            {"step": 5, "service": "SC-API-Retrieve-Cart", "action": "Re-fetch cart to reflect updated total"},
            {"step": 6, "service": "SC-UI-ServiceCenterMain", "action": "Update cartStore total price display"},
        ],
        "booking_retrieval": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "Agent searches for existing booking by PNR"},
            {"step": 2, "service": "SC-API-Checkout-Confirm", "action": "Retrieve booking record", "api": "GraphQL: booking(pnr)"},
            {"step": 3, "service": "SC-UI-ServiceCenterMain", "action": "Display booking details in orderStore"},
        ],
        "cancel_and_refund": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "Agent retrieves order using orderId"},
            {"step": 2, "service": "APIM-CancelAndRefund", "action": "Check refund eligibility", "api": "GraphQL: RetriveOrderRefundEligiblities(input)"},
            {"step": 3, "service": "SC-UI-ServiceCenterMain", "action": "Evaluate eligibility response — check refundStatus and nonEligibilityReasons"},
            {"step": 4, "service": "APIM-CancelAndRefund", "action": "Execute cancellation and refund (if eligible)", "api": "GraphQL: CancellationAndRefund(input) with refundProposalIds"},
            {"step": 5, "service": "SC-UI-ServiceCenterMain", "action": "Display refund confirmation with amounts and payment details"},
        ],
        "optimised_checkout": [
            {"step": 1, "service": "SC-UI-ServiceCenterMain", "action": "User confirms all selections (passengers + seats + payment)", "api": "POST /api/checkout/confirm"},
            {"step": 2, "service": "SC-API-Checkout-Confirm", "action": "Receive unified CheckoutCompleteInput", "api": "GraphQL: checkoutComplete(input)"},
            {"step": 3, "service": "SC-API-Checkout-Confirm", "action": "Parallel: validatePassengers + confirmSeatSelections via Promise.all"},
            {"step": 4, "service": "SC-API-Checkout-Passengers", "action": "Validate & save passenger PII (internal call)"},
            {"step": 5, "service": "SC-API-Seat-Services", "action": "Confirm seat reservations (internal call, parallel with step 4)"},
            {"step": 6, "service": "SC-API-Checkout-Confirm", "action": "Process payment via payment gateway"},
            {"step": 7, "service": "External: Amadeus", "action": "Create flight order → generate PNR", "api": "POST /v1/booking/flight-orders"},
            {"step": 8, "service": "SC-API-Checkout-Confirm", "action": "Persist booking record to DB, sync to Salesforce"},
            {"step": 9, "service": "SC-UI-ServiceCenterMain", "action": "Receive single response → update orderStore → show confirmation"},
        ],
    }

    # Find matching flow
    flow_key = flow_name.lower().replace("-", "_").replace(" ", "_")
    matched_flow = flows.get(flow_key)

    if not matched_flow:
        # Partial match
        for key, flow in flows.items():
            if flow_key in key or key in flow_key:
                matched_flow = flow
                flow_key = key
                break

    if not matched_flow:
        return json.dumps({
            "error": f"Flow '{flow_name}' not found.",
            "available_flows": list(flows.keys()),
        })

    return json.dumps({
        "flow": flow_key,
        "steps": matched_flow,
        "total_steps": len(matched_flow),
        "services_involved": list(set(s["service"] for s in matched_flow)),
    }, indent=2)


def tool_get_env_dependencies(service: str) -> str:
    """Get required environment variables for a service (secrets masked).

    Args:
        service: Service name or partial match.
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found.", "available": [s.name for s in SERVICE_REGISTRY]})

    settings_path = os.path.join(WORKSPACE_ROOT, svc.folder, "local.settings.json")
    if not os.path.isfile(settings_path):
        return json.dumps({"error": f"local.settings.json not found for '{svc.name}'."})

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": f"Failed to read settings: {e}"})

    values = settings.get("Values", {})
    # Mask secret values — only return key names and value category
    env_vars: list[dict] = []
    secret_patterns = re.compile(r"(key|secret|password|token|connection|credential)", re.IGNORECASE)

    for key, value in values.items():
        is_secret = bool(secret_patterns.search(key)) or (isinstance(value, str) and len(value) > 50)
        env_vars.append({
            "key": key,
            "value": "***MASKED***" if is_secret else value,
            "is_secret": is_secret,
        })

    return json.dumps({
        "service": svc.name,
        "env_vars": env_vars,
        "total": len(env_vars),
        "secrets_count": sum(1 for v in env_vars if v["is_secret"]),
    }, indent=2)


def tool_get_pending_migrations(service: str) -> str:
    """Check for Prisma migration status for a service.

    Args:
        service: Service name or partial match.
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found."})

    if not svc.has_prisma:
        return json.dumps({"error": f"Service '{svc.name}' does not use Prisma."})

    migrations_dir = os.path.join(WORKSPACE_ROOT, svc.folder, "prisma", "migrations")
    if not os.path.isdir(migrations_dir):
        return json.dumps({
            "service": svc.name,
            "migrations": [],
            "message": "No migrations directory found.",
        })

    migrations: list[dict] = []
    for entry in sorted(os.listdir(migrations_dir)):
        migration_path = os.path.join(migrations_dir, entry)
        if os.path.isdir(migration_path):
            sql_file = os.path.join(migration_path, "migration.sql")
            has_sql = os.path.isfile(sql_file)
            migrations.append({
                "name": entry,
                "has_sql": has_sql,
                "path": os.path.relpath(migration_path, WORKSPACE_ROOT).replace("\\", "/"),
            })

    return json.dumps({
        "service": svc.name,
        "migrations": migrations,
        "total_migrations": len(migrations),
    }, indent=2)


def tool_read_file(path: str, start_line: int = 1, end_line: int = 100) -> str:
    """Read lines from a project source file. Lines are 1-indexed.

    Args:
        path: File path relative to workspace root.
        start_line: First line to return (1-based, default 1).
        end_line: Last line to return (1-based, max 500 lines per call).
    """
    result = safe_read_lines(path, start_line, end_line)
    return json.dumps(result, indent=2)


def tool_get_git_history(path: str, limit: int = 10) -> str:
    """Get recent git commit history for a file.

    Args:
        path: File path relative to workspace root.
        limit: Number of commits to return (max 50, default 10).
    """
    limit = min(limit, 50)
    resolved = os.path.normpath(os.path.join(WORKSPACE_ROOT, path))
    allowed = os.path.normpath(ALLOWED_FILE_ROOT)

    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return json.dumps({"error": "Access denied: path outside project root."})

    fmt = "%H|%an|%ae|%ad|%s"
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", f"--format={fmt}", "--date=short", "--", resolved],
            capture_output=True, text=True, timeout=10,
            cwd=WORKSPACE_ROOT,
        )
        if result.returncode != 0:
            return json.dumps({"error": result.stderr.strip() or "git log failed."})

        commits = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "hash": parts[0][:12],
                    "author": parts[1],
                    "date": parts[3],
                    "message": parts[4],
                })
        return json.dumps({"path": path, "commits": commits}, indent=2)
    except FileNotFoundError:
        return json.dumps({"error": "git executable not found."})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "git log timed out."})


def tool_get_service_dependencies(service: str) -> str:
    """Get the full dependency graph for a service — what it calls and what calls it.

    Returns internal service dependencies, external API calls, and a plain-English
    description so agents understand where the service fits in the architecture.

    Args:
        service: Service name or partial match (e.g. 'checkout-confirm', 'seat-map').
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found.", "available": [s.name for s in SERVICE_REGISTRY]})

    dep = _SERVICE_DEPENDENCIES.get(svc.name)
    if not dep:
        return json.dumps({"service": svc.name, "message": "No dependency data available."})

    return json.dumps({
        "service": svc.name,
        "description": dep["description"],
        "calls_services": dep["calls"],
        "called_by_services": dep["called_by"],
        "external_dependencies": dep["external"],
        "is_orchestrator": len(dep["calls"]) > 2,
        "tip": (
            "This service is a checkout orchestrator — good candidate for combining calls."
            if svc.name == "SC-API-Checkout-Confirm"
            else None
        ),
    }, indent=2)


def tool_get_all_dependencies() -> str:
    """Get the complete cross-service dependency graph for all 11 services.

    Useful for understanding the full architecture, planning refactors,
    or identifying which services are involved in a given flow.
    """
    return json.dumps({
        "dependency_map": _SERVICE_DEPENDENCIES,
        "summary": {
            "total_services": len(_SERVICE_DEPENDENCIES),
            "orchestrators": [
                name for name, d in _SERVICE_DEPENDENCIES.items()
                if len(d["calls"]) > 2
            ],
            "leaf_services": [
                name for name, d in _SERVICE_DEPENDENCIES.items()
                if len(d["calls"]) == 0 and name != "SC-UI-ServiceCenterMain"
            ],
        },
    }, indent=2)


def tool_get_ui_api_mapping(store_or_flow: str = "") -> str:
    """Map UI Zustand stores to their Apollo hooks, GraphQL operations, and backend services.

    Answers questions like:
    - "Which store manages seat selection?"
    - "What GraphQL mutations does the checkout flow use?"
    - "Which services does orderStore depend on?"

    Args:
        store_or_flow: Optional filter — a store name (e.g. 'cartStore'), a flow name
                       (e.g. 'checkout', 'seat_selection'), or empty for all mappings.
    """
    if not store_or_flow:
        return json.dumps({"mappings": _UI_API_MAPPING, "total": len(_UI_API_MAPPING)}, indent=2)

    q = store_or_flow.lower().replace("-", "_").replace(" ", "_")
    matches = [
        m for m in _UI_API_MAPPING
        if q in m["store"].lower()
        or q in m["flow"].lower()
        or any(q in svc.lower() for svc in m["services"])
        or any(q in op.lower() for op in m["graphql_operations"])
    ]

    if not matches:
        return json.dumps({
            "error": f"No mapping found for '{store_or_flow}'.",
            "available_stores": [m["store"] for m in _UI_API_MAPPING],
            "available_flows": list({m["flow"] for m in _UI_API_MAPPING}),
        })

    return json.dumps({"query": store_or_flow, "mappings": matches, "total": len(matches)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# LIVE API CALLING TOOLS
# ═══════════════════════════════════════════════════════════════════════

from src.utils.api_client import call_graphql, call_rest, introspect_service, check_service_health


def tool_call_service_api(
    service: str,
    query: str,
    variables: Optional[str] = None,
    allow_mutation: bool = False,
) -> str:
    """Call a live GraphQL API on one of the SC microservices and return the response.

    Args:
        service: Service name or partial match (e.g. 'searchpanel', 'create-cart').
        query: GraphQL query or mutation string.
        variables: Optional JSON string of variables (e.g. '{"id": "123"}').
        allow_mutation: Set true to allow mutation execution (blocked by default).
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found.", "available": [s.name for s in SERVICE_REGISTRY]})

    if not svc.has_graphql:
        return json.dumps({"error": f"Service '{svc.name}' does not expose a GraphQL API. Use call_rest_endpoint instead."})

    # Parse variables from JSON string
    vars_dict = None
    if variables:
        try:
            vars_dict = json.loads(variables)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in 'variables' parameter."})

    result = call_graphql(svc.name, query, variables=vars_dict, allow_mutation=allow_mutation)
    return json.dumps(result, indent=2)


def tool_call_rest_endpoint(
    service: str,
    method: str = "GET",
    path: str = "/",
    body: Optional[str] = None,
    allow_mutation: bool = False,
) -> str:
    """Call a live REST endpoint on one of the SC microservices and return the response.

    Args:
        service: Service name or partial match (e.g. 'token', 'searchpanel').
        method: HTTP method — GET, POST, PUT, DELETE, PATCH.
        path: URL path relative to service base (e.g. '/api/token').
        body: Optional JSON string for request body (POST/PUT/PATCH).
        allow_mutation: Set true to allow write methods (blocked by default).
    """
    svc = find_service(service)
    if not svc:
        return json.dumps({"error": f"Service '{service}' not found.", "available": [s.name for s in SERVICE_REGISTRY]})

    # Parse body from JSON string
    body_dict = None
    if body:
        try:
            body_dict = json.loads(body)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in 'body' parameter."})

    result = call_rest(svc.name, method, path, body=body_dict, allow_mutation=allow_mutation)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# ENHANCED FEATURE IMPACT ANALYSIS TOOLS
# ═══════════════════════════════════════════════════════════════════════


def tool_check_feature_flag_live(feature_key: str) -> str:
    """Check the live runtime state of a feature flag by querying SC-API-App-Config.

    Args:
        feature_key: Feature flag key to check (e.g. 'seat_selection', 'multi_city').
    """
    # Query the App-Config service for all feature flags
    query = "query { featureFlags { key enabled description } }"
    result = call_graphql("SC-API-App-Config", query, allow_mutation=False)

    if result.get("error"):
        return json.dumps({
            "feature_key": feature_key,
            "live_check": False,
            "error": result["error"],
            "hint": "Is SC-API-App-Config running? Check with: python server.py --transport sse",
        }, indent=2)

    data = result.get("data")
    if not data or "featureFlags" not in data:
        return json.dumps({
            "feature_key": feature_key,
            "live_check": False,
            "error": "Unexpected response format from App-Config service.",
            "raw": result,
        }, indent=2)

    flags = data["featureFlags"]
    key_lower = feature_key.lower().replace("-", "_").replace(" ", "_")

    matched_flags = [
        f for f in flags
        if key_lower in f["key"].lower().replace("-", "_")
    ]

    return json.dumps({
        "feature_key": feature_key,
        "live_check": True,
        "matched_flags": matched_flags,
        "all_flags_count": len(flags),
        "source": "SC-API-App-Config (live)",
        "service_url": result.get("url"),
        "latency_ms": result.get("duration_ms"),
    }, indent=2)


def tool_get_feature_impact_full(feature_name: str) -> str:
    """Full feature impact analysis: combines static code analysis with live service checks.

    Returns static analysis (affected services, resolvers, models, files, tests, flags)
    PLUS live status (feature flag state, service health, schema drift detection).

    Args:
        feature_name: Feature name to trace (e.g. 'seat_selection', 'passenger_type', 'baggage').
    """
    # 1. Run existing static analysis
    static_result = json.loads(tool_get_feature_impact(feature_name))

    # 2. Live feature flag check
    flag_result = json.loads(tool_check_feature_flag_live(feature_name))

    # 3. Health check for affected services
    affected_service_names = [s["name"] for s in static_result.get("services_affected", [])]
    service_health: list[dict] = []
    for svc_name in affected_service_names:
        health = check_service_health(svc_name)
        service_health.append(health)

    # 4. Schema drift detection — compare static resolvers vs live introspection
    schema_drift: list[dict] = []
    for svc_info in static_result.get("services_affected", []):
        svc_name = svc_info["name"]
        svc = find_service(svc_name)
        if not svc or not svc.has_graphql:
            continue

        introspection = introspect_service(svc_name)
        if introspection.get("error"):
            schema_drift.append({
                "service": svc_name,
                "status": "unreachable",
                "detail": introspection["error"],
            })
            continue

        # Compare static resolvers with live schema
        live_data = introspection.get("data")
        if live_data and "__schema" in live_data:
            live_types = {t["name"]: t for t in live_data["__schema"].get("types", [])}
            static_resolvers = [
                r for r in static_result.get("resolvers_affected", [])
                if r.get("service") == svc_name
            ]
            for resolver in static_resolvers:
                resolver_name = resolver.get("name", "")
                resolver_type = resolver.get("type", "Query")
                live_type = live_types.get(resolver_type)
                if live_type:
                    live_fields = [f["name"] for f in (live_type.get("fields") or [])]
                    if resolver_name not in live_fields:
                        schema_drift.append({
                            "service": svc_name,
                            "status": "drift",
                            "detail": f"Resolver '{resolver_name}' in static contract but missing from live schema.",
                        })

    # 5. Assemble full report
    full_report = {
        "feature": feature_name,
        "static_analysis": static_result,
        "live_status": {
            "feature_flag": flag_result,
            "services_reachable": service_health,
            "schema_drift": schema_drift,
        },
        "summary": {
            **static_result.get("summary", {}),
            "services_reachable_count": sum(1 for h in service_health if h.get("reachable")),
            "services_unreachable_count": sum(1 for h in service_health if not h.get("reachable")),
            "schema_drift_count": len([d for d in schema_drift if d.get("status") == "drift"]),
            "feature_flag_live": flag_result.get("live_check", False),
        },
    }

    return json.dumps(full_report, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# CANCEL & REFUND TOOLS
# ═══════════════════════════════════════════════════════════════════════

_REFUND_ELIGIBILITY_QUERY = """
query RetriveOrderRefundEligiblities($input: RefundEligiblitiesInput!) {
  RetriveOrderRefundEligiblities(input: $input) {
    type
    data {
      orderId
      refundStatus
      totalRefund {
        totalRefundAmounts {
          total { value currencyCode }
        }
        totalPaidAmount {
          total { value currencyCode }
        }
        totalUsedAmount {
          total { value currencyCode }
        }
        totalPenalty {
          total { currencyCode value }
        }
      }
      travelers {
        travelerId
        totalRefund {
          totalRefundAmounts {
            total { value currencyCode }
          }
          totalPaidAmount {
            total { value currencyCode }
          }
          totalUsedAmount {
            total { value currencyCode }
          }
          totalPenalty {
            total { currencyCode value }
          }
        }
        travelDocuments {
          travelDocumentId
          documentType
          status
          seatIds
          serviceIds
          refundAmounts {
            base { value currencyCode }
            taxes { value currencyCode code category }
            totalTaxes { value currencyCode }
            total { value currencyCode }
          }
          paidAmount {
            base { value currencyCode }
            taxes { value currencyCode code category }
            totalRefundableTax { value currencyCode }
            total { value currencyCode }
          }
          usedAmount {
            base { value currencyCode }
            taxes { value currencyCode code category }
            totalRefundableTax { value currencyCode }
            total { value currencyCode }
          }
          penalty { value currencyCode }
          refundMethodOptions {
            id
            paymentDetails {
              paymentMethod {
                paymentType
                vendorCode
                cardNumber
                expiryDate
              }
              amount { value currencyCode }
            }
          }
        }
      }
      refundProposalReferences {
        refundProposalId
      }
      nonEligibilityReasons {
        code
        title
      }
      dictionaries {
        currency { name decimalPlaces }
      }
    }
  }
}
"""

_CANCELLATION_AND_REFUND_MUTATION = """
mutation CancellationAndRefund($input: CancellationAndRefundInput!) {
  CancellationAndRefund(input: $input) {
    orderId
    totalRefund {
      totalRefundAmounts {
        total { value currencyCode }
      }
      totalPaidAmount {
        total { value currencyCode }
      }
      totalUsedAmount {
        total { value currencyCode }
      }
    }
    travelers {
      travelerId
      totalRefund {
        totalRefundAmounts {
          total { value currencyCode }
        }
        totalPaidAmount {
          total { value currencyCode }
        }
        totalUsedAmount {
          total { value currencyCode }
        }
      }
      travelDocuments {
        travelDocumentId
        documentType
        status
        refundAmounts {
          base { value currencyCode }
          taxes { value currencyCode code category }
          totalTaxes { value currencyCode }
          total { value currencyCode }
        }
        paidAmount {
          base { value currencyCode }
          taxes { value currencyCode code category }
          totalRefundableTax { value currencyCode }
          total { value currencyCode }
        }
        usedAmount {
          base { value currencyCode }
          taxes { value currencyCode code category }
          totalRefundableTax { value currencyCode }
          total { value currencyCode }
        }
        paymentDetails {
          paymentMethod {
            paymentType
            vendorCode
            cardNumber
            expiryDate
          }
          amount { value currencyCode }
        }
      }
    }
    dictionaries {
      currency { name decimalPlaces }
    }
    errors {
      code
      title
      detail
    }
  }
}
"""


def _call_cancel_refund_graphql(
    query: str,
    variables: dict,
    allow_mutation: bool = False,
) -> dict:
    """Send a GraphQL request to the APIM Cancel & Refund endpoint."""
    import httpx
    import time

    if not allow_mutation and query.strip().lower().startswith("mutation"):
        if not ALLOW_MUTATIONS:
            return {
                "endpoint": "cancelAndRefund",
                "error": "Mutations are blocked by default. Set ALLOW_MUTATIONS=true or pass allow_mutation=true.",
            }

    url = APIM_CANCEL_REFUND_URL
    payload = {"query": query, "variables": variables}

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
            "endpoint": "cancelAndRefund",
            "url": url,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "data": body.get("data") if isinstance(body, dict) else None,
            "errors": body.get("errors") if isinstance(body, dict) else None,
            "raw_body": body if not isinstance(body, dict) else None,
        }

    except httpx.TimeoutException:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"endpoint": "cancelAndRefund", "url": url, "error": "Request timed out.", "duration_ms": duration_ms}
    except httpx.ConnectError:
        return {"endpoint": "cancelAndRefund", "url": url, "error": f"Connection refused — is APIM reachable at {url}?"}
    except httpx.HTTPError as exc:
        return {"endpoint": "cancelAndRefund", "url": url, "error": str(exc)}


def tool_check_refund_eligibility(order_id: str, last_name: str) -> str:
    """Check if an order is eligible for cancellation and refund.

    Uses the orderId (from Retrieve Order API) and passenger lastName to query
    the APIM cancelAndRefund endpoint for refund eligibility.

    Args:
        order_id: The order ID from the Retrieve Order API (e.g. '8LUTXS').
        last_name: The passenger's last name on the booking.
    """
    variables = {
        "input": {
            "targetAction": "cancelAndRefund",
            "orderId": order_id,
            "lastName": last_name,
            "isEligible": True,
        }
    }

    result = _call_cancel_refund_graphql(_REFUND_ELIGIBILITY_QUERY, variables)

    # Parse eligibility from the response
    data = result.get("data")
    eligibility_info = {
        "order_id": order_id,
        "last_name": last_name,
        "endpoint": result.get("url"),
        "status": result.get("status"),
        "duration_ms": result.get("duration_ms"),
    }

    if result.get("error"):
        eligibility_info["eligible"] = False
        eligibility_info["error"] = result["error"]
        return json.dumps(eligibility_info, indent=2)

    if result.get("errors"):
        eligibility_info["eligible"] = False
        eligibility_info["graphql_errors"] = result["errors"]
        return json.dumps(eligibility_info, indent=2)

    if data and "RetriveOrderRefundEligiblities" in data:
        refund_data = data["RetriveOrderRefundEligiblities"].get("data", {})
        refund_status = refund_data.get("refundStatus")
        non_eligibility_reasons = refund_data.get("nonEligibilityReasons", [])

        eligibility_info["eligible"] = (
            refund_status not in ("NOT_ELIGIBLE", "INELIGIBLE")
            and len(non_eligibility_reasons) == 0
        )
        eligibility_info["refund_status"] = refund_status
        eligibility_info["total_refund"] = refund_data.get("totalRefund")
        eligibility_info["travelers"] = refund_data.get("travelers")
        eligibility_info["refund_proposal_references"] = refund_data.get("refundProposalReferences")
        eligibility_info["non_eligibility_reasons"] = non_eligibility_reasons
        eligibility_info["dictionaries"] = refund_data.get("dictionaries")
    else:
        eligibility_info["eligible"] = False
        eligibility_info["error"] = "Unexpected response structure."
        eligibility_info["raw_data"] = data

    return json.dumps(eligibility_info, indent=2)


def tool_cancel_and_refund(order_id: str, last_name: str, refund_proposal_ids: list[str]) -> str:
    """Execute cancellation and refund for an eligible order.

    This should only be called AFTER confirming eligibility via check_refund_eligibility.
    Uses the refundProposalIds returned from the eligibility check.

    Args:
        order_id: The order ID (e.g. '7QKLLB').
        last_name: The passenger's last name on the booking.
        refund_proposal_ids: List of refund proposal IDs from the eligibility check response.
    """
    variables = {
        "input": {
            "refundProposalIds": refund_proposal_ids,
            "orderId": order_id,
            "lastName": last_name,
        }
    }

    result = _call_cancel_refund_graphql(
        _CANCELLATION_AND_REFUND_MUTATION,
        variables,
        allow_mutation=True,
    )

    refund_info = {
        "order_id": order_id,
        "last_name": last_name,
        "refund_proposal_ids": refund_proposal_ids,
        "endpoint": result.get("url"),
        "status": result.get("status"),
        "duration_ms": result.get("duration_ms"),
    }

    if result.get("error"):
        refund_info["success"] = False
        refund_info["error"] = result["error"]
        return json.dumps(refund_info, indent=2)

    if result.get("errors"):
        refund_info["success"] = False
        refund_info["graphql_errors"] = result["errors"]
        return json.dumps(refund_info, indent=2)

    data = result.get("data")
    if data and "CancellationAndRefund" in data:
        cancellation_data = data["CancellationAndRefund"]
        errors = cancellation_data.get("errors", [])

        refund_info["success"] = len(errors) == 0
        refund_info["cancellation_result"] = cancellation_data
        if errors:
            refund_info["cancellation_errors"] = errors
    else:
        refund_info["success"] = False
        refund_info["error"] = "Unexpected response structure."
        refund_info["raw_data"] = data

    return json.dumps(refund_info, indent=2)
