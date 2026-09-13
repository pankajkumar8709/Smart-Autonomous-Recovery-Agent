"""Bounded-autonomy governance layer.

Contract used by agent_graph.governance_node:
    check_bounded_autonomy(plan) -> (approved: bool, reason: str)

The agent may act autonomously only inside these bounds. Anything outside them
is a human-on-the-loop escalation — the graph loops to try a compliant
alternative, and escalates to END only once alternatives are exhausted.
"""
from typing import Any, Dict, Tuple

import config


def check_bounded_autonomy(plan: Dict[str, Any]) -> Tuple[bool, str]:
    if not plan:
        return False, "NO_PLAN"

    # 1. Compliance gate (domain specialization): never commit to a non-certified source.
    if config.REQUIRE_CDSCO_CERTIFIED and not plan.get("cdsco_certified", False):
        return False, f"COMPLIANCE_VETO: {plan.get('id')} is not CDSCO-certified"

    # 2. Quantity ceiling.
    qty = plan.get("quantity_kg", 0.0)
    if qty > config.MAX_AUTONOMOUS_QTY_KG:
        return False, (
            f"QTY_LIMIT: {qty}kg exceeds autonomous ceiling "
            f"{config.MAX_AUTONOMOUS_QTY_KG}kg"
        )

    # 3. Spend ceiling (total committed value).
    spend = plan.get("unit_cost_inr", 0.0) * qty
    if spend > config.MAX_AUTONOMOUS_SPEND_INR:
        return False, (
            f"SPEND_LIMIT: INR {spend:,.0f} exceeds autonomous ceiling "
            f"INR {config.MAX_AUTONOMOUS_SPEND_INR:,.0f}"
        )

    return True, f"within bounds (spend=INR {spend:,.0f}, qty={qty}kg)"
