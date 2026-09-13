"""Simulated logistics sandbox — the state-changing environment the agent acts on.

Implements the state-changing endpoints the Problem Statement calls for
(rerouting, purchase, allocation, transfer) plus the read endpoints the agent's
verify step needs for genuine Read-After-Write checks, and an out-of-band reefer
telemetry endpoint used to produce a *real* second disruption.

All mutations are idempotent by the x-idempotency-key header so the agent's
replan loop can safely retry an action without double-committing it.

Run with:  uvicorn sandbox_api:app --host 127.0.0.1 --port 8000
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import config
from models import (
    AllocationRequest,
    DemandSignal,
    PurchaseRequest,
    RerouteRequest,
    TransferRequest,
)

app = FastAPI(title="Supply Chain Recovery Sandbox", version="1.0.0")

# Allow the React dashboard (served from a static file or a dev server) to call in.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Datastore: seed hydration + disk persistence (Phase 7) ---
# State survives restarts via a JSON snapshot written on every mutation.
# Set SANDBOX_PERSIST=0 to run fully in-memory (e.g. for CI).
_SEED_PATH = os.path.join(os.path.dirname(__file__), "seed_data.json")
_SNAPSHOT_PATH = os.environ.get(
    "SANDBOX_SNAPSHOT_PATH",
    os.path.join(os.path.dirname(__file__), "sandbox_snapshot.json"),
)
_HISTORY_PATH = os.environ.get(
    "SANDBOX_HISTORY_PATH",
    os.path.join(os.path.dirname(__file__), "run_history.json"),
)
_PERSIST = os.environ.get("SANDBOX_PERSIST", "1") not in ("0", "false", "False")

with open(_SEED_PATH, "r", encoding="utf-8") as _f:
    DB: dict = json.load(_f)


def _load_snapshot() -> bool:
    """Restore DB from the on-disk snapshot. Returns True if restored.

    A snapshot missing any seed collection is healed from the seed (forward
    compatible), so adding new collections to seed_data.json never breaks an
    old snapshot. Corrupt snapshots are ignored, never fatal.
    """
    if not _PERSIST or not os.path.exists(_SNAPSHOT_PATH):
        return False
    try:
        with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            snap = json.load(f)
        if not isinstance(snap, dict) or not snap.get("inventory"):
            return False   # empty/corrupt — fall back to seed
        # Heal collections added after the snapshot was written (forward compat).
        for key, default in (("transfers", {}), ("allocations", {}), ("demand", {}),
                             ("vendors", {}), ("lanes", []), ("orders", {})):
            snap.setdefault(key, default)
        DB.clear()
        DB.update(snap)
        return True
    except (OSError, ValueError):
        return False


def _save_snapshot() -> None:
    """Best-effort atomic snapshot write (tmp + rename). Never crashes a request.
    Skipped entirely under SANDBOX_PERSIST=0 (CI / ephemeral mode)."""
    if not _PERSIST:
        return
    try:
        tmp = _SNAPSHOT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DB, f)
        os.replace(tmp, _SNAPSHOT_PATH)
    except OSError:
        pass  # a failed snapshot write must never break a live mutation


# Ensure the mutable collections exist even if the seed/snapshot omitted them.
DB.setdefault("transfers", {})
DB.setdefault("allocations", {})
DB.setdefault("demand", {})   # facility_id -> demand signal (Phase 1)
DB.setdefault("vendors", {})
DB.setdefault("lanes", [])
DB.setdefault("orders", {})   # order_id -> purchase record (Phase 3: RAW re-GET)

SNAPSHOT_RESTORED = _load_snapshot()

IDEMPOTENCY_CACHE: dict = {}


def _clear_checkpoints(clear: bool) -> None:
    """Delete LangGraph checkpoint rows for this project's agent_state.db.

    Phase 0: /reset now offers full environment reset including the graph's
    persisted state, so tests and demos start from a genuinely clean slate.
    Failures are swallowed — a missing/locked db must not break the reset.
    """
    if not clear:
        return
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB, timeout=2.0)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            for t in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                if t in tables:
                    conn.execute(f"DELETE FROM {t}")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # best-effort: no db file, locked, or schema drift — reset continues


def _reset_db():
    """Re-hydrate the in-memory store from seed and clear caches (test hook).

    Mutates the existing DB dict IN PLACE (clear + repopulate) rather than
    rebinding the global — so every endpoint that closed over `DB` sees the
    reset, with no chance of a stale reference surviving.
    """
    with open(_SEED_PATH, "r", encoding="utf-8") as f:
        fresh = json.load(f)
    DB.clear()
    DB.update(fresh)
    for key, default in (("transfers", {}), ("allocations", {}), ("demand", {}),
                         ("vendors", {}), ("lanes", []), ("orders", {})):
        DB.setdefault(key, default)
    IDEMPOTENCY_CACHE.clear()
    _save_snapshot()   # a reset is a mutation too — persist it


@app.post("/api/v1/reset")
def reset(payload: dict | None = None):
    """Reset sandbox state to the seed. Optional {"scenario": "..."} patches the
    seed so a specific disruption type is the active one (used by the test suite):
      - "stock_breach" (default): stock below safety → PURCHASE/TRANSFER
      - "shipment_only": stock healthy, shipment on customs hold → REROUTE
      - "demand_surge":  stock healthy, shipment IN_TRANSIT → ALLOCATE
    Each scenario also sets a REAL shipment status via the environment (Phase 1):
    the agent's initial-state status hint is ignored once observe GETs the truth.

    Optional {"clear_checkpoints": true} also deletes LangGraph checkpoint rows
    from agent_state.db (Phase 0 hygiene). The reset is itself persisted
    (Phase 7), so a restart after /reset comes back to the reset state — pass
    SANDBOX_PERSIST=0 to run fully in-memory.
    """
    _reset_db()
    body = payload or {}
    scenario = body.get("scenario", "stock_breach")
    fac = DB["inventory"].get("FAC-HYD-GENOME")
    shipment = DB["shipments"].get("IMP-JNPT-8802")
    if fac and scenario in ("shipment_only", "demand_surge"):
        # Lift stock above the safety floor so there is no SAFETY_STOCK_BREACH,
        # letting the pure shipment / pure surge branch drive the recovery.
        fac["current_stock_kg"] = fac["safety_stock_kg"] + 2000.0
    if shipment and scenario == "demand_surge":
        # A demand-surge scenario is a healthy logistics day: the shipment is
        # simply in transit. The environment (not the agent's initial state)
        # now says so.
        shipment["status"] = "IN_TRANSIT"
    # A scenario reset always neutralizes demand so runs are reproducible: a
    # signal left over from a previous run must not silently combine with the
    # new scenario. Callers (orchestrator/tests) post a fresh signal per run.
    DB["demand"].clear()
    _clear_checkpoints(bool(body.get("clear_checkpoints")))
    return {
        "status": "reset",
        "scenario": scenario,
        "facilities": len(DB["inventory"]),
        "shipment_status": shipment.get("status") if shipment else None,
        "checkpoints_cleared": bool(body.get("clear_checkpoints")),
    }


# ----------------------------------------------------------------------------
# Read endpoints (used by observe_node and verify_node for real RAW checks)
# ----------------------------------------------------------------------------
@app.get("/api/v1/inventory/{facility_id}")
def get_inventory(facility_id: str):
    if facility_id not in DB["inventory"]:
        raise HTTPException(status_code=404, detail="FACILITY_NOT_FOUND")
    return DB["inventory"][facility_id]


@app.get("/api/v1/inventory")
def get_all_inventory():
    """Every facility's live inventory (Phase 2: surplus/deficit discovery)."""
    return DB["inventory"]


@app.get("/api/v1/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    if shipment_id not in DB["shipments"]:
        raise HTTPException(status_code=404, detail="SHIPMENT_NOT_FOUND")
    return DB["shipments"][shipment_id]


@app.get("/api/v1/transfers/{transfer_id}")
def get_transfer(transfer_id: str):
    if transfer_id not in DB["transfers"]:
        raise HTTPException(status_code=404, detail="TRANSFER_NOT_FOUND")
    return DB["transfers"][transfer_id]


# ----------------------------------------------------------------------------
# Phase 3: RAW verification targets — verify_node re-GETs the record each
# action type mutated before claiming success.
# ----------------------------------------------------------------------------
@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: str):
    order = DB.get("orders", {}).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")
    return order


@app.get("/api/v1/allocations/{reservation_id}")
def get_allocation(reservation_id: str):
    alloc = DB.get("allocations", {}).get(reservation_id)
    if not alloc:
        raise HTTPException(status_code=404, detail="ALLOCATION_NOT_FOUND")
    return alloc


@app.delete("/api/v1/allocations/{reservation_id}")
def cancel_allocation(reservation_id: str):
    """Out-of-band allocation cancellation (tamper path for Phase 3 tests):
    the reservation vanishes exactly as a real ERP-side cancellation would.
    The agent's re-GET must discover the disappearance — never be told."""
    alloc = DB.get("allocations", {}).pop(reservation_id, None)
    if alloc is None:
        raise HTTPException(status_code=404, detail="ALLOCATION_NOT_FOUND")
    _save_snapshot()
    return {"reservation_id": reservation_id, "status": "CANCELLED"}


# ----------------------------------------------------------------------------
# State-changing endpoints — one per PS action type
# ----------------------------------------------------------------------------
@app.post("/api/v1/transfers/dispatch")
def dispatch_transfer(payload: TransferRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    src = DB["inventory"].get(payload.source_facility_id)
    dest = DB["inventory"].get(payload.dest_facility_id)
    if not src or not dest:
        raise HTTPException(status_code=404, detail="FACILITY_NOT_FOUND")
    if src["current_stock_kg"] < payload.quantity_kg:
        raise HTTPException(status_code=400, detail="INSUFFICIENT_SOURCE_STOCK")

    # Physical move: deduct from source, credit destination (so verify_node's RAW
    # inventory GET on the destination genuinely reflects the recovered stock).
    src["current_stock_kg"] -= payload.quantity_kg
    dest["current_stock_kg"] += payload.quantity_kg

    transfer_id = f"TR-{uuid.uuid4().hex[:6].upper()}"
    response = {
        "transfer_id": transfer_id,            # load-bearing field name; do not rename
        "status": "DISPATCHED",                # must be in verify_node's success set
        "source_facility_id": payload.source_facility_id,
        "dest_facility_id": payload.dest_facility_id,
        "quantity_kg": payload.quantity_kg,
        "mode": payload.transport_mode,
        "current_temp_celsius": 4.0,           # reefer telemetry endpoint updates this in-place
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
    }
    DB["transfers"][transfer_id] = response    # persist so GET /transfers/{id} + telemetry work
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    _save_snapshot()
    return response


@app.post("/api/v1/orders/purchase")
def purchase_order(payload: PurchaseRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    dest = DB["inventory"].get(payload.dest_facility_id)
    if not dest:
        raise HTTPException(status_code=404, detail="FACILITY_NOT_FOUND")

    # Simulated external purchase — stock arrives, doesn't deduct from another facility.
    dest["current_stock_kg"] += payload.quantity_kg
    order_id = f"PO-{uuid.uuid4().hex[:6].upper()}"
    response = {
        "order_id": order_id,
        "status": "ORDERED",
        "vendor_id": payload.vendor_id,
        "dest_facility_id": payload.dest_facility_id,
        "quantity_kg": payload.quantity_kg,
        "mode": payload.transport_mode,
        "ordered_at": datetime.now(timezone.utc).isoformat(),
    }
    DB.setdefault("orders", {})[order_id] = response   # persist so GET /orders/{id} works (Phase 3)
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    _save_snapshot()
    return response


@app.post("/api/v1/shipments/reroute")
def reroute_shipment(payload: RerouteRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    shipment = DB["shipments"].get(payload.shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="SHIPMENT_NOT_FOUND")

    shipment["destination"] = payload.new_destination
    shipment["eta"] = payload.new_eta.isoformat()
    shipment["status"] = "REROUTED"
    shipment["version"] = shipment.get("version", 1) + 1

    response = {
        "shipment_id": payload.shipment_id,
        "status": "REROUTED",
        "new_eta": payload.new_eta.isoformat(),
    }
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    _save_snapshot()
    return response


@app.post("/api/v1/allocations/reserve")
def reserve_allocation(payload: AllocationRequest, x_idempotency_key: str = Header(...)):
    if x_idempotency_key in IDEMPOTENCY_CACHE:
        return IDEMPOTENCY_CACHE[x_idempotency_key]

    facility = DB["inventory"].get(payload.facility_id)
    if not facility or facility["current_stock_kg"] < payload.quantity_kg:
        raise HTTPException(status_code=400, detail="INSUFFICIENT_STOCK_TO_RESERVE")

    # Reserve without moving physical stock between facilities — distinct from TRANSFER.
    reservation_id = f"ALLOC-{uuid.uuid4().hex[:6].upper()}"
    DB.setdefault("allocations", {})[reservation_id] = {
        "reservation_id": reservation_id,
        "facility_id": payload.facility_id,
        "sku_id": payload.sku_id,
        "quantity_kg": payload.quantity_kg,
        "reserved_for": payload.reserved_for,
    }
    response = {
        "reservation_id": reservation_id,
        "status": "RESERVED",
        "quantity_kg": payload.quantity_kg,
    }
    IDEMPOTENCY_CACHE[x_idempotency_key] = response
    _save_snapshot()
    return response


# ----------------------------------------------------------------------------
# Out-of-band telemetry — produces a *real* second disruption, not an injected
# state dict. verify_node's RAW check discovers the excursion on its own.
# ----------------------------------------------------------------------------
@app.post("/api/v1/telemetry/reefer/{transfer_id}")
def report_reefer_telemetry(transfer_id: str, temp_celsius: float):
    if transfer_id not in DB["transfers"]:
        raise HTTPException(status_code=404, detail="TRANSFER_NOT_FOUND")
    DB["transfers"][transfer_id]["current_temp_celsius"] = temp_celsius
    _save_snapshot()
    return {"transfer_id": transfer_id, "current_temp_celsius": temp_celsius}


# ----------------------------------------------------------------------------
# Environment mutation endpoints (Phase 1: environment is the source of truth).
# Disruptions — shipment status, demand surges — enter the world through these
# HTTP endpoints; the agent *discovers* them via its own reads. Nothing is ever
# injected into the agent's state directly.
# ----------------------------------------------------------------------------
@app.post("/api/v1/shipments/{shipment_id}/status")
def set_shipment_status(shipment_id: str, payload: dict):
    """Mutate a shipment's real status (customs hold, delay, release...).

    Bumps `version` so watchers can distinguish mutations. This is the endpoint
    the dashboard/orchestrator uses to set up a scenario — the agent then reads
    the status itself in observe_node.
    """
    shipment = DB["shipments"].get(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="SHIPMENT_NOT_FOUND")
    status = str(payload.get("status", "")).upper()
    allowed = {"IN_TRANSIT", "CUSTOMS_HOLD", "DELAYED", "COMPROMISED", "DELIVERED"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"INVALID_STATUS — allowed: {sorted(allowed)}")
    shipment["status"] = status
    shipment["version"] = shipment.get("version", 1) + 1
    _save_snapshot()
    return {"shipment_id": shipment_id, "status": status, "version": shipment["version"]}


@app.post("/api/v1/demand/signal")
def post_demand_signal(signal: DemandSignal):
    """Record a real demand signal for a facility (burn rate + surge ratio).

    Reuses the DemandSignal model that previously sat unused. observe_node GETs
    this per facility; a surge above config.DEMAND_SURGE_THRESHOLD is what the
    agent *discovers* as a DEMAND_SURGE disruption.
    """
    DB["demand"][signal.facility_id] = signal.model_dump()
    _save_snapshot()
    return {"status": "RECORDED", "facility_id": signal.facility_id, "surge_ratio": signal.surge_ratio}


@app.get("/api/v1/demand/{facility_id}")
def get_demand_signal(facility_id: str):
    signal = DB["demand"].get(facility_id)
    if signal is None:
        # No signal recorded — the agent treats this as baseline demand.
        raise HTTPException(status_code=404, detail="DEMAND_SIGNAL_NOT_FOUND")
    return signal


# ----------------------------------------------------------------------------
# Discovery endpoints (Phase 2: the agent investigates the live environment).
# Candidates are built from THESE reads — no vendor/route/price data is
# hardcoded in the agent. Editing seed_data.json changes the option set.
# ----------------------------------------------------------------------------
@app.get("/api/v1/vendors")
def get_vendors():
    """All vendors with their live conditions (stock, certification, location)."""
    return list(DB.get("vendors", {}).values())


@app.get("/api/v1/vendors/{vendor_id}")
def get_vendor(vendor_id: str):
    vendor = DB.get("vendors", {}).get(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="VENDOR_NOT_FOUND")
    return vendor


@app.post("/api/v1/vendors/{vendor_id}/condition")
def set_vendor_condition(vendor_id: str, payload: dict):
    """Mutate a vendor's live condition (Phase 4: "vendor conditions change").

    Body (both optional): {"stock_available_kg": number, "cdsco_certified": bool}.
    This is an OUT-OF-BAND environment mutation — exactly how a real vendor
    stock-out or certification suspension would enter the world. The agent is
    never told; its own investigation GET must discover the new condition and
    steer the plan around it.
    """
    vendor = DB.get("vendors", {}).get(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="VENDOR_NOT_FOUND")
    changed = {}
    if "stock_available_kg" in payload:
        vendor["stock_available_kg"] = float(payload["stock_available_kg"])
        changed["stock_available_kg"] = vendor["stock_available_kg"]
    if "cdsco_certified" in payload:
        vendor["cdsco_certified"] = bool(payload["cdsco_certified"])
        changed["cdsco_certified"] = vendor["cdsco_certified"]
    if not changed:
        raise HTTPException(status_code=400, detail="NO_CONDITION_FIELDS — allowed: stock_available_kg, cdsco_certified")
    _save_snapshot()
    return {"vendor_id": vendor_id, "condition": vendor, "changed": changed}


@app.get("/api/v1/routes")
def get_routes(from_city: str | None = None, to_city: str | None = None):
    """Transport lanes, optionally filtered by city pair."""
    lanes = DB.get("lanes", [])
    if from_city is not None:
        lanes = [l for l in lanes if l["from_city"].lower() == from_city.lower()]
    if to_city is not None:
        lanes = [l for l in lanes if l["to_city"].lower() == to_city.lower()]
    return lanes


@app.post("/api/v1/tools/cost-carbon")
def cost_carbon(payload: dict):
    """Deterministic cost/carbon/transit calculator over lane physics.

    Body: {origin_city, destination_city, quantity_kg, mode?} — the lane is
    looked up in DB (or taken from the optional inline "lane" for testing).
    Returns {transit_hours, cost_inr, carbon_kg, lane_id, distance_km}.
    Shares the exact math with candidates.lane_quote so agent and API agree.
    """
    from candidates import lane_quote

    lane = payload.get("lane")
    if not lane:
        origin = payload.get("origin_city", "")
        dest = payload.get("destination_city", "")
        matches = [
            l for l in DB.get("lanes", [])
            if l["from_city"].lower() == origin.lower()
            and l["to_city"].lower() == dest.lower()
            and (payload.get("mode") is None or l["mode"] == payload.get("mode"))
        ]
        if not matches:
            raise HTTPException(status_code=404, detail="NO_LANE_BETWEEN_CITIES")
        lane = matches[0]
    qty = float(payload.get("quantity_kg", 0.0))
    quote = lane_quote(lane, qty)
    return {
        "transit_hours": quote["transit_hours"],
        "cost_inr": quote["freight_cost_inr"],
        "carbon_kg": quote["carbon_kg"],
        "lane_id": lane.get("lane_id"),
        "distance_km": quote["distance_km"],
        "mode": quote["mode"],
    }


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "facilities": len(DB["inventory"]), "shipments": len(DB["shipments"])}


@app.get("/api/v1/state")
def read_state():
    """Snapshot the whole sandbox for the Monitor tab.

    Phase 1: includes demand signals so the UI shows the real environment the
    agent sees (not a form value)."""
    return {
        "inventory": list(DB["inventory"].values()),
        "shipments": list(DB["shipments"].values()),
        "transfers": list(DB["transfers"].values()),
        "allocations": list(DB.get("allocations", {}).values()),
        "demand": list(DB.get("demand", {}).values()),
        "vendors": list(DB.get("vendors", {}).values()),
        "lanes": list(DB.get("lanes", [])),
        "orders": list(DB.get("orders", {}).values()),
    }


# ----------------------------------------------------------------------------
# Agent orchestration — one generator drives the graph and yields a rich,
# per-node event carrying the exact state slice each dashboard tab needs
# (candidates for Options, plan+score for Optimize, RAW result for Verify).
# Both the SSE stream and the JSON endpoint reuse it.
# ----------------------------------------------------------------------------
RUN_HISTORY: list = []  # newest last. Each entry is a run summary (persisted, Phase 7).


def _load_history() -> None:
    if not _PERSIST or not os.path.exists(_HISTORY_PATH):
        return
    try:
        with open(_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            RUN_HISTORY.extend(data)
    except (OSError, ValueError):
        pass


def _save_history() -> None:
    if not _PERSIST:
        return
    try:
        tmp = _HISTORY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(RUN_HISTORY[-200:], f)   # cap: last 200 runs
        os.replace(tmp, _HISTORY_PATH)
    except OSError:
        pass


_load_history()


def _agent_iter(payload: dict):
    """Yield (stage, node, state_values) tuples as the graph advances.

    Raises RuntimeError with a readable message if the agent stack is missing.
    """
    try:
        from agent_graph import graph
        from agent_graph import _post as agent_post
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(f"AGENT_UNAVAILABLE: {exc}")

    facility = payload.get("facility_id", "FAC-HYD-GENOME")
    shipment = payload.get("shipment_id", "IMP-JNPT-8802")
    shipment_status = payload.get("shipment_status", "CUSTOMS_HOLD")
    surge = float(payload.get("surge_ratio", 1.0))
    inject_reefer = bool(payload.get("inject_reefer", True))
    inject_vendor_failure = bool(payload.get("inject_vendor_failure", False))
    vendor_id = str(payload.get("vendor_id", "VEND-TAIPEI"))

    # One click = fresh environment + run (Phase 1 / G9): optional reset first,
    # to the chosen base scenario (stock_breach / shipment_only / demand_surge).
    reset_to = str(payload.get("scenario", "stock_breach"))
    if bool(payload.get("reset_scenario")):
        reset({"scenario": reset_to})  # direct call: same process, no HTTP round-trip
        yield {"kind": "node", "stage": 0, "node": "environment",
               "message": f"Scenario reset to seed ({reset_to})."}

    # Phase 1: the requested disruption is applied THROUGH the environment
    # (status + demand endpoints) before the agent streams. The agent's own
    # observe reads will discover these — nothing is injected into its state.
    # (agent_post degrades to None on sandbox-down; the run then proceeds on
    # whatever environment the sandbox currently holds, and audit frames show it.)
    applied = []
    env_setup_failed = False
    yield {"kind": "node", "stage": 0, "node": "environment",
           "message": f"Applying environment: shipment {shipment} -> {shipment_status}, demand surge {surge}x."}
    if agent_post(f"/shipments/{shipment}/status", json={"status": shipment_status}):
        applied.append(f"shipment={shipment_status}")
    else:
        env_setup_failed = True
    demand_body = {
        "facility_id": facility, "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 300.0 * max(surge, 1.0), "forecast_daily_burn_kg": 300.0,
        "surge_ratio": surge,
    }
    if agent_post("/demand/signal", json=demand_body):
        applied.append(f"demand={surge}x")
    else:
        env_setup_failed = True
    if env_setup_failed:
        yield {"kind": "warning", "stage": 0,
               "message": "Environment setup partly failed (sandbox unreachable for some mutations) — agent will observe whatever the sandbox currently holds."}

    thread_id = f"TH-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": facility},
        "shipment_state": {"shipment_id": shipment},   # status hint removed — environment decides
        "demand_state": {},                            # discovered via GET /demand in observe
        "replan_count": 0,
        "invalidated_options": [],
    }

    yield {"kind": "meta", "thread_id": thread_id, "stage": 1}

    def drive(stream, stage):
        for event in stream:
            for node, values in event.items():
                if not isinstance(values, dict):
                    continue
                trail = values.get("audit_trail", [])
                yield {
                    "kind": "node",
                    "stage": stage,
                    "node": node,
                    "message": trail[0] if trail else "",
                    # State slices for the tabs (only what each node produced):
                    "inventory_state": values.get("inventory_state"),
                    "shipment_state": values.get("shipment_state"),
                    "demand_state": values.get("demand_state"),
                    "disruption_info": values.get("disruption_info"),
                    "candidate_options": values.get("candidate_options"),
                    "scored_candidates": values.get("scored_candidates"),
                    "optimal_plan": values.get("optimal_plan"),
                    "governance_approved": values.get("governance_approved"),
                    "execution_result": values.get("execution_result"),
                    "verified": values.get("verified"),
                    "invalidated_options": values.get("invalidated_options"),
                    "computed_required_kg": values.get("computed_required_kg"),
                }

    yield from drive(graph.stream(initial_state, config=cfg), 1)

    reefer_injected = None
    if inject_reefer:
        last = graph.get_state(cfg).values
        transfer_id = last.get("execution_result", {}).get("transfer_id")
        if transfer_id:
            agent_post(
                f"/telemetry/reefer/{transfer_id}",
                params={"temp_celsius": config.REEFER_EXCURSION_TEMP_C},
            )
            reefer_injected = transfer_id
            yield {"kind": "disruption", "stage": 2, "transfer_id": transfer_id,
                   "temp_celsius": config.REEFER_EXCURSION_TEMP_C}
            graph.update_state(cfg, {"verified": False}, as_node="execute")
            yield from drive(graph.stream(None, config=cfg), 2)

    # ------------------------------------------------------------------
    # Stage 3 (Phase 4): the certified vendor's condition changes OUT-OF-BAND
    # (stock-out). The agent is never told — a fresh disruption forces a new
    # investigation, whose own vendor GET discovers the stock-out and steers
    # the plan to the remaining feasible option.
    # ------------------------------------------------------------------
    vendor_failed = None
    if inject_vendor_failure:
        # Force a genuinely new disruption via the environment: fresh demand
        # surge (stock healthy after recovery, so a new problem is needed) plus
        # the out-of-band vendor condition change. The agent is told NEITHER —
        # it re-enters the graph at observe and discovers both itself.
        agent_post("/demand/signal", json={
            "facility_id": facility, "sku_id": "API-AMX-9901",
            "observed_daily_burn_kg": 300.0 * 1.8, "forecast_daily_burn_kg": 300.0,
            "surge_ratio": 1.8,
        })
        cond = agent_post(f"/vendors/{vendor_id}/condition", json={"stock_available_kg": 0.0})
        if cond:
            vendor_failed = vendor_id
            yield {"kind": "disruption", "stage": 3, "vendor_id": vendor_id,
                   "condition": "STOCK_OUT"}
            # Re-enter at START (same thread): checkpointed accumulators persist
            # (audit trail, replan count) while observe re-reads the world — so
            # the agent DISCOVERS the surge and the vendor stock-out on its own.
            reentry = {
                "thread_id": thread_id,
                "inventory_state": {"facility_id": facility},
                "shipment_state": {"shipment_id": shipment},
                "demand_state": {},   # deliberately empty — discover the surge
            }
            yield from drive(graph.stream(reentry, config=cfg), 3)
        else:
            yield {"kind": "warning", "stage": 3,
                   "message": f"Vendor condition mutation failed (sandbox unreachable for {vendor_id}) — stage 3 skipped."}

    final = graph.get_state(cfg).values
    summary = {
        "kind": "final",
        "thread_id": thread_id,
        "reefer_injected": reefer_injected,
        "vendor_failed": vendor_failed,
        "verified": final.get("verified"),
        "replan_count": final.get("replan_count"),
        "final_plan": final.get("optimal_plan", {}),
        "invalidated_options": final.get("invalidated_options", []),
        "params": {
            "facility_id": facility, "shipment_id": shipment,
            "shipment_status": shipment_status, "surge_ratio": surge,
            "inject_reefer": inject_reefer,
            "inject_vendor_failure": inject_vendor_failure,
        },
        "at": datetime.now(timezone.utc).isoformat(),
    }
    RUN_HISTORY.append({k: summary[k] for k in
                        ("thread_id", "verified", "replan_count", "final_plan", "params", "at")})
    _save_history()
    yield summary


@app.get("/api/v1/stream-scenario")
def stream_scenario(
    facility_id: str = "FAC-HYD-GENOME",
    shipment_id: str = "IMP-JNPT-8802",
    shipment_status: str = "CUSTOMS_HOLD",
    surge_ratio: float = 1.0,
    inject_reefer: bool = True,
    inject_vendor_failure: bool = False,
    vendor_id: str = "VEND-TAIPEI",
    reset_scenario: bool = False,
    scenario: str = "stock_breach",
):
    """Server-Sent Events: one frame per graph node, so the UI animates the
    pipeline node-by-node. EventSource can only issue GET, hence query params."""
    from fastapi.responses import StreamingResponse

    payload = {
        "facility_id": facility_id, "shipment_id": shipment_id,
        "shipment_status": shipment_status, "surge_ratio": surge_ratio,
        "inject_reefer": inject_reefer,
        "inject_vendor_failure": inject_vendor_failure,
        "vendor_id": vendor_id,
        "reset_scenario": reset_scenario,
        "scenario": scenario,
    }

    def event_source():
        try:
            for item in _agent_iter(payload):
                yield f"data: {json.dumps(item)}\n\n"
        except RuntimeError as exc:
            yield f"data: {json.dumps({'kind': 'error', 'detail': str(exc)})}\n\n"
        yield "data: {\"kind\": \"done\"}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/run-scenario")
def run_scenario(payload: dict):
    """Non-streaming variant (used by History replay). Collects the same events."""
    try:
        items = list(_agent_iter(payload))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    nodes = [i for i in items if i.get("kind") == "node"]
    final = next((i for i in items if i.get("kind") == "final"), {})
    return {
        "thread_id": final.get("thread_id"),
        "events": nodes,
        "reefer_injected": final.get("reefer_injected"),
        "verified": final.get("verified"),
        "replan_count": final.get("replan_count"),
        "final_plan": final.get("final_plan", {}),
    }


@app.get("/api/v1/history")
def get_history():
    return {"runs": list(reversed(RUN_HISTORY))}


@app.post("/api/v1/environment/apply")
def apply_environment(payload: dict):
    """Apply the control panel's environment setup WITHOUT running the agent.

    Phase 5: 'Apply environment (no run)' — exactly what the orchestrator does
    before stage 1 (reset? + shipment status + demand signal), proving the
    disruption enters via HTTP and the Monitor tab then shows it before any
    agent acts. Returns what actually changed.
    """
    changed = {}
    if bool(payload.get("reset_scenario")):
        result = reset({"scenario": str(payload.get("scenario", "stock_breach"))})
        changed["reset"] = result
    shipment = payload.get("shipment_id", "IMP-JNPT-8802")
    status = str(payload.get("shipment_status", "CUSTOMS_HOLD")).upper()
    target = DB["shipments"].get(shipment)
    if not target:
        raise HTTPException(status_code=404, detail=f"SHIPMENT_NOT_FOUND: {shipment}")
    allowed = {"IN_TRANSIT", "CUSTOMS_HOLD", "DELAYED", "COMPROMISED", "DELIVERED"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"INVALID_STATUS — allowed: {sorted(allowed)}")
    target["status"] = status
    target["version"] = target.get("version", 1) + 1
    changed["shipment"] = {"shipment_id": shipment, "status": status, "version": target["version"]}

    facility = payload.get("facility_id", "FAC-HYD-GENOME")
    if facility not in DB["inventory"]:
        raise HTTPException(status_code=404, detail=f"FACILITY_NOT_FOUND: {facility}")
    surge = float(payload.get("surge_ratio", 1.0))
    signal = DemandSignal(
        facility_id=facility, sku_id="API-AMX-9901",
        observed_daily_burn_kg=300.0 * max(surge, 1.0),
        forecast_daily_burn_kg=300.0, surge_ratio=surge,
    )
    DB["demand"][facility] = signal.model_dump()
    _save_snapshot()
    changed["demand"] = {"facility_id": facility, "surge_ratio": surge}
    return {"status": "APPLIED", "changed": changed}
