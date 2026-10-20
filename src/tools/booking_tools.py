"""Booking Flow MCP Tools — 10 tools for the Create Booking Agent.

Each tool auto-handles JWT token acquisition via the APIM client
and embeds the exact GraphQL query/mutation from the Postman collection.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from config import ALLOW_MUTATIONS, logger
from src.utils.apim_client import call_apim_graphql


# ═══════════════════════════════════════════════════════════════════════
# Input Validation Helpers
# ═══════════════════════════════════════════════════════════════════════

_VALID_PAX_TYPES = {"ADT", "CHD", "INF", "YTH", "UNN"}
_VALID_TRIP_TYPES = {"OW", "RT", "MC"}
_VALID_FARE_TYPES = {"Economy", "Business", "First"}
_AIRPORT_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _validate_airport_code(code: str, field_name: str) -> str:
    """Validate and normalize an IATA airport code."""
    code = code.strip().upper()
    if not _AIRPORT_CODE_RE.match(code):
        raise ValueError(
            f"Invalid {field_name}: '{code}'. Must be a 3-letter IATA airport code (e.g. HEL, LHR, JFK)."
        )
    return code


def _validate_date(date_str: str, field_name: str, allow_past: bool = False) -> str:
    """Validate a date string in YYYY-MM-DD format."""
    date_str = date_str.strip()
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"Invalid {field_name}: '{date_str}'. Must be in YYYY-MM-DD format."
        )
    if not allow_past and dt.date() < datetime.now().date():
        raise ValueError(
            f"Invalid {field_name}: '{date_str}' is in the past. Provide a future date."
        )
    return date_str


def _validate_passengers(passengers: list[dict[str, str]]) -> list[dict[str, str]]:
    """Validate passenger type codes."""
    if not passengers or not isinstance(passengers, list):
        raise ValueError("At least one passenger is required.")
    for i, pax in enumerate(passengers):
        pax_type = pax.get("passengerTypeCode", "").upper()
        if pax_type not in _VALID_PAX_TYPES:
            raise ValueError(
                f"Invalid passengerTypeCode '{pax_type}' for passenger {i+1}. "
                f"Valid types: {', '.join(sorted(_VALID_PAX_TYPES))}"
            )
    return passengers


# ═══════════════════════════════════════════════════════════════════════
# 1. SearchFlights
# ═══════════════════════════════════════════════════════════════════════

_SEARCH_FLIGHTS_QUERY = """
query Offer($searchInput: OfferRequest!) {
  getOffers(OfferRequest: $searchInput) {
    warnings
    response {
      dataLists
      connections {
        departureLocationCode
        arrivalLocationCode
        flightProducts {
          ranking
          duration
          FormatedDuration
          daysIndication
          segments {
            flightId
            connectionTime
            formatedConnectionTime
          }
          flightSKUs {
            SKUId
            SKUCode
            SKUName
            cabinClass
            lowestFairIndication
            seatsLeft
            prices {
              unitPrices {
                paxID
                prices {
                  baseAmount
                  totalAmount
                  curCode
                  totalTaxAmount
                  taxSummary {
                    amount
                    taxCode
                    taxName
                  }
                  discount {
                    discountCode
                    originalTotal
                  }
                }
              }
              totalPrices {
                baseAmount
                totalAmount
                curCode
                totalTaxAmount
                taxSummary {
                  amount
                  taxCode
                  taxName
                }
                discount {
                  discountCode
                  originalTotal
                }
              }
            }
            services {
              flightId
              services
            }
            restrictions
          }
        }
      }
    }
  }
}
"""


def tool_search_flights(
    trip_type: str,
    departure_location: str,
    arrival_location: str,
    departure_date: str,
    passengers: list[dict[str, str]],
    fare_type: str = "Economy",
    return_date: str = "",
) -> str:
    """Search for flight offers between two locations.

    This is the first step in the booking flow. Returns available flights
    with SKU IDs needed to create a cart.

    Args:
        trip_type: Trip type code — 'OW' (one-way), 'RT' (round-trip), or 'MC' (multi-city).
        departure_location: Departure airport code (e.g. 'HEL', 'JFK', 'LHR').
        arrival_location: Arrival airport code (e.g. 'JFK', 'HEL', 'DEL').
        departure_date: Departure date in YYYY-MM-DD format (e.g. '2026-07-24').
        passengers: List of passenger dicts with 'passengerTypeCode' and 'discountCode'.
                    Example: [{"passengerTypeCode": "ADT", "discountCode": "ADT"}]
        fare_type: Fare cabin type (default 'Economy'). Options: 'Economy', 'Business', 'First'.
        return_date: Return date for round-trip in YYYY-MM-DD format. Required if trip_type is 'RT'.
    """
    # ── Input Validation ──
    trip_type = trip_type.strip().upper()
    if trip_type not in _VALID_TRIP_TYPES:
        return json.dumps({"error": f"Invalid trip_type '{trip_type}'. Must be one of: {', '.join(sorted(_VALID_TRIP_TYPES))}"})

    try:
        departure_location = _validate_airport_code(departure_location, "departure_location")
        arrival_location = _validate_airport_code(arrival_location, "arrival_location")
        _validate_date(departure_date, "departure_date")
        _validate_passengers(passengers)
        if trip_type == "RT":
            if not return_date:
                return json.dumps({"error": "return_date is required for round-trip (RT) flights."})
            _validate_date(return_date, "return_date")
    except ValueError as e:
        return json.dumps({"error": str(e)})

    if fare_type not in _VALID_FARE_TYPES:
        return json.dumps({"error": f"Invalid fare_type '{fare_type}'. Must be one of: {', '.join(sorted(_VALID_FARE_TYPES))}"})

    logger.info(f"SearchFlights: {departure_location}→{arrival_location} on {departure_date} ({trip_type}, {len(passengers)} pax)")

    trips = [
        {
            "departureLocationCode": departure_location,
            "arrivalLocationCode": arrival_location,
            "departureDateTime": departure_date,
            "isRequestedBound": True,
        }
    ]
    if trip_type == "RT" and return_date:
        trips.append(
            {
                "departureLocationCode": arrival_location,
                "arrivalLocationCode": departure_location,
                "departureDateTime": return_date,
                "isRequestedBound": True,
            }
        )

    variables = {
        "searchInput": {
            "tripType": trip_type,
            "trips": trips,
            "selectedFlightProductId": None,
            "passengers": passengers,
            "fareTypes": fare_type,
        }
    }

    result = call_apim_graphql("/shop/flights", _SEARCH_FLIGHTS_QUERY, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 2. CreateCart
# ═══════════════════════════════════════════════════════════════════════

_CREATE_CART_MUTATION = """
mutation CreateCart($input: CreateCart!) {
  createCart(requestBody: $input) {
    dataList {
      aircraft
      airline
      bookingStatus
      country
      currency
      flights
      location
      meal
      tax
    }
    response {
      cartId
      checkoutId
      airofferid
      airlinecode
      passengers {
        passengerTypeCode
        passengerId
        oldPassengerId
      }
      air {
        price {
          unitPrices {
            travelerIds
            prices {
              base
              total
              taxes {
                code
                currencyCode
                value
              }
              totalTaxes
              fees {
                value
                currencyCode
                nature
              }
              totalFees
            }
          }
          totalPrices {
            base
            total
            totalTaxes
            fees {
              value
              currencyCode
              nature
            }
            totalFees
          }
        }
        connections {
          originLocationCode
          destinationLocationCode
          flights {
            id
            cabin
            bookingClass
            statusCode
            connectionTime
            fareFamilyCode
          }
          duration
        }
      }
    }
    warnings {
      severity
      message
      code
    }
  }
}
"""


def tool_create_cart(
    sku_ids: list[str],
    airline_id: str = "AY",
    agent_id: str = "MCP-Agent",
) -> str:
    """Create a booking cart from selected flight offer SKU IDs.

    Call this after SearchFlights. Pass the SKUId(s) from the search results.
    Returns cartId, checkoutId, and passenger IDs needed for subsequent steps.

    Args:
        sku_ids: List of SKU IDs from SearchFlights results (e.g. ['SKU-123']).
        airline_id: Airline code (default 'AY').
        agent_id: Agent identifier (default 'MCP-Agent').
    """
    variables = {
        "input": {
            "skuIds": sku_ids,
            "airlineId": airline_id,
            "agentId": agent_id,
        }
    }

    result = call_apim_graphql("/create-cart", _CREATE_CART_MUTATION, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 3. UpdatePassengers
# ═══════════════════════════════════════════════════════════════════════

_UPDATE_PASSENGERS_MUTATION = """
mutation Mutation($passengerInput: AddPassengerInput!) {
  updatePassengerInformation(passengerInput: $passengerInput) {
    checkoutId
    passengers {
      id
      tid
      associatedPassengerId
      passengerTypeCode
      identityDetails {
        title
        firstName
        lastName
        nameType
        dateOfBirth
        gender
      }
      contactDetails {
        mobile {
          tid
          id
          isDefault
          category
          number
          countryCode
          purposes
          addresseeName
          countrycode
        }
        email {
          id
          tid
          isDefault
          category
          emailAddress
          purposes
        }
        landline {
          id
          tid
          isDefault
          category
          number
          countryCode
          purposes
          addresseeName
          countrycode
        }
        address {
          id
          tid
          isDefault
          category
          addresseeName
          lines
          countryCode
          stateCode
          cityName
          zipCode
          postalBox
          purposes
        }
        fax {
          id
          tid
          isDefault
          category
          number
          countryCode
          purposes
          addresseeName
          countrycode
        }
      }
      frequentFlyer {
        companyCode
        cardNumber
      }
      regulatoryDetails {
        id
        tid
        flightIds
        airlineCode
        regulatoryApisType
        regulatoryDocument {
          documentType
          number
          issuanceDate
          effectiveDate
          expiryDate
          issuanceLocation
          issuanceCountryCode
          applicableCountryCodes
          name {
            firstName
            middleName
            lastName
            title
            nameType
          }
          isPreferred
          nationalityCode
          gender
          birthDate
          remarks
          birthPlace
        }
      }
    }
  }
}
"""


def tool_update_passengers(
    checkout_id: str,
    passengers: list[dict[str, Any]],
) -> str:
    """Add or update passenger information for a checkout session.

    Call this after CreateCart. Each passenger dict must include 'id' (from CreateCart),
    'passengerTypeCode', and 'identityDetails' with name, DOB, gender, and title.
    At least one passenger must include 'contactDetails' with email and mobile.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        passengers: List of passenger objects. Each must have:
                    - id: passenger ID from CreateCart
                    - passengerTypeCode: 'ADT', 'CHD', or 'INF'
                    - identityDetails: {firstName, lastName, gender, nameType, dateOfBirth, title}
                    - contactDetails (optional): {email: [...], mobile: [...], address: [...]}
                    - associatedPassengerId (optional): for INF passengers, the ADT id they travel with
    """
    variables = {
        "passengerInput": {
            "checkoutId": checkout_id,
            "passengers": passengers,
        }
    }

    result = call_apim_graphql(
        "/checkout/passengers", _UPDATE_PASSENGERS_MUTATION, variables
    )
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 4. GetServiceCatalog
# ═══════════════════════════════════════════════════════════════════════

_GET_SERVICES_QUERY = """
query GetServicesCatalogue($checkoutId: String!, $params: ServiceQueryParams) {
  getServicesCatalogue(checkoutId: $checkoutId, params: $params) {
    datalist {
      aircraft
      airline
      country
      currency
      flights
      location
      tax
    }
    flights {
      destination
      id
      origin
    }
    passengersV3 {
      id
      type
      title
      firstName
      lastName
    }
    serviceTypes {
      unitType
      unitLevel
      categoryTypes
    }
    connections {
      destination
      origin
      passengers {
        id
        firstName
        lastName
        type
        SKUs {
          code
          name
          id
          level
          oncePerPassengerPerFlight
          typeLevel
          ignoredFlightsIfBoundLevel
          price {
            totalPrices {
              baseAmount
              currencyCode
              totalAmount
              totalFees
              totalSurcharges
              totalTaxes
            }
            unitPrices {
              flightIds
              prices {
                baseAmount
                currencyCode
                totalAmount
                totalFees
                totalSurcharges
                totalTaxes
              }
              travelerIds
            }
          }
          quotaStatus
          quota
          serviceCapping
          serviceCategory
          serviceRanking
          unitCapping
          unitRanking
          unitType
        }
        segments {
          flightId
          SKUs {
            code
            id
            level
            name
            oncePerPassengerPerFlight
            typeLevel
            ignoredFlightsIfBoundLevel
            price {
              totalPrices {
                baseAmount
                currencyCode
                totalAmount
                totalFees
                totalSurcharges
                totalTaxes
              }
              unitPrices {
                flightIds
                prices {
                  baseAmount
                  currencyCode
                  totalAmount
                  totalFees
                  totalSurcharges
                  totalTaxes
                }
                travelerIds
              }
            }
            quotaStatus
            quota
            serviceCapping
            serviceCategory
            serviceRanking
            unitCapping
            unitRanking
            unitType
          }
        }
      }
    }
  }
}
"""


def tool_get_service_catalog(
    checkout_id: str,
    promotion_code: str = "",
) -> str:
    """Retrieve the ancillary services catalogue (bags, meals, wifi, etc.) for a checkout.

    Call this after UpdatePassengers to see available ancillary services.
    Returns service SKUs per passenger per segment with pricing.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        promotion_code: Optional promotion code (e.g. 'SCUISEATP').
    """
    variables: dict[str, Any] = {"checkoutId": checkout_id}
    if promotion_code:
        variables["params"] = {"promotionCode": promotion_code}

    result = call_apim_graphql("/services", _GET_SERVICES_QUERY, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 5. GetSeatMap
# ═══════════════════════════════════════════════════════════════════════

_GET_SEATMAP_QUERY = """
query ExampleQuery($input: SeatMapInput!, $params: SeatQueryParams) {
  getSeatMap(input: $input, params: $params) {
    warnings {
      code
      detail
    }
    data {
      services
      flight {
        marketingAirlineCode
        marketingFlightNumber
        departure {
          locationCode
        }
        arrival {
          locationCode
        }
        aircraftCode
        aircraftConfigurationVersion
        cabin
      }
      seatmaps {
        computedCoordinates
        decks {
          deckType
          deckDimensions {
            width
            length
            exitRowsX
            startWingsX
            endWingsX
          }
          firstAvailableSeat {
            seatNumber
            x
          }
          cheapestSeat {
            cabin
            seatNumber
            travelers {
              id
              seatCharacteristicsCodes
              seatAvailabilityStatus
              prices {
                base
                total
                currencyCode
                totalTaxes
                discount {
                  originalTotal
                  discountCode
                }
              }
            }
            coordinates {
              x
              y
            }
          }
          facilities {
            code
            column
            row
            position
          }
          seats {
            cabin
            seatNumber
            travelers {
              id
              seatAvailabilityStatus
              seatCharacteristicsCodes
              packServiceIds
              prices {
                base
                currencyCode
                total
                totalTaxes
                discount {
                  discountCode
                  originalTotal
                }
              }
            }
            coordinates {
              x
              y
            }
          }
        }
      }
    }
    dataLists
  }
}
"""


def tool_get_seat_map(
    checkout_id: str,
    flight_id: str,
    promotion_code: str = "",
) -> str:
    """Retrieve the seat map for a specific flight in the checkout.

    Returns seat availability, pricing, and characteristics for all seats
    on the aircraft. Use this to show the agent available seats before assigning.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        flight_id: The flight segment ID (from CreateCart connections.flights[].id).
        promotion_code: Optional promotion code (e.g. 'SCUISEATP').
    """
    variables: dict[str, Any] = {
        "input": {
            "checkoutId": checkout_id,
            "flightId": flight_id,
        }
    }
    if promotion_code:
        variables["params"] = {"promotionCode": promotion_code}

    result = call_apim_graphql("/seatmap", _GET_SEATMAP_QUERY, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 6. AddSeats
# ═══════════════════════════════════════════════════════════════════════

_ADD_SEATS_MUTATION = """
mutation AddSeat($input: SeatInput!) {
  addSeat(input: $input) {
    data {
      seats {
        id
        flightId
        seat {
          travelerId
          seatNumber
          isExempted
          isChargeable
          seatCharacteristics {
            code
          }
        }
      }
      services {
        travelerId
        quantity
        id
        flightIds
        descriptions {
          type
          content
        }
      }
    }
  }
}
"""


def tool_add_seats(
    checkout_id: str,
    traveller: list[dict[str, Any]],
) -> str:
    """Assign seats to passengers for a checkout.

    Call this after GetSeatMap to assign specific seats to passengers.
    Each traveller entry maps a passenger to seat(s) on flight(s).

    Args:
        checkout_id: The checkoutId from CreateCart response.
        traveller: List of seat assignments. Each item has:
                   - id: passenger ID
                   - seat: list of {flightId, seat, bundleId (optional)}
                   Example: [{"id": "P1", "seat": [{"flightId": "FL1", "seat": "12A"}]}]
    """
    variables = {
        "input": {
            "checkoutId": checkout_id,
            "traveller": traveller,
        }
    }

    result = call_apim_graphql("/seat/services", _ADD_SEATS_MUTATION, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 7. AddAncillaries
# ═══════════════════════════════════════════════════════════════════════

_ADD_SERVICES_MUTATION = """
mutation AddService($input: ServicesInput!) {
  addService(input: $input) {
    data {
      id
      descriptions {
        type
        content
      }
      flightIds
      travelerId
      quantity
    }
    dataLists
  }
}
"""


def tool_add_ancillaries(
    checkout_id: str,
    traveller: list[dict[str, Any]],
) -> str:
    """Add ancillary services (bags, meals, wifi, etc.) to a checkout.

    Call this after GetServiceCatalog. Each traveller entry maps a passenger
    to selected service SKU IDs with quantities.

    Args:
        checkout_id: The checkoutId from CreateCart response.
        traveller: List of service selections. Each item has:
                   - id: passenger ID
                   - services: list of {id: service_SKU_id, quantity: int}
                   Example: [{"id": "P1", "services": [{"id": "SKU-BAG-1", "quantity": 1}]}]
    """
    variables = {
        "input": {
            "checkoutId": checkout_id,
            "traveller": traveller,
        }
    }

    result = call_apim_graphql("/seat/services", _ADD_SERVICES_MUTATION, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 8. RetrieveCart
# ═══════════════════════════════════════════════════════════════════════

_RETRIEVE_CART_QUERY = """
query RetrieveCart($checkoutId: String!) {
  retrieveCart(checkoutID: $checkoutId) {
    response {
      checkoutID
      passengers {
        identityDetails {
          firstName
          lastName
          isPreferred
          title
          dateOfBirth
          nameType
          accompanyingTravelerId
        }
        air {
          price {
            totalPrices {
              base {
                value
                currencyCode
              }
              total {
                value
                currencyCode
              }
              taxes {
                value
                currencyCode
                code
              }
              totalTaxes {
                value
                currencyCode
              }
              fees {
                value
                currencyCode
                nature
              }
              totalFees {
                value
                currencyCode
              }
              discount {
                originalBase
                originalTotal
                originalTotalTaxes
                discountCode
                discountCodes
              }
            }
          }
          connections {
            originLocationCode
            destinationLocationCode
            duration
          }
        }
        seats {
          id
          flightId
          seatSelection {
            seatNumber
            isChargeable
          }
          statusCode
          price {
            totalPrices {
              base {
                value
                currencyCode
              }
              total {
                value
                currencyCode
              }
              totalTaxes {
                value
                currencyCode
              }
            }
          }
        }
        services {
          name
          code
          quantity
          type
          flightIds
          statusCode
          parameters {
            key
            value
          }
          travelerId
          isChargeable
          price {
            totalPrices {
              base {
                value
                currencyCode
              }
              total {
                value
                currencyCode
              }
              totalTaxes {
                value
                currencyCode
              }
            }
          }
        }
        price {
          totalPrices {
            base {
              value
              currencyCode
            }
            total {
              value
              currencyCode
            }
            totalTaxes {
              value
              currencyCode
            }
            totalFees {
              value
              currencyCode
            }
            discount {
              originalBase
              originalTotal
              originalTotalTaxes
              discountCode
              discountCodes
            }
          }
        }
        id
        passengerType
      }
      dataList {
        location
        flights
        currency
        bookingStatus
        airline
        country
        aircraft
        tax
        meal
      }
    }
  }
}
"""


def tool_retrieve_cart(checkout_id: str) -> str:
    """Retrieve the full cart state for review before confirmation.

    Returns all passengers, selected flights, seats, services, and pricing.
    Use this to verify the booking details before calling ConfirmBooking.

    Args:
        checkout_id: The checkoutId from CreateCart response.
    """
    variables = {"checkoutId": checkout_id}

    result = call_apim_graphql("/cart/retrieve", _RETRIEVE_CART_QUERY, variables)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 9. ConfirmBooking
# ═══════════════════════════════════════════════════════════════════════

_CONFIRM_BOOKING_MUTATION = """
mutation ConfirmCheckout($confirmRequest: CheckoutConfirmRequest!) {
  ConfirmCheckout(CheckoutConfirmRequest: $confirmRequest) {
    id
    creationDateTime
    expirationDateTime
    paymentTimeLimit
    air {
      price {
        unitPrices {
          travelerIds
          flightIds
          prices {
            base {
              value
              currencyCode
            }
            total {
              value
              currencyCode
            }
            taxes {
              value
              currencyCode
              code
            }
            totalTaxes {
              value
              currencyCode
            }
            totalRefundableTaxes {
              value
              currencyCode
            }
            fees {
              value
              currencyCode
              nature
            }
            totalFees {
              value
              currencyCode
            }
          }
        }
        totalPrices {
          base {
            value
            currencyCode
          }
          total {
            value
            currencyCode
          }
          totalTaxes {
            value
            currencyCode
          }
          totalRefundableTaxes {
            value
            currencyCode
          }
          totalFees {
            value
            currencyCode
          }
        }
      }
      connections {
        originLocationCode
        destinationLocationCode
        flights {
          id
          cabin
          bookingClass
          statusCode
          connectionTime
          fareFamilyCode
        }
        duration
      }
    }
    passengers {
      passengerTypeCode
      id
      identityDetails {
        firstName
        lastName
        title
        nameType
        isPreferred
        dateOfBirth
        accompanyingTravelerId
      }
    }
    services {
      name
      quantity
      flightIds
      statusCode
      parameters {
        code
        value
      }
      travelerId
      isChargeable
    }
    remarks {
      type
      text
    }
    dataList
  }
}
"""


def tool_confirm_booking(checkout_id: str) -> str:
    """Confirm the booking and create an order (generates PNR).

    This is the final step in the booking flow. Call this after all passengers,
    seats, and services have been added and the cart has been reviewed.
    Returns the orderId and booking confirmation details.

    IMPORTANT: This action is irreversible. Ensure the cart is complete before calling.

    Args:
        checkout_id: The checkoutId from CreateCart response.
    """
    # ── Mutation Safety Guard ──
    if not ALLOW_MUTATIONS:
        logger.warning(f"ConfirmBooking BLOCKED for checkout {checkout_id} — ALLOW_MUTATIONS=false")
        return json.dumps({
            "error": "Booking confirmation is disabled. ALLOW_MUTATIONS is set to false.",
            "detail": "This is a safety guard to prevent accidental PNR creation. "
                       "Set ALLOW_MUTATIONS=true in your .env file to enable this operation.",
            "checkout_id": checkout_id,
        })

    logger.info(f"ConfirmBooking: creating PNR for checkout {checkout_id}")

    variables = {
        "confirmRequest": {
            "checkoutID": checkout_id,
        }
    }

    result = call_apim_graphql(
        "/checkoutConfirm", _CONFIRM_BOOKING_MUTATION, variables
    )
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 10. RetrieveOrder
# ═══════════════════════════════════════════════════════════════════════

_RETRIEVE_ORDER_QUERY = """
query retrieveOrder($orderId: String) {
  retrieveOrder(orderID: $orderId) {
    response {
      id
      creationDateTime
      pnrId
      expirationDateTime
      paymentTimeLimit
      price {
        unitPrices {
          travelerIds
          flightIds
          prices {
            base {
              value
              currencyCode
            }
            total {
              value
              currencyCode
            }
            taxes {
              value
              currencyCode
              code
            }
            totalTaxes {
              value
              currencyCode
            }
            totalRefundableTaxes {
              value
              currencyCode
            }
            fees {
              value
              currencyCode
              nature
            }
            totalFees {
              value
              currencyCode
            }
          }
        }
        totalPrices {
          base {
            value
            currencyCode
          }
          total {
            value
            currencyCode
          }
          totalTaxes {
            value
            currencyCode
          }
          totalRefundableTaxes {
            value
            currencyCode
          }
          totalFees {
            value
            currencyCode
          }
        }
      }
      connections {
        originLocationCode
        destinationLocationCode
        flights {
          id
          cabin
          bookingClass
          statusCode
          connectionTime
          fareFamilyCode
        }
        duration
      }
      passengers {
        passengerTypeCode
        id
        identityDetails {
          firstName
          lastName
          title
          nameType
          isPreferred
          dateOfBirth
          accompanyingTravelerId
        }
        contactDetails {
          mobile {
            countryCode
            number
            purpose
          }
          landline {
            countryCode
            number
            purpose
          }
          email {
            emailAddress
            purpose
          }
          address {
            addresseeName
            lines
            zipCode
            countryCode
            cityName
            stateCode
            postalBox
            purpose
          }
        }
        emergencyContactDetails {
          mobile {
            countryCode
            number
            purpose
          }
          landline {
            countryCode
            number
            purpose
          }
        }
      }
      services {
        name
        code
        description
        quantity
        categoryType
        type
        flightIds
        statusCode
        parameters {
          code
          value
        }
        travelerId
        isChargeable
      }
      seats {
        id
        flightId
        statusCode
        seatSelections {
          seatNumber
          travelerId
          isChargeable
        }
      }
      remarks {
        type
        text
      }
      eligibilities {
        acknowledge {
          airBoundId
          disruption {
            isEligible
            nonEligibilityReasons {
              code
              title
            }
          }
          waitlistConfirmation {
            isEligible
            nonEligibilityReasons {
              code
              title
            }
          }
          seats {
            isEligible
            nonEligibilityReasons {
              code
              title
            }
          }
        }
        cancel {
          isEligible
        }
        cancelAndRefund {
          isEligible
          nonEligibilityReasons {
            code
            title
          }
        }
        change {
          airBoundId
          flightIds
          isEligible
          nonEligibilityReasons {
            code
            title
          }
          nonEligibilityReason
          isPenaltyApplied
          isRouteChangeAllowed
          waiverCodes
        }
      }
      paymentInfo {
        id
        paymentType
        amount
        currencyCode
        ... on CardPayment {
          holderName
          cardNumber
          authorization
        }
      }
      dataList
    }
  }
}
"""


def tool_retrieve_order(order_id: str) -> str:
    """Retrieve a confirmed booking order by its order ID.

    Call this after ConfirmBooking to get the full order details including
    PNR, passengers, flights, services, seats, payment info, and eligibilities
    (cancel, change, refund).

    Args:
        order_id: The order ID from ConfirmBooking response (e.g. '8LUTXS').
    """
    variables = {"orderId": order_id}

    result = call_apim_graphql("/orders/retrieve", _RETRIEVE_ORDER_QUERY, variables)
    return json.dumps(result, indent=2)
