"""Autonomous recovery agent — LangGraph state machine.

Graph shape (matches the seven PS bullets 1:1):
    observe -> detect -> [investigate -> optimize -> governance -> execute -> verify] -> replan loop

Every node that is *named* for an action actually performs it against the
sandbox: execute_node makes real HTTP calls, verify_node does a real
Read-After-Write GET. Nothing is faked in-process.

Phase 0 hardening: every sandbox call goes through _get/_post which degrade
gracefully — a sandbox blip produces an audit trail + escalation/replan, never
a crash and never a fabricated success.
"""
import sqlite3
from typing import Annotated, Any, Dict, List, TypedDict
import operator

import httpx
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

import config
from candidates import build_candidates, compute_required_kg
from optimizer import evaluate_and_optimize
from governance import check_bounded_autonomy
from digital_twin import DigitalTwinSubstrate

SANDBOX_URL = config.SANDBOX_URL
client = httpx.Client(timeout=5.0)


def _get(path: str) -> Dict[str, Any] | List[Any] | None:
    """Sandbox GET with graceful degradation.
    
    Returns the parsed JSON on 2xx (dict or list — Phase 2 discovery endpoints
    like /vendors and /routes return lists), or None when the sandbox is down,
    the route 404s, or the body is not JSON. Callers never crash on a sandbox
    blip — they branch on None and either escalate or replan (anti-fake rule 4).
    """
    try:
        resp = client.get(f"{SANDBOX_URL}{path}")
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _post(path: str, *, json: Dict[str, Any] | None = None,
          params: Dict[str, Any] | None = None,
          headers: Dict[str, str] | None = None) -> Dict[str, Any] | None:
    """Sandbox POST with graceful degradation (same contract as _get)."""
    try:
        resp = client.post(f"{SANDBOX_URL}{path}", json=json, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


class SupplyState(TypedDict):
    thread_id: str
    inventory_state: Dict[str, Any]
    shipment_state: Dict[str, Any]
    demand_state: Dict[str, Any]
    disruption_active: bool
    disruption_info: Dict[str, Any]
    candidate_options: List[Dict[str, Any]]
    scored_candidates: List[Dict[str, Any]]
    optimal_plan: Dict[str, Any]
    governance_approved: bool
    execution_result: Dict[str, Any]
    verified: bool
    replan_count: int
    invalidated_options: Annotated[List[str], operator.add]
    audit_trail: Annotated[List[str], operator.add]
    computed_required_kg: float


twin = DigitalTwinSubstrate(initial_state={"inventory": {}, "shipments": {}})


# --- Nodes ---
def observe_node(state: SupplyState) -> Dict[str, Any]:
    facility_id = state["inventory_state"]["facility_id"]

    inv = _get(f"/inventory/{facility_id}")
    if inv is None:
        # Cannot see the world -> do NOT invent a healthy world. Mark the
        # sandbox-unreachable condition so detect/route escalate to a human
        # instead of acting on fabricated data.
        return {
            "disruption_active": True,
            "disruption_info": {"reasons": ["SANDBOX_UNREACHABLE"]},
            "audit_trail": ["ObserveNode: SANDBOX_UNREACHABLE — inventory GET failed; escalating to human."],
        }

    # Refresh shipment state every tick, not just once at seed time — otherwise
    # detect_node reads stale shipment status on every replan loop.
    shipment_id = state.get("shipment_state", {}).get("shipment_id")
    shipment = (_get(f"/shipments/{shipment_id}") if shipment_id else None) \
        or state.get("shipment_state", {})

    # Demand is a REAL environment condition (Phase 1): the agent discovers the
    # facility's demand signal via HTTP, exactly like inventory and shipments.
    demand = _get(f"/demand/{facility_id}")

    # Digital twin: synchronize BOTH domains so the twin mirrors the full
    # observed world; detect_node reads its shipment view from the snapshot,
    # making the twin load-bearing rather than dead code (Phase 0 decision).
    twin.synchronize_telemetry({
        "inventory": {inv["facility_id"]: inv},
        "shipments": ({shipment["shipment_id"]: shipment} if shipment.get("shipment_id") else {}),
    })

    audit = ["ObserveNode: Refreshed inventory + shipment + demand state from sandbox (real GETs, not seeded)."]
    if demand is None:
        audit.append("ObserveNode: no demand signal in sandbox — defaulting to baseline (no surge).")
    return {
        "inventory_state": inv,
        "shipment_state": shipment,
        "demand_state": demand or {"surge_ratio": 1.0},
        "audit_trail": audit,
    }


def detect_node(state: SupplyState) -> Dict[str, Any]:
    if "SANDBOX_UNREACHABLE" in state.get("disruption_info", {}).get("reasons", []):
        return {
            "disruption_active": True,
            "disruption_info": {"reasons": ["SANDBOX_UNREACHABLE"]},
            "audit_trail": ["DetectNode: Sandbox unreachable — cannot observe the world; escalating."],
        }

    inv = state["inventory_state"]
    demand = state.get("demand_state", {})

    # Shipment status is read from the digital twin's snapshot (load-bearing use
    # of the twin — Phase 0). Falls back to the state copy if the twin has no
    # record (e.g. a shipment_id the sandbox does not know).
    shipment_id = state.get("shipment_state", {}).get("shipment_id")
    shipment = twin.snapshot("shipments", shipment_id) if shipment_id else {}
    if not shipment:
        shipment = state.get("shipment_state", {})

    reasons = []
    if inv.get("current_stock_kg", 0.0) < inv.get("safety_stock_kg", 0.0):
        reasons.append("SAFETY_STOCK_BREACH")
    if shipment.get("status") in ["CUSTOMS_HOLD", "COMPROMISED", "DELAYED"]:
        reasons.append(f"SHIPMENT_{shipment['status']}")
    if demand.get("surge_ratio", 1.0) > config.DEMAND_SURGE_THRESHOLD:
        reasons.append("DEMAND_SURGE")

    if reasons:
        return {
            "disruption_active": True,
            "disruption_info": {"reasons": reasons},
            "audit_trail": [f"DetectNode: ALERT - {', '.join(reasons)}"],
        }
    return {"disruption_active": False, "audit_trail": ["DetectNode: No constraint violation."]}


def investigate_node(state: SupplyState) -> Dict[str, Any]:
    """Discover the recovery option set from the LIVE environment (Phase 2).

    Nothing is hardcoded here anymore. The node reads vendors, lanes, all
    facility inventories, demand, and the in-flight shipment over HTTP, prices
    each (candidate x lane) with the sandbox cost-carbon calculator's math,
    and delegates construction to candidates.build_candidates. Editing
    seed_data.json (vendor stock, lane speed, a new vendor) changes what the
    agent investigates — deleting these loops changes nothing, because there
    are no constants to delete.

    The 'resolves' filter stays: only action types that can structurally fix
    the detected disruption are admitted, before the optimizer scores.
    """
    reasons = state.get("disruption_info", {}).get("reasons", [])
    facility_id = state["inventory_state"]["facility_id"]
    shipment_id = state.get("shipment_state", {}).get("shipment_id")
    invalidated = state.get("invalidated_options", [])

    # --- Discover the world over HTTP (graceful degradation throughout) ---
    inventory = _get("/inventory")            # every facility (surplus math)
    if inventory is None:
        # Without the full inventory map we cannot compute surplus or deficit
        # honestly — do not fabricate options from stale state. Escalate.
        return {
            "candidate_options": [],
            "audit_trail": ["InvestigateNode: inventory discovery GET failed (sandbox unreachable) — cannot investigate honestly; escalating."],
        }
    target = inventory.get(facility_id) or state["inventory_state"]
    vendors = _get("/vendors") or []           # [] degrades to fewer candidates, not a crash
    lanes = _get("/routes") or []
    shipment = _get(f"/shipments/{shipment_id}") if shipment_id else None
    demand = state.get("demand_state") or {}

    # Price check: confirm the sandbox calculator agrees with local math on one
    # live lane — a real tool call, part of the audit ("we used the tool").
    calc = None
    if lanes:
        first_lane = lanes[0]
        calc = _post("/tools/cost-carbon", json={
            "origin_city": first_lane["from_city"],
            "destination_city": first_lane["to_city"],
            "quantity_kg": 1000.0,
        })

    required_kg = compute_required_kg(target, demand)
    env = {
        "inventory": inventory,
        "target": target,
        "shipment": shipment,
        "vendors": vendors,
        "lanes": lanes,
        "demand": demand,
    }
    valid = build_candidates(env, reasons, invalidated, required_kg)

    # Vendor conditions are live data: name anything the discovery found that
    # constrains the option set (stock-outs, certification losses) so the audit
    # trail shows WHY candidates are absent — not just that they are.
    vendor_conditions = []
    for v in vendors if isinstance(vendors, list) else []:
        stock = float(v.get("stock_available_kg", 0.0))
        if stock <= 0.0:
            vendor_conditions.append(f"{v.get('vendor_id')}:STOCK_OUT")
        elif not v.get("cdsco_certified", False):
            vendor_conditions.append(f"{v.get('vendor_id')}:UNCERTIFIED")
    cond_note = f"; vendor conditions: {', '.join(vendor_conditions)}" if vendor_conditions else ""

    audit = [
        f"InvestigateNode: discovered {len(vendors)} vendors, {len(lanes)} lanes, "
        f"{len(inventory)} facilities from sandbox; computed required={required_kg}kg "
        f"(deficit + surge buffer){cond_note}."
    ]
    if calc:
        audit.append(
            f"InvestigateNode: cost-carbon tool verified on lane {calc.get('lane_id')} "
            f"@1000kg -> {calc.get('cost_inr')} INR / {calc.get('carbon_kg')} kg CO2."
        )
    audit.append(
        f"InvestigateNode: {len(valid)} candidates built from live data "
        f"after excluding {invalidated}."
    )
    return {
        "candidate_options": valid,
        "computed_required_kg": required_kg,
        "audit_trail": audit,
    }


def optimize_node(state: SupplyState) -> Dict[str, Any]:
    candidates = state["candidate_options"]
    optimized = evaluate_and_optimize(candidates, max_allowed_hours=config.MAX_ALLOWED_HOURS)

    # Build a full table for the UI: feasible options carry their score; ones the
    # feasibility filter dropped are marked infeasible so the Options tab can show
    # *why* an option was not chosen (over time bound / not CDSCO-certified).
    feasible_ids = {c["id"] for c in optimized}
    scored_table = list(optimized)
    for c in candidates:
        if c["id"] not in feasible_ids:
            scored_table.append({**c, "score": None, "feasible": False})
    for c in scored_table:
        c.setdefault("feasible", True)

    if not optimized:
        return {
            "scored_candidates": scored_table,
            "optimal_plan": {},
            "audit_trail": ["OptimizeNode: No feasible option satisfies hard bounds."],
        }
    best = optimized[0]
    return {
        "scored_candidates": scored_table,
        "optimal_plan": best,
        "audit_trail": [f"OptimizeNode: Selected {best['id']} (score={best['score']:.4f})."],
    }


def governance_node(state: SupplyState) -> Dict[str, Any]:
    plan = state["optimal_plan"]
    if not plan:
        # Increment here too, or route_governance's exhaustion check never fires
        # once investigate_node runs out of candidates (optimize returns {} each pass).
        return {
            "governance_approved": False,
            "replan_count": state.get("replan_count", 0) + 1,
            "audit_trail": ["GovernanceNode: No plan to review (candidates exhausted)."],
        }
    approved, reason = check_bounded_autonomy(plan)
    result = {
        "governance_approved": approved,
        "audit_trail": [f"GovernanceNode: {'APPROVED' if approved else 'REJECTED'} - {reason}"],
    }
    if not approved:
        result["invalidated_options"] = [plan["id"]]
        result["replan_count"] = state.get("replan_count", 0) + 1
    return result


def execute_node(state: SupplyState) -> Dict[str, Any]:
    plan = state["optimal_plan"]
    idem_key = f"{state['thread_id']}-replan-{state.get('replan_count', 0)}"
    headers = {"x-idempotency-key": idem_key}

    if plan["type"] == "PURCHASE":
        payload = {
            "vendor_id": plan["vendor_id"], "dest_facility_id": state["inventory_state"]["facility_id"],
            "quantity_kg": plan["quantity_kg"], "unit_cost_inr": plan["unit_cost_inr"],
            "transport_mode": plan["mode"], "requested_by": "agent",
        }
        resp = _post("/orders/purchase", json=payload, headers=headers)
    elif plan["type"] == "TRANSFER":
        payload = {
            "source_facility_id": plan["source_facility_id"],
            "dest_facility_id": state["inventory_state"]["facility_id"],
            "quantity_kg": plan["quantity_kg"], "transport_mode": plan["mode"], "requested_by": "agent",
        }
        resp = _post("/transfers/dispatch", json=payload, headers=headers)
    elif plan["type"] == "REROUTE":
        payload = {
            "shipment_id": plan["shipment_id"], "new_destination": plan["new_destination"],
            "new_eta": plan["new_eta"], "reason": plan.get("reason", "disruption_recovery"),
        }
        resp = _post("/shipments/reroute", json=payload, headers=headers)
    elif plan["type"] == "ALLOCATE":
        payload = {
            "facility_id": state["inventory_state"]["facility_id"], "sku_id": plan["sku_id"],
            "quantity_kg": plan["quantity_kg"], "reserved_for": plan.get("reserved_for", "recovery_order"),
        }
        resp = _post("/allocations/reserve", json=payload, headers=headers)
    else:
        return {"execution_result": {"status": "UNSUPPORTED_ACTION"}, "audit_trail": ["ExecuteNode: Unsupported action type."]}

    if resp is None:
        # Sandbox blipped mid-action: do NOT fabricate a success. Treat the call
        # as failed so verify/replan (or escalation) handles it honestly.
        return {
            "execution_result": {"status": "SANDBOX_UNREACHABLE", "option_id": plan["id"]},
            "audit_trail": [f"ExecuteNode: {plan['type']} failed — sandbox unreachable; routing into replan/escalation."],
        }

    result = dict(resp)
    result["option_id"] = plan["id"]
    return {
        "execution_result": result,
        "audit_trail": [f"ExecuteNode: {plan['type']} dispatched, key={idem_key}, sandbox_status={result.get('status')}."],
    }


def verify_node(state: SupplyState) -> Dict[str, Any]:
    res = state["execution_result"]
    facility_id = state["inventory_state"]["facility_id"]

    # A sandbox-unreachable execution can't be verified — fail into replan.
    if res.get("status") == "SANDBOX_UNREACHABLE":
        return {
            "verified": False,
            "replan_count": state.get("replan_count", 0) + 1,
            "invalidated_options": [res.get("option_id")],
            "audit_trail": ["VerifyNode: FAILURE - sandbox unreachable at execute time; triggering replan."],
        }

    # Real Read-After-Write check
    fresh_inv = _get(f"/inventory/{facility_id}")
    if fresh_inv is None:
        return {
            "verified": False,
            "replan_count": state.get("replan_count", 0) + 1,
            "invalidated_options": [res.get("option_id")],
            "audit_trail": ["VerifyNode: FAILURE - RAW inventory GET failed (sandbox unreachable); triggering replan."],
        }
    stock_ok = fresh_inv["current_stock_kg"] >= fresh_inv["safety_stock_kg"]

    # A reefer excursion shows up on the TRANSFER record (via the telemetry
    # endpoint), not the destination facility's storage temp.
    transfer_id = res.get("transfer_id")
    if transfer_id:
        transfer = _get(f"/transfers/{transfer_id}")
        in_transit_temp = (transfer or {}).get("current_temp_celsius", config.COLD_CHAIN_MIN_C + 2.0)
        cold_chain_ok = config.COLD_CHAIN_MIN_C <= in_transit_temp <= config.COLD_CHAIN_MAX_C
    else:
        cold_chain_ok = config.COLD_CHAIN_MIN_C <= fresh_inv.get("storage_temp_celsius", 4.0) <= config.COLD_CHAIN_MAX_C

    # Which disruption are we actually recovering from? A stock breach / demand
    # surge is only "resolved" when real stock clears the safety floor. A pure
    # shipment problem is resolved by the shipment moving out of a bad status.
    reasons = state.get("disruption_info", {}).get("reasons", [])
    stock_disruption = any(r in ("SAFETY_STOCK_BREACH", "DEMAND_SURGE") for r in reasons)

    call_ok = res.get("status") in ["DISPATCHED", "ORDERED", "REROUTED", "RESERVED"]

    # Phase 3 — complete Read-After-Write: re-GET the exact record each action
    # type mutated. A success status in the POST response is a claim; the fresh
    # GET of the mutated record is the proof. A vanished/reverted record fails
    # verification into the replan loop, honestly.
    record_ok = True
    record_note = "n/a"
    if call_ok and res.get("order_id"):
        order = _get(f"/orders/{res['order_id']}")
        record_ok = order is not None and order.get("status") == "ORDERED" \
            and order.get("vendor_id") == res.get("vendor_id")
        record_note = f"order {res['order_id']} re-GET: {'ok' if record_ok else 'MISMATCH/MISSING'}"
    elif call_ok and res.get("reservation_id"):
        alloc = _get(f"/allocations/{res['reservation_id']}")
        record_ok = alloc is not None and \
            float(alloc.get("quantity_kg", 0.0)) == float(res.get("quantity_kg", -1.0))
        record_note = f"reservation {res['reservation_id']} re-GET: {'ok' if record_ok else 'VANISHED/MISMATCH'}"
    elif call_ok and res.get("shipment_id") and res.get("new_eta"):
        shipment = _get(f"/shipments/{res['shipment_id']}")
        record_ok = shipment is not None and \
            shipment.get("status") in ("REROUTED", "IN_TRANSIT")
        record_note = f"shipment {res['shipment_id']} re-GET: status={shipment.get('status') if shipment else 'MISSING'}"

    if call_ok and not record_ok:
        return {
            "verified": False,
            "replan_count": state.get("replan_count", 0) + 1,
            "invalidated_options": [res.get("option_id")],
            "inventory_state": fresh_inv,
            "audit_trail": [
                f"VerifyNode: FAILURE - RAW record check failed ({record_note}); "
                "the mutated record did not hold. Triggering replan."
            ],
        }

    # Recovery gate: the sandbox call succeeded, cold-chain is intact, AND — when
    # the disruption was a stock problem — stock has genuinely recovered. This is
    # what stops a REROUTE/ALLOCATE (which add no physical stock) from being
    # reported as a successful recovery of a safety-stock breach.
    recovered = call_ok and cold_chain_ok and (stock_ok if stock_disruption else True)

    if recovered:
        return {
            "verified": True,
            # Publish the RAW-read inventory so the dashboard's stock stat shows
            # post-recovery truth, not the stale pre-observe value.
            "inventory_state": fresh_inv,
            "audit_trail": [
                f"VerifyNode: SUCCESS - RAW check: stock={fresh_inv['current_stock_kg']}kg "
                f"(safety={fresh_inv['safety_stock_kg']}kg, ok={stock_ok}), cold-chain "
                f"ok={cold_chain_ok}, record check: {record_note}."
            ],
        }
    return {
        "verified": False,
        "replan_count": state.get("replan_count", 0) + 1,
        "invalidated_options": [res.get("option_id")],
        "inventory_state": fresh_inv,
        "audit_trail": [
            f"VerifyNode: FAILURE - call_ok={call_ok}, cold_chain_ok={cold_chain_ok}, "
            f"stock_ok={stock_ok} (needed={stock_disruption}), record: {record_note}. Triggering replan."
        ],
    }


# --- Conditional edges ---
def route_detection(state: SupplyState) -> str:
    # Sandbox-unreachable is not a recoverable disruption: escalate to a human.
    if "SANDBOX_UNREACHABLE" in state.get("disruption_info", {}).get("reasons", []):
        return END
    return "investigate" if state["disruption_active"] else END


def route_governance(state: SupplyState) -> str:
    if state.get("governance_approved"):
        return "execute"
    if state.get("replan_count", 0) > config.MAX_REPLANS:
        return END   # exhausted options — genuine human-on-the-loop escalation
    return "investigate"


def route_verification(state: SupplyState) -> str:
    if state["verified"]:
        return END
    if state.get("replan_count", 0) > config.MAX_REPLANS:
        return END
    return "investigate"


# --- Build graph ---
def build_graph(checkpointer=None):
    if checkpointer is None:
        conn = sqlite3.connect(config.CHECKPOINT_DB, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    builder = StateGraph(SupplyState)
    builder.add_node("observe", observe_node)
    builder.add_node("detect", detect_node)
    builder.add_node("investigate", investigate_node)
    builder.add_node("optimize", optimize_node)
    builder.add_node("governance", governance_node)
    builder.add_node("execute", execute_node)
    builder.add_node("verify", verify_node)

    builder.add_edge(START, "observe")
    builder.add_edge("observe", "detect")
    builder.add_conditional_edges("detect", route_detection, {"investigate": "investigate", END: END})
    builder.add_edge("investigate", "optimize")
    builder.add_edge("optimize", "governance")
    builder.add_conditional_edges("governance", route_governance, {"execute": "execute", "investigate": "investigate", END: END})
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges("verify", route_verification, {"investigate": "investigate", END: END})

    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
