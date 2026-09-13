"""Scenario runner — the double-disruption demo.

Stage 1: primary disruption (customs hold + safety-stock breach) → agent
recovers autonomously. Stage 2: a REAL secondary disruption is produced by
calling the out-of-band reefer telemetry endpoint (not by injecting state), and
the agent's own verify step discovers it and replans.

Phase 1: the environment is set up through real endpoints first (shipment
status + demand signal), so the agent discovers the disruption itself.

Requires the sandbox running:  uvicorn sandbox_api:app --host 127.0.0.1 --port 8000
Then:  python scenarios.py
"""
import sys
import uuid

import config
from agent_graph import graph, _post, SANDBOX_URL


def _print_events(stream):
    for event in stream:
        for node, values in event.items():
            trail = values.get("audit_trail", [""]) if isinstance(values, dict) else [""]
            print(f"[{node}] -> {trail[0] if trail else ''}")


def run_double_disruption_scenario():
    thread_id = f"TH-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}

    # Phase 1: set up the environment via the sandbox, not via agent state.
    # The agent's observe_node discovers the customs hold + demand itself.
    print("=== STAGE 0: Environment setup (via real endpoints) ===")
    _post(f"/shipments/IMP-JNPT-8802/status", json={"status": "CUSTOMS_HOLD"})
    _post("/demand/signal", json={
        "facility_id": "FAC-HYD-GENOME", "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 300.0, "forecast_daily_burn_kg": 300.0,
        "surge_ratio": 1.0,
    })
    print("Environment: shipment CUSTOMS_HOLD, demand baseline.")

    initial_state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},   # status comes from the sandbox
        "demand_state": {},                                   # demand comes from the sandbox
        "replan_count": 0,
        "invalidated_options": [],
    }

    print("\n=== STAGE 1: Primary Disruption ===")
    _print_events(graph.stream(initial_state, config=cfg))

    # Real secondary disruption: an out-of-band telematics event, exactly like a
    # reefer truck's webhook. It does NOT touch the graph's state directly.
    excursion_temp = config.REEFER_EXCURSION_TEMP_C
    print(f"\n=== STAGE 2: Real Secondary Disruption — reefer compressor failure ({excursion_temp}C) ===")
    last_state = graph.get_state(cfg).values
    transfer_id = last_state.get("execution_result", {}).get("transfer_id")
    if transfer_id:
        _post(f"/telemetry/reefer/{transfer_id}", params={"temp_celsius": excursion_temp})
        print(f"Telemetry: transfer {transfer_id} now reporting +{excursion_temp}C (excursion).")

        # Force verify_node to re-run against the now-degraded transfer record.
        graph.update_state(cfg, {"verified": False}, as_node="execute")
        _print_events(graph.stream(None, config=cfg))
    else:
        print("Stage 1 recovery was not a TRANSFER (no reefer leg) — no secondary excursion to inject.")

    final = graph.get_state(cfg).values
    print("\n=== FINAL AUDIT TRAIL ===")
    for line in final.get("audit_trail", []):
        print(f"  {line}")
    print(f"\nverified={final.get('verified')} replan_count={final.get('replan_count')}")


def run_vendor_disruption_scenario():
    """Phase 4 demo — the third disruption: vendor conditions change.

    Stage 1: primary disruption, agent recovers. Stage 2: OUT-OF-BAND, the
    certified vendor stocks out AND a fresh demand surge hits (both via real
    environment endpoints, neither told to the agent). The graph re-enters at
    observe on the SAME thread; the agent's own investigation GET discovers
    the vendor is gone and steers the plan to the remaining feasible option.
    """
    thread_id = f"TH-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}

    print("=== STAGE 0: Environment setup (via real endpoints) ===")
    _post(f"/shipments/IMP-JNPT-8802/status", json={"status": "CUSTOMS_HOLD"})
    _post("/demand/signal", json={
        "facility_id": "FAC-HYD-GENOME", "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 300.0, "forecast_daily_burn_kg": 300.0,
        "surge_ratio": 1.0,
    })
    print("Environment: shipment CUSTOMS_HOLD, demand baseline.")

    initial_state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "replan_count": 0,
        "invalidated_options": [],
    }

    print("\n=== STAGE 1: Primary Disruption ===")
    _print_events(graph.stream(initial_state, config=cfg))

    print("\n=== STAGE 2: Out-of-band vendor stock-out (VEND-TAIPEI) + fresh demand surge ===")
    _post("/vendors/VEND-TAIPEI/condition", json={"stock_available_kg": 0.0})
    _post("/demand/signal", json={
        "facility_id": "FAC-HYD-GENOME", "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 300.0 * 1.8, "forecast_daily_burn_kg": 300.0,
        "surge_ratio": 1.8,
    })
    print("Environment: VEND-TAIPEI stock_available_kg=0, demand surge 1.8x. Agent told nothing.")

    # Re-enter at START on the same thread: the agent re-observes the world and
    # must DISCOVER the vendor condition + surge via its own GETs.
    reentry = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
    }
    _print_events(graph.stream(reentry, config=cfg))

    final = graph.get_state(cfg).values
    plan = final.get("optimal_plan", {})
    print("\n=== FINAL AUDIT TRAIL ===")
    for line in final.get("audit_trail", []):
        print(f"  {line}")
    print(f"\nverified={final.get('verified')} replan_count={final.get('replan_count')}")
    print(f"final plan: {plan.get('id')}")
    if plan.get("vendor_id") == "VEND-TAIPEI":
        print("FAILURE: agent purchased from the stocked-out vendor!")
    else:
        print("OK: the stocked-out vendor was discovered and avoided.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "vendor":
        run_vendor_disruption_scenario()
    else:
        run_double_disruption_scenario()
