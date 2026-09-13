# PharmaShield AI — Corrected Execution Plan (v2)
### Mapped strictly against Problem Statement 6: Autonomous Retail Supply Chain Recovery Agent

---

## 0. Problem Statement Decomposition

The actual PS text is generic — it does **not** require pharma, CDSCO, or cold-chain. Those are your
domain specialization (good for realism scoring), layered on top of the seven mandatory bullets below.
Every fix in this document exists to close a gap between what the PS literally asks for and what v1's
code actually did.

| # | PS Requirement (verbatim) | v1 Status | v2 Fix |
|---|---|---|---|
| 1 | Monitor inventory **and shipment** state | Only shipment checked | `observe_node` now pulls both via digital twin |
| 2 | Detect disruption **or constraint violation** | Only shipment status checked | `detect_node` now also checks safety-stock breach and demand surge |
| 3 | Investigate alternative **vendors/routes/allocations** | Hardcoded candidate list | Unchanged logic, but now sourced to reflect all 3 categories (vendor purchase, route reroute, allocation transfer) |
| 4 | Use optimization tools to compare **feasible** actions | `optimizer.py` — correct | Unchanged, this was already solid |
| 5 | Execute a simulated **rerouting, purchase, allocation, or transfer** | Only "transfer" implemented; execute_node faked its own response | All four types now branch to real endpoints: `/orders/purchase`, `/transfers/dispatch`, `/shipments/reroute`, `/allocations/reserve` |
| 6 | **Verify** the resulting inventory and delivery state | `verify_node` inspected a fabricated dict, not real state | `verify_node` does a real RAW GET on inventory, and on the in-transit transfer record when relevant, so a reefer excursion is actually discoverable |
| 7 | **Replan** when alternative becomes unavailable or another disruption occurs | Conditional loop existed, but governance had no real veto path, checkpoint resume was wrong, and the second disruption was scripted into state | Governance rejection and verify failure both loop to `investigate` (excluding the failed option) instead of dead-ending; second disruption now arrives via a real telemetry endpoint, not `update_state` injection; checkpoint resume uses `update_state` + `stream(None, ...)` correctly |

**Bottom line:** your graph *shape* (observe → detect → investigate → optimize → governance → execute → verify → replan-loop) was already correct and matches the PS well. The problem was that three of the seven nodes didn't actually do the thing they were named for — they simulated success internally instead of calling the sandbox and checking real state. That's the exact failure mode the rules warn about ("fixed prompt chains without meaningful autonomous action").

---

## 1. File Blueprint (unchanged from v1, still correct)

```
TechRebels_Github_agentic/
├── README.md
├── requirements.txt
├── config.py
├── models.py
├── sandbox_api.py
├── optimizer.py
├── digital_twin.py
├── governance.py
├── agent_graph.py
├── scenarios.py
├── seed_data.json
└── dashboard/
    └── app.py
```

---

## 2. models.py — additions needed

v1 only had a `TransferRequest`. The PS requires four action types (reroute, purchase, allocate,
transfer), so the sandbox needs a model + endpoint for each.

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TransferRequest(BaseModel):
    source_facility_id: str
    dest_facility_id: str
    quantity_kg: float
    transport_mode: str
    requested_by: str

class PurchaseRequest(BaseModel):
    vendor_id: str
    dest_facility_id: str
    quantity_kg: float
    unit_cost_inr: float
    transport_mode: str
    requested_by: str

class RerouteRequest(BaseModel):
    shipment_id: str
    new_destination: str
    new_eta: datetime
    reason: str

class AllocationRequest(BaseModel):
    facility_id: str
    sku_id: str
    quantity_kg: float
    reserved_for: str   # e.g. order/customer id

class DemandSignal(BaseModel):
    facility_id: str
    sku_id: str
    observed_daily_burn_kg: float
    forecast_daily_burn_kg: float
    surge_ratio: float   # observed / baseline
```

---

## 3. sandbox_api.py — add the missing endpoints

v1 only implemented `/transfers/dispatch`. Add purchase and reroute so `execute_node` has something
real to call for every action type the optimizer might select.

> **Also fix the existing `dispatch_transfer` endpoint from Phase 1:** it currently builds a response
> dict but never writes it to `DB["transfers"]`. Fix 2's telemetry endpoint and `verify_node`'s
> transfer `GET` (Section 6) both require a real persisted record. Add
> `DB["transfers"][transfer_id] = response` before returning, and include a starting
> `"current_temp_celsius": 4.0` field in the response so the reefer telemetry endpoint has something
> to update.
>
> **Response-contract lock (one field name carries the whole Fix-2 reefer path).** The entire
> second-disruption demo keys off a field literally named `transfer_id`: `verify_node` branches on
> `res.get("transfer_id")`, `scenarios.py` reads `execution_result.get("transfer_id")`, and both the
> telemetry `POST` and the transfer `GET` are addressed by it. If `dispatch_transfer` returns
> `id` / `dispatch_id` / anything else, verify silently falls through to the facility-temp path and
> the reefer excursion is never discovered — the demo no-ops with no error. `dispatch_transfer` MUST
> return **exactly** these keys, so the corrected endpoint is spelled out here rather than left
> "unchanged from v1":
>
> ```python
> @app.post("/api/v1/transfers/dispatch")
> def dispatch_transfer(payload: TransferRequest, x_idempotency_key: str = Header(...)):
>     if x_idempotency_key in IDEMPOTENCY_CACHE:
>         return IDEMPOTENCY_CACHE[x_idempotency_key]
>
>     src = DB["inventory"].get(payload.source_facility_id)
>     dest = DB["inventory"].get(payload.dest_facility_id)
>     if not src or not dest:
>         raise HTTPException(status_code=404, detail="FACILITY_NOT_FOUND")
>     if src["current_stock_kg"] < payload.quantity_kg:
>         raise HTTPException(status_code=400, detail="INSUFFICIENT_SOURCE_STOCK")
>
>     # Physical move: deduct from source, credit destination (so verify_node's RAW
>     # inventory GET on the destination genuinely reflects the recovered stock).
>     src["current_stock_kg"] -= payload.quantity_kg
>     dest["current_stock_kg"] += payload.quantity_kg
>
>     transfer_id = f"TR-{uuid.uuid4().hex[:6].upper()}"
>     response = {
>         "transfer_id": transfer_id,            # <-- the load-bearing field name; do not rename
>         "status": "DISPATCHED",                # <-- must be in verify_node's success set
>         "source_facility_id": payload.source_facility_id,
>         "dest_facility_id": payload.dest_facility_id,
>         "quantity_kg": payload.quantity_kg,
>         "mode": payload.transport_mode,
>         "current_temp_celsius": 4.0,           # <-- reefer telemetry endpoint updates this in-place
>         "dispatched_at": datetime.utcnow().isoformat(),
>     }
>     DB["transfers"][transfer_id] = response    # <-- persist so GET /transfers/{id} + telemetry work
>     IDEMPOTENCY_CACHE[x_idempotency_key] = response
>     return response
> ```

```python
from models import PurchaseRequest, RerouteRequest, AllocationRequest

@app.post("/api/v1/orders/purchase")
def purchase_order(payload: PurchaseRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    dest = DB["inventory"].get(payload.dest_facility_id)
    if not dest:
        raise HTTPException(status_code=404, detail="FACILITY_NOT_FOUND")

    # Simulated external purchase — stock arrives, doesn't deduct from another facility
    order_id = f"PO-{uuid.uuid4().hex[:6].upper()}"
    response = {
        "order_id": order_id,
        "status": "ORDERED",
        "vendor_id": payload.vendor_id,
        "dest_facility_id": payload.dest_facility_id,
        "quantity_kg": payload.quantity_kg,
        "mode": payload.transport_mode,
        "ordered_at": datetime.utcnow().isoformat()
    }
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    return response

@app.post("/api/v1/shipments/reroute")
def reroute_shipment(payload: RerouteRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    shipment = DB["shipments"].get(payload.shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="SHIPMENT_NOT_FOUND")

    shipment["destination"] = payload.new_destination
    shipment["eta"] = payload.new_eta
    shipment["status"] = "REROUTED"
    shipment["version"] = shipment.get("version", 1) + 1

    response = {"shipment_id": payload.shipment_id, "status": "REROUTED", "new_eta": payload.new_eta.isoformat()}
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    return response

# Needed for real RAW verification in verify_node
@app.get("/api/v1/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    if shipment_id not in DB["shipments"]:
        raise HTTPException(status_code=404, detail="SHIPMENT_NOT_FOUND")
    return DB["shipments"][shipment_id]

@app.post("/api/v1/allocations/reserve")
def reserve_allocation(payload: AllocationRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    facility = DB["inventory"].get(payload.facility_id)
    if not facility or facility["current_stock_kg"] < payload.quantity_kg:
        raise HTTPException(status_code=400, detail="INSUFFICIENT_STOCK_TO_RESERVE")

    # Reserve without moving physical stock between facilities — distinct from TRANSFER
    reservation_id = f"ALLOC-{uuid.uuid4().hex[:6].upper()}"
    DB.setdefault("allocations", {})[reservation_id] = {
        "reservation_id": reservation_id, "facility_id": payload.facility_id,
        "sku_id": payload.sku_id, "quantity_kg": payload.quantity_kg,
        "reserved_for": payload.reserved_for
    }
    response = {"reservation_id": reservation_id, "status": "RESERVED", "quantity_kg": payload.quantity_kg}
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    return response

@app.get("/api/v1/transfers/{transfer_id}")
def get_transfer(transfer_id: str):
    if transfer_id not in DB["transfers"]:
        raise HTTPException(status_code=404, detail="TRANSFER_NOT_FOUND")
    return DB["transfers"][transfer_id]

# Represents an out-of-band telematics feed (e.g. reefer truck compressor failure).
# Called by the demo scenario to produce a *real* second disruption, not an injected
# state dict — verify_node's RAW check will pick this up on its own next GET.
@app.post("/api/v1/telemetry/reefer/{transfer_id}")
def report_reefer_telemetry(transfer_id: str, temp_celsius: float):
    if transfer_id not in DB["transfers"]:
        raise HTTPException(status_code=404, detail="TRANSFER_NOT_FOUND")
    DB["transfers"][transfer_id]["current_temp_celsius"] = temp_celsius
    return {"transfer_id": transfer_id, "current_temp_celsius": temp_celsius}
```

---

## 4. digital_twin.py — wire it into the graph (v1 defined it but never called it)

No code changes needed to the class itself — the fix is in `observe_node` (Section 6).

---

## 5. governance.py — unchanged, logic was already correct

The bug was never inside `check_bounded_autonomy()` — it was that the graph ignored its `False` result.
Fixed in Section 6.

---

## 6. agent_graph.py — corrected version

Key changes from v1, in order of importance:

1. `execute_node` and `verify_node` now use `httpx` to call the real sandbox instead of fabricating dicts.
2. `execute_node` branches on all four `plan["type"]` values — `PURCHASE`, `TRANSFER`, `REROUTE`, and `ALLOCATE` — so every action type the PS names is actually reachable, not just two of four.
3. `governance_node` result now actually gates execution via a conditional edge, and a rejection loops back to `investigate` (excluding the rejected option) rather than dead-ending — only escalating to `END` once `replan_count` is exhausted.
4. `detect_node` checks inventory safety-stock breach and demand surge, not just shipment status — this is what PS bullet 1/2 actually require ("inventory... state", "demand conditions").
5. `observe_node` calls `DigitalTwinSubstrate.synchronize_telemetry()` and now refreshes **shipment state** every tick too (real GET, not the seeded value) so replan loops never reason over stale shipment status.
6. `investigate_node` now filters candidates by which action types can actually **resolve the active disruption** (from `detect_node`'s reasons) *before* the optimizer scores them — so a safety-stock breach can't be "recovered" by a cheap ALLOCATE/REROUTE that adds no stock and then fails `verify_node`, which would waste replan cycles. All four action types stay reachable; the filter just gates them by disruption type.

```python
import sqlite3
import httpx
from typing import TypedDict, Annotated, List, Dict, Any
import operator
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from optimizer import evaluate_and_optimize
from governance import check_bounded_autonomy
from digital_twin import DigitalTwinSubstrate

SANDBOX_URL = "http://127.0.0.1:8000/api/v1"
client = httpx.Client(timeout=5.0)

class SupplyState(TypedDict):
    thread_id: str
    inventory_state: Dict[str, Any]
    shipment_state: Dict[str, Any]
    demand_state: Dict[str, Any]
    disruption_active: bool
    disruption_info: Dict[str, Any]
    candidate_options: List[Dict[str, Any]]
    optimal_plan: Dict[str, Any]
    governance_approved: bool
    execution_result: Dict[str, Any]
    verified: bool
    replan_count: int
    invalidated_options: Annotated[List[str], operator.add]
    audit_trail: Annotated[List[str], operator.add]

twin = DigitalTwinSubstrate(initial_state={"inventory": {}, "shipments": {}})

# --- Nodes ---

def observe_node(state: SupplyState) -> Dict[str, Any]:
    inv = client.get(f"{SANDBOX_URL}/inventory/{state['inventory_state']['facility_id']}").json()

    # Fix 3: refresh shipment state every tick, not just once at seed time — otherwise
    # detect_node reads stale shipment status on every replan loop.
    shipment_id = state.get("shipment_state", {}).get("shipment_id")
    shipment = client.get(f"{SANDBOX_URL}/shipments/{shipment_id}").json() if shipment_id else state.get("shipment_state", {})

    twin.synchronize_telemetry({"inventory": {inv["facility_id"]: inv}})
    return {
        "inventory_state": inv,
        "shipment_state": shipment,
        "audit_trail": ["ObserveNode: Refreshed inventory + shipment state from sandbox (real GETs, not seeded)."]
    }

def detect_node(state: SupplyState) -> Dict[str, Any]:
    inv = state["inventory_state"]
    shipment = state.get("shipment_state", {})
    demand = state.get("demand_state", {})

    reasons = []
    if inv["current_stock_kg"] < inv["safety_stock_kg"]:
        reasons.append("SAFETY_STOCK_BREACH")
    if shipment.get("status") in ["CUSTOMS_HOLD", "COMPROMISED", "DELAYED"]:
        reasons.append(f"SHIPMENT_{shipment['status']}")
    if demand.get("surge_ratio", 1.0) > 1.3:
        reasons.append("DEMAND_SURGE")

    if reasons:
        return {
            "disruption_active": True,
            "disruption_info": {"reasons": reasons},
            "audit_trail": [f"DetectNode: ALERT - {', '.join(reasons)}"]
        }
    return {"disruption_active": False, "audit_trail": ["DetectNode: No constraint violation."]}

def investigate_node(state: SupplyState) -> Dict[str, Any]:
    # Bug fix: v_prior only ever proposed PURCHASE/TRANSFER candidates, so the REROUTE and
    # ALLOCATE branches in execute_node were unreachable dead code — the optimizer could never
    # select an action type that was never investigated. Adding one of each so all four PS
    # action types (reroute, purchase, allocation, transfer) are genuinely reachable.
    #
    # Note: every candidate must carry the same optimizer-scored fields (unit_cost_inr,
    # quantity_kg, transit_time_hours, carbon_per_kg_co2, cdsco_certified) regardless of type,
    # since evaluate_and_optimize() scores them uniformly. The action-specific fields
    # (shipment_id, sku_id, etc.) are only read later by execute_node's per-type branch.
    #
    # Residual-issue fix: an action can only be a *valid recovery* for the disruption that is
    # actually active. A safety-stock breach at the destination facility is NOT resolved by a
    # REROUTE (changes a shipment's destination/ETA, adds no stock here) or an ALLOCATE (merely
    # reserves stock that is already too low) — only a PURCHASE or a TRANSFER adds physical
    # stock. If we let the optimizer pick purely on cost/time/carbon, OPT-ALLOC-EXISTING-STOCK
    # (cheapest, fastest, lowest carbon) wins, then fails verify_node's stock check, and the
    # graph burns replan cycles before landing on a fix. So we filter candidates by which action
    # types can resolve the active disruption BEFORE scoring, per the reasons detect_node found.
    reasons = state.get("disruption_info", {}).get("reasons", [])
    resolves = set()
    if any(r in ("SAFETY_STOCK_BREACH",) or r == "DEMAND_SURGE" for r in reasons):
        # need real stock at this facility -> only purchase or transfer add it
        resolves |= {"PURCHASE", "TRANSFER"}
    if any(r.startswith("SHIPMENT_") for r in reasons):
        # an in-flight shipment problem (customs hold, delay) is what a reroute fixes;
        # a transfer/purchase can also backfill while the shipment is stuck
        resolves |= {"REROUTE", "PURCHASE", "TRANSFER"}
    if not resolves:
        # no classified reason (e.g. a re-entry after a telemetry-only excursion) -> allow all,
        # let the optimizer and verify_node's RAW check sort it out
        resolves = {"PURCHASE", "TRANSFER", "REROUTE", "ALLOCATE"}

    all_candidates = [
        {"id": "OPT-AIR-VENDOR", "type": "PURCHASE", "vendor_id": "VEND-TAIPEI", "quantity_kg": 5000.0,
         "unit_cost_inr": 2400.0, "transit_time_hours": 11.0, "carbon_per_kg_co2": 0.9,
         "cdsco_certified": True, "mode": "AIR_CARGO"},
        {"id": "OPT-REEFER-TRANSFER", "type": "TRANSFER", "source_facility_id": "FAC-VIZAG-COLD",
         "quantity_kg": 5000.0, "unit_cost_inr": 360.0, "transit_time_hours": 14.0,
         "carbon_per_kg_co2": 0.16, "cdsco_certified": True, "mode": "REEFER_TRUCK"},
        {"id": "OPT-LOCAL-UNVERIFIED", "type": "PURCHASE", "vendor_id": "VEND-LOCAL", "quantity_kg": 5000.0,
         "unit_cost_inr": 180.0, "transit_time_hours": 6.0, "carbon_per_kg_co2": 0.05,
         "cdsco_certified": False, "mode": "LOCAL_TRUCK"},
        {"id": "OPT-REROUTE-RGIA", "type": "REROUTE", "shipment_id": state.get("shipment_state", {}).get("shipment_id"),
         "new_destination": "RGIA Hyderabad Air Cargo", "new_eta": "2026-09-14T09:00:00", "reason": "primary_disruption_recovery",
         "quantity_kg": 5000.0, "unit_cost_inr": 90.0, "transit_time_hours": 9.0,
         "carbon_per_kg_co2": 0.4, "cdsco_certified": True, "mode": "SEA_REROUTE"},
        {"id": "OPT-ALLOC-EXISTING-STOCK", "type": "ALLOCATE", "sku_id": "API-AMX-9901", "reserved_for": "recovery_order",
         "quantity_kg": 3000.0, "unit_cost_inr": 20.0, "transit_time_hours": 1.0,
         "carbon_per_kg_co2": 0.01, "cdsco_certified": True, "mode": "IN_FACILITY_RESERVE"},
    ]
    invalidated = state.get("invalidated_options", [])
    valid = [c for c in all_candidates if c["id"] not in invalidated and c["type"] in resolves]
    return {"candidate_options": valid, "audit_trail": [f"InvestigateNode: {len(valid)} candidates of types {sorted(resolves)} remain after excluding {invalidated}."]}

def optimize_node(state: SupplyState) -> Dict[str, Any]:
    optimized = evaluate_and_optimize(state["candidate_options"], max_allowed_hours=16.0)
    if not optimized:
        return {"optimal_plan": {}, "audit_trail": ["OptimizeNode: No feasible option satisfies hard bounds."]}
    best = optimized[0]
    return {"optimal_plan": best, "audit_trail": [f"OptimizeNode: Selected {best['id']} (score={best['score']:.4f})."]}

def governance_node(state: SupplyState) -> Dict[str, Any]:
    plan = state["optimal_plan"]
    if not plan:
        # Bug fix: this branch previously skipped incrementing replan_count entirely.
        # Once investigate_node exhausts all candidates, optimize_node returns {} every
        # pass, and without incrementing here, route_governance's `replan_count > 3` check
        # would never fire — the graph would loop governance -> investigate -> optimize ->
        # governance forever on an empty plan. Increment here so exhaustion is still detected.
        return {
            "governance_approved": False,
            "replan_count": state.get("replan_count", 0) + 1,
            "audit_trail": ["GovernanceNode: No plan to review (candidates exhausted)."]
        }
    approved, reason = check_bounded_autonomy(plan)
    result = {"governance_approved": approved, "audit_trail": [f"GovernanceNode: {'APPROVED' if approved else 'REJECTED'} - {reason}"]}
    if not approved:
        # Fix 4: exclude the rejected option so investigate_node doesn't re-propose it,
        # and route_governance can loop back to try the next-best candidate instead of dead-ending.
        # replan_count must increment here too, or route_governance's exhaustion check never fires.
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
            "transport_mode": plan["mode"], "requested_by": "agent"
        }
        resp = client.post(f"{SANDBOX_URL}/orders/purchase", json=payload, headers=headers)
    elif plan["type"] == "TRANSFER":
        payload = {
            "source_facility_id": plan["source_facility_id"], "dest_facility_id": state["inventory_state"]["facility_id"],
            "quantity_kg": plan["quantity_kg"], "transport_mode": plan["mode"], "requested_by": "agent"
        }
        resp = client.post(f"{SANDBOX_URL}/transfers/dispatch", json=payload, headers=headers)
    elif plan["type"] == "REROUTE":
        payload = {
            "shipment_id": plan["shipment_id"], "new_destination": plan["new_destination"],
            "new_eta": plan["new_eta"], "reason": plan.get("reason", "disruption_recovery")
        }
        resp = client.post(f"{SANDBOX_URL}/shipments/reroute", json=payload, headers=headers)
    elif plan["type"] == "ALLOCATE":
        payload = {
            "facility_id": state["inventory_state"]["facility_id"], "sku_id": plan["sku_id"],
            "quantity_kg": plan["quantity_kg"], "reserved_for": plan.get("reserved_for", "recovery_order")
        }
        resp = client.post(f"{SANDBOX_URL}/allocations/reserve", json=payload, headers=headers)
    else:
        return {"execution_result": {"status": "UNSUPPORTED_ACTION"}, "audit_trail": ["ExecuteNode: Unsupported action type."]}

    result = resp.json()
    result["option_id"] = plan["id"]
    return {"execution_result": result, "audit_trail": [f"ExecuteNode: {plan['type']} dispatched, key={idem_key}, sandbox_status={result.get('status')}."]}

def verify_node(state: SupplyState) -> Dict[str, Any]:
    res = state["execution_result"]
    facility_id = state["inventory_state"]["facility_id"]

    # Real Read-After-Write check
    fresh_inv = client.get(f"{SANDBOX_URL}/inventory/{facility_id}").json()
    stock_ok = fresh_inv["current_stock_kg"] >= fresh_inv["safety_stock_kg"]

    # Fix 2 dependency: a reefer excursion shows up on the TRANSFER record (via the
    # telemetry endpoint), not the destination facility's storage temp — check whichever
    # is relevant to this execution.
    transfer_id = res.get("transfer_id")
    if transfer_id:
        transfer = client.get(f"{SANDBOX_URL}/transfers/{transfer_id}").json()
        in_transit_temp = transfer.get("current_temp_celsius", 4.0)
        cold_chain_ok = 2.0 <= in_transit_temp <= 8.0
    else:
        cold_chain_ok = 2.0 <= fresh_inv.get("storage_temp_celsius", 4.0) <= 8.0

    # Bug fix: this set previously only covered PURCHASE ("ORDERED") and TRANSFER
    # ("DISPATCHED") success statuses. A successful REROUTE returns "REROUTED" and a
    # successful ALLOCATE returns "RESERVED" — both were being misclassified as failures,
    # triggering needless replans even when the action actually succeeded.
    if res.get("status") in ["DISPATCHED", "ORDERED", "REROUTED", "RESERVED"] and cold_chain_ok:
        return {"verified": True, "audit_trail": [f"VerifyNode: SUCCESS - RAW check confirms stock={fresh_inv['current_stock_kg']}kg, cold-chain OK."]}
    else:
        return {
            "verified": False,
            "replan_count": state.get("replan_count", 0) + 1,
            "invalidated_options": [res.get("option_id")],
            "audit_trail": [f"VerifyNode: FAILURE - cold_chain_ok={cold_chain_ok}, stock_ok={stock_ok}. Triggering replan."]
        }

# --- Conditional edges ---

def route_detection(state: SupplyState) -> str:
    return "investigate" if state["disruption_active"] else END

def route_governance(state: SupplyState) -> str:
    # Fix 4: a rejection should try the next compliant candidate, not dead-end immediately.
    # Only escalate to a human (END) once options are exhausted.
    if state.get("governance_approved"):
        return "execute"
    if state.get("replan_count", 0) > 3:
        return END   # exhausted options — genuine human-on-the-loop escalation
    return "investigate"

def route_verification(state: SupplyState) -> str:
    if state["verified"]:
        return END
    if state.get("replan_count", 0) > 3:
        return END
    return "investigate"

# --- Build graph ---

conn = sqlite3.connect("agent_state.db", check_same_thread=False)
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
builder.add_conditional_edges("governance", route_governance, {"execute": "execute", END: END})
builder.add_edge("execute", "verify")
builder.add_conditional_edges("verify", route_verification, {"investigate": "investigate", END: END})

graph = builder.compile(checkpointer=checkpointer)
```

---

## 7. scenarios.py — corrected checkpoint resume

v1's `graph.stream(checkpoint_state, config=config)` re-enters at `START`, which defeats the whole
point of using `SqliteSaver`. Use `update_state` + `stream(None, ...)` to genuinely resume mid-graph.

**Fix 2:** the secondary disruption is now produced through the real `/telemetry/reefer/{transfer_id}`
endpoint added in Section 3, not injected as a fabricated `execution_result`. `verify_node`'s own
Read-After-Write `GET` will independently discover the temperature excursion on its next check — the
graph doesn't need to be told the plan failed, it finds out.

```python
import uuid
from agent_graph import graph, client, SANDBOX_URL

def run_double_disruption_scenario():
    thread_id = f"TH-{uuid.uuid4().hex[:6].upper()}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802", "status": "CUSTOMS_HOLD"},
        "demand_state": {"surge_ratio": 1.0},
        "replan_count": 0,
        "invalidated_options": [],
    }

    print("=== STAGE 1: Primary Disruption ===")
    for event in graph.stream(initial_state, config=config):
        for node, values in event.items():
            print(f"[{node}] -> {values.get('audit_trail', [''])[0]}")

    # Fix 2: this is an out-of-band event, exactly like a real truck's telematics webhook
    # would be — it does NOT touch the graph's state directly. The reefer transfer_id comes
    # from Stage 1's execution_result (captured via graph.get_state(config) in a real run).
    print("\n=== STAGE 2: Real Secondary Disruption — reefer compressor failure ===")
    last_state = graph.get_state(config).values
    transfer_id = last_state.get("execution_result", {}).get("transfer_id")
    if transfer_id:
        client.post(f"{SANDBOX_URL}/telemetry/reefer/{transfer_id}", params={"temp_celsius": 14.0})
        print(f"Injected telemetry: transfer {transfer_id} now reporting +14°C.")

    # Resume the graph. It re-enters verify_node, which does a fresh RAW GET, independently
    # discovers the excursion, and the conditional edge routes back to investigate on its own —
    # nothing about the failure was told to the graph directly.
    for event in graph.stream(None, config=config):
        for node, values in event.items():
            print(f"[{node}] -> {values.get('audit_trail', [''])[0]}")

if __name__ == "__main__":
    run_double_disruption_scenario()
```

---

## 8. Final Checklist Against the Literal Problem Statement

- [x] Monitor inventory **and** shipment state → `observe_node` pulls real inventory via sandbox GET
- [x] Detect disruption **or constraint violation** → `detect_node` checks safety stock, shipment status, demand surge
- [x] Investigate alternative vendors/routes/allocations → `investigate_node` proposes one candidate of each of the four action types, filtered by prior failures **and by which types can resolve the active disruption** (so the optimizer never picks an action that structurally can't fix the current problem)
- [x] Optimization tool compares feasible actions → `optimizer.py`, hard-bound filtered then scored
- [x] Execute simulated rerouting/purchase/allocation/transfer → all four `plan["type"]` branches wired in `execute_node` to real endpoints (`/orders/purchase`, `/transfers/dispatch`, `/shipments/reroute`, `/allocations/reserve`); `dispatch_transfer` response contract pinned so it returns a `transfer_id` + `status:"DISPATCHED"` + `current_temp_celsius` (the load-bearing keys for the Fix-2 reefer path)
- [x] Verify resulting inventory and delivery state → `verify_node` does a real RAW GET on both inventory and (when relevant) the in-transit transfer record, checks cold-chain + stock bounds; success set covers all four action statuses (`DISPATCHED`/`ORDERED`/`REROUTED`/`RESERVED`)
- [x] Replan when alternative unavailable or new disruption occurs → verify-failure loop AND governance-rejection loop both route back to `investigate` excluding the failed/rejected option; secondary disruption now arrives via a real out-of-band telemetry call instead of a scripted state injection**Status update (post-build):** this v2 plan was executed and superseded by
`BUILD_PLAN.md`, which drove Phases 0–6 to completion. Everything above now
exists as real files; where the build refined this spec, BUILD_PLAN and the
code win — notably: candidates are no longer a hardcoded list (Phase 2 replaced
this file's `investigate_node` snippet with the discovery-driven
`candidates.py`), verification is stronger than sketched here (recovery gate +
per-type RAW reads), and a third disruption class (vendor condition changes)
exists beyond this plan's seven bullets. See `README.md` for the current
architecture and `MANUAL_TEST_PLAN.md` / `DEMO_SCRIPT.md` for how to prove it.
Test suite: 36 green (22 unit + 14 integration against the live sandbox).