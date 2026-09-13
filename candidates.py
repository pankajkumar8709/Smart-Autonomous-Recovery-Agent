"""Discovery-driven candidate generation (Phase 2).

The investigation step no longer holds a hardcoded option list. It reads the
live environment — vendors, lanes, inventory, demand — and builds every
candidate that *could* resolve the active disruption, pricing each one with a
real cost/carbon/transit computation over lane physics.

Anti-fake contract (BUILD_PLAN ground rule 2):
    Nothing hardcoded. Candidates, quantities, ETAs, and costs are discovered
    or computed from sandbox data (vendors, routes, calculator) at run time.

Everything here is PURE: dict in, dict out, no I/O. `investigate_node` performs
the sandbox reads and calls `build_candidates`, so this module stays unit-
testable without a server.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import config


# ---------------------------------------------------------------------------
# Deficit math — quantity is computed from real state, never a constant 5000
# ---------------------------------------------------------------------------
def compute_required_kg(
    inventory: Dict[str, Any],
    demand: Optional[Dict[str, Any]],
    surge_buffer_fraction: float = None,
) -> float:
    """Stock the facility must ADD to clear its floor under live demand.

        required = max(0, safety - current)                     # the deficit
                 + surge_buffer (safety * burn-ratio excess)    # demand headroom

    The surge buffer scales the *gap to the floor* by how far observed burn
    exceeds forecast burn — a mild surge adds headroom, a bigger surge adds
    more, and a 1.0 ratio (or no signal) adds nothing. Always >= 0.
    """
    if surge_buffer_fraction is None:
        surge_buffer_fraction = config.SURGE_BUFFER_FRACTION

    current = float(inventory.get("current_stock_kg", 0.0))
    safety = float(inventory.get("safety_stock_kg", 0.0))
    deficit = max(0.0, safety - current)

    surge = 1.0
    if demand:
        surge = float(demand.get("surge_ratio", 1.0))
    buffer_kg = safety * max(0.0, surge - 1.0) * surge_buffer_fraction

    return round(deficit + buffer_kg, 1)


# ---------------------------------------------------------------------------
# Lane pricing — deterministic physics, the honest math the UI can display
# ---------------------------------------------------------------------------
def lane_quote(lane: Dict[str, Any], quantity_kg: float) -> Dict[str, Any]:
    """Price one lane traversal. Returns transit_hours / cost_inr / carbon_kg.

        transit_hours = distance / avg_speed (+ fixed cold-chain handling delay
                        for temperature-controlled modes)
        cost_inr      = quantity * distance * cost_per_km_per_kg
        carbon_kg     = quantity * distance * co2_per_km_per_kg

    Deterministic and honest: the same inputs always produce the same numbers,
    and every field is traceable to a lane-physics input or a sandbox record.
    """
    distance = float(lane.get("distance_km", 0.0))
    speed = float(lane.get("avg_speed_kmh", 0.0)) or 1.0
    qty = max(0.0, float(quantity_kg))

    transit = distance / speed
    mode = str(lane.get("mode", "")).upper()
    if mode in ("REEFER_TRUCK", "AIR_CARGO"):
        transit += 2.0   # cold-chain handling: pre-cool + loadout at both ends

    cost = qty * distance * float(lane.get("cost_per_km_per_kg", 0.0))
    carbon = qty * distance * float(lane.get("co2_per_km_per_kg", 0.0))

    return {
        "transit_hours": round(transit, 2),
        "freight_cost_inr": round(cost, 2),
        "carbon_kg": round(carbon, 2),
        "distance_km": distance,
        "mode": mode,
    }


def _pick_lane(lanes: List[Dict[str, Any]], from_city: str, to_city: str) -> Optional[Dict[str, Any]]:
    """Cheapest lane by freight cost for the given city pair."""
    matches = [
        l for l in lanes
        if str(l.get("from_city", "")).lower() == str(from_city).lower()
        and str(l.get("to_city", "")).lower() == str(to_city).lower()
    ]
    if not matches:
        return None

    def freight(l: Dict[str, Any]) -> float:
        return float(l.get("distance_km", 0.0)) * float(l.get("cost_per_km_per_kg", 0.0))

    return min(matches, key=freight)


# ---------------------------------------------------------------------------
# Candidate construction from live environment data
# ---------------------------------------------------------------------------
def build_candidates(
    env: Dict[str, Any],
    reasons: List[str],
    invalidated_options: List[str],
    required_kg: float,
) -> List[Dict[str, Any]]:
    """Generate every candidate that could resolve the active disruption.

    Args:
        env: live sandbox data — {"inventory": {id: record}, "target": facility
             record, "shipment": record|None, "vendors": [records], "lanes":
             [records], "demand": record|None, "now": datetime (for ETA math)}.
        reasons: detect_node's disruption reasons (drives the resolves filter).
        invalidated_options: option ids excluded by governance/verify replans.
        required_kg: computed deficit + surge buffer (from compute_required_kg).

    Returns candidates with the exact schema the optimizer scores:
        id, type, quantity_kg, unit_cost_inr, transit_time_hours,
        carbon_per_kg_co2, cdsco_certified, mode, + action-specific fields.

    The uncertified vendor PASSES THROUGH here — the optimizer's feasibility
    filter (not the investigator) drops it, so the UI can show it was
    "investigated then rejected" (manual test plan bullet 3).
    """
    target = env.get("target") or {}
    facility_id = target.get("facility_id")
    lanes = env.get("lanes") or []
    vendors = env.get("vendors") or []
    other_facilities = [
        f for f in (env.get("inventory") or {}).values()
        if f.get("facility_id") != facility_id
    ]
    now = env.get("now") or datetime.now()
    shipment = env.get("shipment")

    breach = "SAFETY_STOCK_BREACH" in reasons
    surge = "DEMAND_SURGE" in reasons
    shipment_issue = any(str(r).startswith("SHIPMENT_") for r in reasons)

    resolves: set = set()
    if breach and required_kg > 0:
        # Stock physically below the floor and still unfilled — only actions
        # that ADD stock help (a 0-kg purchase/transfer is not a plan).
        resolves |= {"PURCHASE", "TRANSFER"}
    elif surge:
        # Stock above floor but demand spiked: ALLOCATE is valid precisely
        # because there IS stock to reserve; purchase/transfer add buffer.
        resolves |= {"ALLOCATE", "PURCHASE", "TRANSFER"}
    elif shipment_issue:
        # Pure shipment problem, stock fine: reroute is the natural fix.
        resolves |= {"REROUTE", "PURCHASE", "TRANSFER"}
    if not resolves and not (breach or surge or shipment_issue):
        # No recognizable reason at all (unclassified re-entry) — allow all four
        # types and let the optimizer + verify's RAW check sort it out.
        resolves = {"PURCHASE", "TRANSFER", "REROUTE", "ALLOCATE"}
    if shipment_issue and required_kg <= 0:
        # Replan path: the stock part already recovered (required == 0) but the
        # shipment problem is still live — offer the reroute that fixes it. The
        # stock-adders stay out because moving 0 kg would be a fake action.
        resolves |= {"REROUTE"}

    candidates: List[Dict[str, Any]] = []

    # --- PURCHASE: vendors x cheapest lane from vendor city -> facility city ---
    # A zero requirement means no stock needs to move — buying/transferring 0 kg
    # is not a plan, so stock-adders only appear when required_kg > 0.
    for v in vendors:
        vendor_id = v.get("vendor_id")
        if not vendor_id:
            continue
        if required_kg <= 0:
            continue
        vendor_stock = float(v.get("stock_available_kg", 0.0))
        if vendor_stock < required_kg:
            continue  # cannot supply enough — excluded by live data, honestly
        lane = _pick_lane(lanes, v.get("location_city"), target.get("city"))
        if lane is None:
            continue  # no lane from this vendor's city — not investigable, honest gap
        quote = lane_quote(lane, required_kg)

        # Transit = vendor lead time (prep + pickup) + lane physics.
        lead = float(v.get("lead_time_hours", 0.0))
        transit = round(lead + quote["transit_hours"], 2)

        # Per-kg landed cost: vendor price + freight rate (distance x rate/kg).
        # Per-kg on purpose — governance/optimizer compute spend as unit x qty.
        freight_per_kg = quote["distance_km"] * float(lane.get("cost_per_km_per_kg", 0.0))

        # Carbon: route freight per kg (distance x emission rate).
        carbon = quote["distance_km"] * float(lane.get("co2_per_km_per_kg", 0.0))
        candidates.append({
            "id": f"PURCHASE-{vendor_id}-{lane['lane_id']}",
            "type": "PURCHASE",
            "vendor_id": vendor_id,
            "quantity_kg": required_kg,
            "unit_cost_inr": round(float(v.get("unit_cost_inr", 0.0)) + freight_per_kg, 2),
            "transit_time_hours": transit,
            "carbon_per_kg_co2": round(carbon, 4),
            "cdsco_certified": bool(v.get("cdsco_certified", False)),
            "mode": quote["mode"],
            # discovery provenance (shown in the UI, asserted in tests)
            "source": "sandbox_discovery",
            "vendor_stock_kg": vendor_stock,
            "lane_id": lane["lane_id"],
            # cost/carbon breakdown for the UI (per-kg components, honest math)
            "breakdown": {
                "vendor_unit_cost": round(float(v.get("unit_cost_inr", 0.0)), 2),
                "freight_per_kg": round(freight_per_kg, 2),
                "handling_per_kg": 0.0,
                "distance_km": quote["distance_km"],
            },
        })

    # --- TRANSFER: every other facility whose surplus can cover the need ---
    for f in other_facilities:
        fid = f.get("facility_id")
        if not fid or required_kg <= 0:
            continue
        surplus = float(f.get("current_stock_kg", 0.0)) - float(f.get("safety_stock_kg", 0.0))
        if surplus < required_kg:
            continue  # cannot spare enough — excluded by live data, honestly
        lane = _pick_lane(lanes, f.get("city"), target.get("city"))
        if lane is None:
            continue
        quote = lane_quote(lane, required_kg)
        # Per-kg handling cost of moving stock between cold stores (config, not magic).
        handling = float(config.TRANSFER_HANDLING_COST_PER_KG)
        freight_per_kg = quote["distance_km"] * float(lane.get("cost_per_km_per_kg", 0.0))
        carbon = quote["distance_km"] * float(lane.get("co2_per_km_per_kg", 0.0))
        candidates.append({
            "id": f"TRANSFER-{fid}-{lane['lane_id']}",
            "type": "TRANSFER",
            "source_facility_id": fid,
            "quantity_kg": required_kg,
            "unit_cost_inr": round(handling + freight_per_kg, 2),
            "transit_time_hours": quote["transit_hours"],
            "carbon_per_kg_co2": round(carbon, 4),
            "cdsco_certified": True,   # internal network stock is certified by policy
            "mode": quote["mode"],
            "source": "sandbox_discovery",
            "source_surplus_kg": round(surplus, 1),
            "lane_id": lane["lane_id"],
            "breakdown": {
                "vendor_unit_cost": 0.0,
                "freight_per_kg": round(freight_per_kg, 2),
                "handling_per_kg": round(handling, 2),
                "distance_km": quote["distance_km"],
            },
        })

    # --- REROUTE: alternative lanes to the shipment's destination, ETA computed ---
    # NOTE: computed against the shipment's own quantity, so a reroute remains a
    # real action even when the facility's stock deficit is already zero.
    if "REROUTE" in resolves and shipment:
        dest_facility = next(
            (f for f in (env.get("inventory") or {}).values()
             if f.get("facility_id") == shipment.get("destination")),
            target,
        )
        current_lane = _pick_lane(lanes, shipment.get("origin"), dest_facility.get("city"))
        for lane in lanes:
            # Alternatives only: skip the lane the shipment is nominally on.
            if current_lane and lane["lane_id"] == current_lane["lane_id"]:
                continue
            quote = lane_quote(lane, float(shipment.get("quantity_kg", 0.0)) or required_kg)
            eta = (now + timedelta(hours=quote["transit_hours"])).isoformat()
            # Per-kg rerouting fee at the interchange hub (config, not magic).
            reroute_fee = float(config.REROUTE_HANDLING_COST_PER_KG)
            qty = float(shipment.get("quantity_kg", 0.0)) or required_kg
            freight_per_kg = quote["distance_km"] * float(lane.get("cost_per_km_per_kg", 0.0))
            carbon = quote["distance_km"] * float(lane.get("co2_per_km_per_kg", 0.0))
            candidates.append({
                "id": f"REROUTE-{shipment.get('shipment_id')}-{lane['lane_id']}",
                "type": "REROUTE",
                "shipment_id": shipment.get("shipment_id"),
                "new_destination": lane["to_city"] + " interchange",
                "new_eta": eta,
                "reason": "primary_disruption_recovery",
                "quantity_kg": qty,
                "unit_cost_inr": round(reroute_fee + freight_per_kg, 2),
                "transit_time_hours": quote["transit_hours"],
                "carbon_per_kg_co2": round(carbon, 4),
                "cdsco_certified": True,
                "mode": quote["mode"],
                "source": "sandbox_discovery",
                "lane_id": lane["lane_id"],
                "breakdown": {
                    "vendor_unit_cost": 0.0,
                    "freight_per_kg": round(freight_per_kg, 2),
                    "handling_per_kg": round(reroute_fee, 2),
                    "distance_km": quote["distance_km"],
                },
            })

    # --- ALLOCATE: reserve own-facility stock for the priority order ---
    if "ALLOCATE" in resolves:
        own_stock = float(target.get("current_stock_kg", 0.0))
        allocate_qty = min(own_stock, required_kg)
        if allocate_qty > 0:
            candidates.append({
                "id": f"ALLOCATE-{facility_id}-existing",
                "type": "ALLOCATE",
                "sku_id": target.get("sku_id", "unknown-sku"),
                "reserved_for": "recovery_order",
                "quantity_kg": allocate_qty,
                "unit_cost_inr": float(config.ALLOCATE_HANDLING_COST_PER_KG),
                "transit_time_hours": 1.0,
                "carbon_per_kg_co2": 0.0,
                "cdsco_certified": True,
                "mode": "IN_FACILITY_RESERVE",
                "source": "sandbox_discovery",
                "breakdown": {
                    "vendor_unit_cost": 0.0,
                    "freight_per_kg": 0.0,
                    "handling_per_kg": float(config.ALLOCATE_HANDLING_COST_PER_KG),
                    "distance_km": 0.0,
                },
            })

    # Keep the existing replan contract: excluded options never come back.
    return [c for c in candidates if c["id"] not in set(invalidated_options)]
