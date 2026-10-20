"""Refund Agent tools — Cancel & Refund GraphQL API via APIM.

Two tools:
  1. check_refund_eligibility — read-only query (RetriveOrderRefundEligiblities)
  2. cancel_and_refund        — IRREVERSIBLE mutation (CancellationAndRefund),
                                blocked unless ALLOW_MUTATIONS=true
"""

from __future__ import annotations

import json
import re

from config import ALLOW_MUTATIONS, APIM_REFUND_PATH, logger
from src.utils.apim_client import call_apim_graphql

_PNR_PATTERN = re.compile(r"^[A-Z0-9]{6}$")

_MONEY = "total { value currencyCode }"

_REFUND_ELIGIBILITY_QUERY = f"""
query RetriveOrderRefundEligiblities($input: RefundEligiblitiesInput!) {{
  RetriveOrderRefundEligiblities(input: $input) {{
    type
    data {{
      orderId
      refundStatus
      totalRefund {{
        totalRefundAmounts {{ {_MONEY} }}
        totalPaidAmount {{ {_MONEY} }}
        totalUsedAmount {{ {_MONEY} }}
        totalPenalty {{ {_MONEY} }}
      }}
      travelers {{
        travelerId
        totalRefund {{
          totalRefundAmounts {{ {_MONEY} }}
          totalPaidAmount {{ {_MONEY} }}
          totalUsedAmount {{ {_MONEY} }}
          totalPenalty {{ {_MONEY} }}
        }}
        travelDocuments {{
          travelDocumentId
          documentType
          status
          refundAmounts {{ {_MONEY} }}
          penalty {{ value currencyCode }}
          refundMethodOptions {{
            id
            paymentDetails {{
              paymentMethod {{ paymentType vendorCode }}
              amount {{ value currencyCode }}
            }}
          }}
        }}
      }}
      refundProposalReferences {{ refundProposalId }}
      nonEligibilityReasons {{ code title }}
    }}
  }}
}}
"""

_CANCEL_AND_REFUND_MUTATION = f"""
mutation CancellationAndRefund($input: CancellationAndRefundInput!) {{
  CancellationAndRefund(input: $input) {{
    orderId
    totalRefund {{
      totalRefundAmounts {{ {_MONEY} }}
      totalPaidAmount {{ {_MONEY} }}
      totalUsedAmount {{ {_MONEY} }}
    }}
    travelers {{
      travelerId
      travelDocuments {{
        travelDocumentId
        documentType
        status
        refundAmounts {{ {_MONEY} }}
        paymentDetails {{
          paymentMethod {{ paymentType vendorCode }}
          amount {{ value currencyCode }}
        }}
      }}
    }}
    errors {{ code title detail }}
  }}
}}
"""


def _normalize_pnr(order_id: str) -> str:
    pnr = (order_id or "").strip().upper()
    if not _PNR_PATTERN.match(pnr):
        raise ValueError(f"order_id must be a 6-character alphanumeric PNR, got '{order_id}'.")
    return pnr


def _require_last_name(last_name: str) -> str:
    name = (last_name or "").strip()
    if not name:
        raise ValueError("last_name is required.")
    return name


def tool_check_refund_eligibility(order_id: str, last_name: str) -> str:
    """Check whether an order can be cancelled and refunded. Read-only.

    Returns refundStatus, refund/paid/used/penalty totals, per-traveler breakdown,
    refundProposalReferences (needed by cancel_and_refund) and nonEligibilityReasons.
    """
    try:
        variables = {
            "input": {
                "targetAction": "cancelAndRefund",
                "orderId": _normalize_pnr(order_id),
                "lastName": _require_last_name(last_name),
                "isEligible": True,
            }
        }
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    result = call_apim_graphql(APIM_REFUND_PATH, _REFUND_ELIGIBILITY_QUERY, variables)
    return json.dumps(result, indent=2)


def tool_cancel_and_refund(order_id: str, last_name: str, refund_proposal_ids: list[str]) -> str:
    """Cancel an order and execute the refund. IRREVERSIBLE.

    refund_proposal_ids must come from a prior check_refund_eligibility call.
    """
    if not ALLOW_MUTATIONS:
        logger.warning(f"CancelAndRefund BLOCKED for order {order_id} — ALLOW_MUTATIONS=false")
        return json.dumps({
            "error": "Cancellation and refund is disabled. ALLOW_MUTATIONS is set to false.",
            "detail": "This is a safety guard to prevent accidental cancellations. "
                      "Set ALLOW_MUTATIONS=true to enable this operation.",
            "order_id": order_id,
        })

    try:
        pnr = _normalize_pnr(order_id)
        name = _require_last_name(last_name)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    proposal_ids = [p.strip() for p in (refund_proposal_ids or []) if p and p.strip()]
    if not proposal_ids:
        return json.dumps({
            "error": "refund_proposal_ids is required. Call check_refund_eligibility first "
                     "and pass refundProposalReferences[].refundProposalId.",
        })

    logger.info(f"CancelAndRefund: cancelling order {pnr} with {len(proposal_ids)} proposal(s)")
    variables = {"input": {"refundProposalIds": proposal_ids, "orderId": pnr, "lastName": name}}
    result = call_apim_graphql(APIM_REFUND_PATH, _CANCEL_AND_REFUND_MUTATION, variables)
    return json.dumps(result, indent=2)
