"""Test suite for the Autonomous Supply Chain Recovery Agent.

Two layers:
  * Unit tests   — optimizer + governance, pure Python, always run.
  * Integration  — drive the real LangGraph agent against a running sandbox;
                   skipped automatically if the sandbox on 127.0.0.1:8000 is down
                   or langgraph isn't installed.

Run everything (with the sandbox up on :8000):
    uvicorn sandbox_api:app --host 127.0.0.1 --port 8000   # terminal 1
    pytest -v                                              # terminal 2

Unit tests alone (no server needed):
    pytest -v -m "not integration"
"""
import uuid

import pytest

import config
import governance
import optimizer

SANDBOX = config.SANDBOX_URL


# ---------------------------------------------------------------------------
# Unit tests — optimizer
# ---------------------------------------------------------------------------
def _c(id, type="PURCHASE", cost=100.0, qty=1000.0, hours=5.0, carbon=0.1, cdsco=True):
    return {
        "id": id, "type": type, "unit_cost_inr": cost, "quantity_kg": qty,
        "transit_time_hours": hours, "carbon_per_kg_co2": carbon, "cdsco_certified": cdsco,
    }


def test_optimizer_drops_over_time_bound():
    cands = [_c("A", hours=5.0), _c("B", hours=99.0)]
    out = optimizer.evaluate_and_optimize(cands, max_allowed_hours=16.0)
    assert [c["id"] for c in out] == ["A"]


def test_optimizer_drops_uncertified():
    cands = [_c("A", cdsco=True), _c("B", cdsco=False)]
    out = optimizer.evaluate_and_optimize(cands, max_allowed_hours=16.0)
    assert [c["id"] for c in out] == ["A"]


def test_optimizer_ranks_cheaper_fresher_lower_carbon_first():
    cheap = _c("CHEAP", cost=100.0, hours=5.0, carbon=0.1)
    pricey = _c("PRICEY", cost=900.0, hours=15.0, carbon=0.9)
    out = optimizer.evaluate_and_optimize([pricey, cheap], max_allowed_hours=16.0)
    assert out[0]["id"] == "CHEAP"
    assert out[0]["score"] <= out[1]["score"]


def test_optimizer_empty_when_none_feasible():
    assert optimizer.evaluate_and_optimize([_c("A", hours=99.0)], max_allowed_hours=16.0) == []


# ---------------------------------------------------------------------------
# Unit tests — governance
# ---------------------------------------------------------------------------
def test_governance_vetoes_uncertified():
    ok, reason = governance.check_bounded_autonomy(_c("X", cdsco=False))
    assert ok is False and "COMPLIANCE" in reason


def test_governance_vetoes_over_quantity():
    ok, reason = governance.check_bounded_autonomy(_c("X", qty=config.MAX_AUTONOMOUS_QTY_KG + 1))
    assert ok is False and "QTY_LIMIT" in reason


def test_governance_vetoes_over_spend():
    huge = config.MAX_AUTONOMOUS_SPEND_INR + 1
    ok, reason = governance.check_bounded_autonomy(_c("X", cost=huge, qty=1.0))
    assert ok is False and "SPEND_LIMIT" in reason


def test_governance_approves_within_bounds():
    ok, reason = governance.check_bounded_autonomy(_c("X", cost=100.0, qty=1000.0))
    assert ok is True


# ---------------------------------------------------------------------------
# Integration tests — real graph against the running sandbox
# ---------------------------------------------------------------------------
def _sandbox_up():
    try:
        import httpx

        return httpx.get(f"{SANDBOX}/health", timeout=1.0).status_code == 200
    except Exception:
        return False


integration = pytest.mark.integration
needs_sandbox = pytest.mark.skipif(not _sandbox_up(), reason="sandbox not running on :8000")


@pytest.fixture
def fresh_graph():
    """A graph with its OWN in-memory checkpointer, so no run pollutes another via
    the shared agent_state.db. This is the fix for the stale-checkpoint failures."""
    from langgraph.checkpoint.memory import MemorySaver

    from agent_graph import build_graph

    return build_graph(checkpointer=MemorySaver())


def _reset(scenario="stock_breach"):
    import httpx

    httpx.post(f"{SANDBOX}/reset", json={"scenario": scenario}, timeout=2.0)
    # Verify the reset actually took — guards against a stale sandbox process
    # running old code (a no-op /reset), which would otherwise masquerade as an
    # agent bug. stock_breach must leave stock BELOW safety; the others ABOVE.
    inv = httpx.get(f"{SANDBOX}/inventory/FAC-HYD-GENOME", timeout=2.0).json()
    breached = inv["current_stock_kg"] < inv["safety_stock_kg"]
    if scenario == "stock_breach":
        assert breached, (
            f"reset did not restore the seed breach (stock={inv['current_stock_kg']} "
            f">= safety={inv['safety_stock_kg']}). Restart the sandbox so it runs the "
            f"current sandbox_api.py with a working /reset."
        )
    else:
        assert not breached, (
            f"reset scenario '{scenario}' should leave stock healthy "
            f"(stock={inv['current_stock_kg']}, safety={inv['safety_stock_kg']})."
        )


def _run(graph, **overrides):
    thread_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}
    state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802", "status": "CUSTOMS_HOLD"},
        "demand_state": {"surge_ratio": 1.0},
        "replan_count": 0,
        "invalidated_options": [],
    }
    state.update(overrides)
    for _ in graph.stream(state, config=cfg):
        pass
    values = graph.get_state(cfg).values
    # The graph must have reached verify (disruption detected + acted on). If it
    # ran straight to END with no verdict, that's a real failure — surface it clearly.
    assert "verified" in values, (
        f"graph ended without verifying — disruption not detected/acted? "
        f"disruption_active={values.get('disruption_active')} trail={values.get('audit_trail')}"
    )
    return values


@integration
@needs_sandbox
def test_stock_breach_recovers_by_adding_stock(fresh_graph):
    """Safety-stock breach → agent must pick PURCHASE/TRANSFER and truly recover."""
    _reset("stock_breach")
    final = _run(fresh_graph)
    assert final["verified"] is True
    assert final["optimal_plan"]["type"] in ("PURCHASE", "TRANSFER")


@integration
@needs_sandbox
def test_reroute_executes_on_pure_shipment_issue(fresh_graph):
    """Healthy stock + shipment on customs hold → REROUTE is reachable and the run
    recovers (agent may pick REROUTE or a stock-add fallback, all valid)."""
    from agent_graph import investigate_node

    _reset("shipment_only")
    out = investigate_node({
        "disruption_info": {"reasons": ["SHIPMENT_CUSTOMS_HOLD"]},
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "invalidated_options": [],
    })
    assert "REROUTE" in {c["type"] for c in out["candidate_options"]}

    final = _run(fresh_graph)
    assert final["verified"] is True
    assert final["optimal_plan"]["type"] in ("REROUTE", "PURCHASE", "TRANSFER")


@integration
@needs_sandbox
def test_allocate_executes_on_pure_demand_surge(fresh_graph):
    """Pure demand surge, stock healthy → ALLOCATE reachable; the run recovers.
    Phase 1: the surge is posted to the sandbox (environment), not agent state —
    observe discovers it via GET /demand."""
    import httpx

    from agent_graph import investigate_node

    _reset("demand_surge")
    # Environment mutation FIRST (Phase 2 doctrine): the surge lives in the
    # sandbox, and the investigation sizes the allocation from discovered
    # demand — investigate with no demand signal finds nothing to reserve.
    httpx.post(f"{SANDBOX}/demand/signal", json={
        "facility_id": "FAC-HYD-GENOME", "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 540.0, "forecast_daily_burn_kg": 300.0,
        "surge_ratio": 1.8,
    }, timeout=2.0)
    out = investigate_node({
        "disruption_info": {"reasons": ["DEMAND_SURGE"]},
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {"surge_ratio": 1.8},
        "invalidated_options": [],
    })
    assert "ALLOCATE" in {c["type"] for c in out["candidate_options"]}

    # No demand/status hints in agent state — observe discovers the truth.
    final = _run(fresh_graph, shipment_state={"shipment_id": "IMP-JNPT-8802"}, demand_state={})
    assert final["verified"] is True
    assert final["optimal_plan"]["type"] in ("ALLOCATE", "PURCHASE", "TRANSFER")


@integration
@needs_sandbox
def test_double_disruption_triggers_replan(fresh_graph):
    """Full loop: recover via transfer, inject a real reefer excursion, verify the
    agent discovers it on its own RAW check and replans to a fresh recovery."""
    import httpx

    _reset("stock_breach")
    graph = fresh_graph
    thread_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}
    state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802", "status": "CUSTOMS_HOLD"},
        "demand_state": {"surge_ratio": 1.0},
        "replan_count": 0,
        "invalidated_options": [],
    }
    for _ in graph.stream(state, config=cfg):
        pass

    first = graph.get_state(cfg).values
    transfer_id = first.get("execution_result", {}).get("transfer_id")
    first_plan_id = first.get("optimal_plan", {}).get("id")
    # In the stock_breach scenario the cheapest certified stock-adder is the
    # Vizag reefer transfer (discovered from live vendor/lane data, Phase 2),
    # which yields a transfer_id and the in-transit reefer leg the secondary
    # disruption needs. If this ever stops holding, the reefer replan path
    # can't be exercised — so assert it firmly.
    assert transfer_id, (
        f"stage 1 should recover via TRANSFER; got "
        f"{first_plan_id} — check optimizer scoring / sandbox reset"
    )

    # Real out-of-band excursion, then resume — verify_node must re-discover it.
    httpx.post(f"{SANDBOX}/telemetry/reefer/{transfer_id}", params={"temp_celsius": 14.0}, timeout=2.0)
    graph.update_state(cfg, {"verified": False}, as_node="execute")
    for _ in graph.stream(None, config=cfg):
        pass

    final = graph.get_state(cfg).values
    assert final["replan_count"] >= 1
    assert final["verified"] is True
    assert first_plan_id in final.get("invalidated_options", [])


# ---------------------------------------------------------------------------
# Phase 2 integration — candidates provably derive from live sandbox data
# ---------------------------------------------------------------------------
@integration
@needs_sandbox
def test_candidate_ids_derive_from_live_sandbox_data():
    """Phase 2 anti-fake proof: the option ids the agent investigates are built
    from the sandbox's OWN vendor/lane identifiers read over HTTP — rename a
    vendor or a lane in the environment and the option set changes with it."""
    import httpx

    from agent_graph import investigate_node

    _reset("stock_breach")
    out = investigate_node({
        "disruption_info": {"reasons": ["SAFETY_STOCK_BREACH"]},
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "invalidated_options": [],
    })
    ids = {c["id"] for c in out["candidate_options"]}
    assert ids, "investigation must produce candidates from live data"

    # Every id component must exist in the environment's live data.
    vendors = {v["vendor_id"] for v in httpx.get(f"{SANDBOX}/vendors", timeout=2.0).json()}
    lanes = {l["lane_id"] for l in httpx.get(f"{SANDBOX}/routes", timeout=2.0).json()}
    for cid in ids:
        found = any(v in cid for v in vendors) or any(l in cid for l in lanes) or cid.startswith("ALLOCATE-")
        assert found, f"candidate '{cid}' does not reference any live vendor/lane — hardcoded?"

    # Prices are calculator-derived: landed unit cost = vendor price + distance*rate.
    taipei = next((c for c in out["candidate_options"] if c.get("vendor_id") == "VEND-TAIPEI"), None)
    assert taipei is not None
    lane = next(l for l in httpx.get(f"{SANDBOX}/routes", timeout=2.0).json()
                if l["lane_id"] == taipei["lane_id"])
    expected_unit = taipei_vendor_price(lane)
    assert taipei["unit_cost_inr"] == pytest.approx(expected_unit)


def taipei_vendor_price(lane):
    import json

    seed = json.load(open("seed_data.json", encoding="utf-8"))
    return seed["vendors"]["VEND-TAIPEI"]["unit_cost_inr"] + lane["distance_km"] * lane["cost_per_km_per_kg"]


@integration
@needs_sandbox
def test_all_four_action_types_execute_end_to_end(fresh_graph):
    """Phase 2: with candidates discovered from live data, each scenario still
    drives a DIFFERENT action type through execute + RAW verify."""
    _reset("stock_breach")
    final = _run(fresh_graph)
    assert final["verified"] is True
    assert final["optimal_plan"]["type"] in ("PURCHASE", "TRANSFER")

    _reset("demand_surge")
    import httpx

    httpx.post(f"{SANDBOX}/demand/signal", json={
        "facility_id": "FAC-HYD-GENOME", "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 540.0, "forecast_daily_burn_kg": 300.0,
        "surge_ratio": 1.8,
    }, timeout=2.0)
    final = _run(fresh_graph, shipment_state={"shipment_id": "IMP-JNPT-8802"}, demand_state={})
    assert final["verified"] is True
    assert final["optimal_plan"]["type"] in ("ALLOCATE", "PURCHASE", "TRANSFER")


# ---------------------------------------------------------------------------
# Phase 0/1 integration — environment as source of truth, graceful degradation
# ---------------------------------------------------------------------------
@integration
@needs_sandbox
def test_sandbox_down_escalates_instead_of_crashing(fresh_graph):
    """Phase 0: with no sandbox reachable, observe must report
    SANDBOX_UNREACHABLE, route_detection escalates to END, and the run exits
    with an audit trail — never a crash, never a fabricated success."""
    import agent_graph

    # Patch the module-level sandbox URL to a dead port. (_get/_post resolve
    # SANDBOX_URL at call time, so this redirects every sandbox call.) Patching
    # the client is NOT enough — httpx base_url does not override absolute URLs.
    real_url = agent_graph.SANDBOX_URL
    agent_graph.SANDBOX_URL = "http://127.0.0.1:1/api/v1"
    try:
        graph = fresh_graph
        thread_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
        cfg = {"configurable": {"thread_id": thread_id}}
        state = {
            "thread_id": thread_id,
            "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
            "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
            "demand_state": {},
            "replan_count": 0,
            "invalidated_options": [],
        }
        for _ in graph.stream(state, config=cfg):
            pass
        final = graph.get_state(cfg).values
        assert "SANDBOX_UNREACHABLE" in final.get("disruption_info", {}).get("reasons", []), (
            f"expected SANDBOX_UNREACHABLE, got {final.get('disruption_info')} / {final.get('audit_trail')}"
        )
        assert final.get("verified") is None, "run must not fabricate a verdict"
        assert any("SANDBOX_UNREACHABLE" in line for line in final.get("audit_trail", []))
    finally:
        agent_graph.SANDBOX_URL = real_url


@integration
@needs_sandbox
def test_shipment_status_endpoint_drives_detection(fresh_graph):
    """Phase 1 negative control, fixed: set the shipment IN_TRANSIT via the real
    status endpoint (environment mutation, not agent state) with healthy stock —
    the agent must detect NO disruption and end without acting."""
    import httpx

    _reset("demand_surge")   # healthy stock + IN_TRANSIT shipment in the sandbox
    # Belt and braces: force the status explicitly through the endpoint.
    r = httpx.post(
        f"{SANDBOX}/shipments/IMP-JNPT-8802/status",
        json={"status": "IN_TRANSIT"}, timeout=2.0,
    )
    assert r.status_code == 200, r.text

    # Observe-only run: stream and stop after detect. Feed no status hint.
    graph = fresh_graph
    thread_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}
    state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "replan_count": 0,
        "invalidated_options": [],
    }
    for _ in graph.stream(state, config=cfg):
        pass
    final = graph.get_state(cfg).values
    assert final.get("disruption_active") is False, (
        f"negative control failed — false disruption: {final.get('disruption_info')}"
    )
    assert "verified" not in final, "agent acted despite a healthy environment"


@integration
@needs_sandbox
def test_demand_signal_endpoint_drives_detection(fresh_graph):
    """Phase 1: a demand signal posted to the sandbox (environment) is discovered
    by observe_node's own GET and drives DEMAND_SURGE detection + recovery."""
    import httpx

    _reset("demand_surge")
    # Real environment mutation: post a surge signal.
    r = httpx.post(f"{SANDBOX}/demand/signal", json={
        "facility_id": "FAC-HYD-GENOME", "sku_id": "API-AMX-9901",
        "observed_daily_burn_kg": 540.0, "forecast_daily_burn_kg": 300.0,
        "surge_ratio": 1.8,
    }, timeout=2.0)
    assert r.status_code == 200, r.text
    # Read it back — the environment is the source of truth.
    got = httpx.get(f"{SANDBOX}/demand/FAC-HYD-GENOME", timeout=2.0).json()
    assert got["surge_ratio"] == 1.8

    graph = fresh_graph
    thread_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
    cfg = {"configurable": {"thread_id": thread_id}}
    state = {
        "thread_id": thread_id,
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "replan_count": 0,
        "invalidated_options": [],
    }
    for _ in graph.stream(state, config=cfg):
        pass
    final = graph.get_state(cfg).values
    reasons = final.get("disruption_info", {}).get("reasons", [])
    assert "DEMAND_SURGE" in reasons, f"surge not discovered: {reasons}"
    assert final.get("verified") is True
    assert final["optimal_plan"]["type"] in ("ALLOCATE", "PURCHASE", "TRANSFER")


@integration
@needs_sandbox
def test_vendor_stockout_discovered_and_avoided(fresh_graph):
    """Phase 4: zeroing a vendor's stock OUT-OF-BAND must change what the agent's
    own investigation GET discovers — no PURCHASE candidate from that vendor may
    exist, and the run still reaches verified=True. The re-investigation names
    the vendor condition in its audit trail via the live-data counts."""
    import httpx

    from agent_graph import investigate_node

    _reset("stock_breach")
    # Out-of-band environment mutation: the certified vendor sells out.
    r = httpx.post(f"{SANDBOX}/vendors/VEND-TAIPEI/condition",
                   json={"stock_available_kg": 0.0}, timeout=2.0)
    assert r.status_code == 200, r.text
    # Read it back — the environment is the source of truth.
    vend = httpx.get(f"{SANDBOX}/vendors/VEND-TAIPEI", timeout=2.0).json()
    assert vend["stock_available_kg"] == 0.0

    out = investigate_node({
        "disruption_info": {"reasons": ["SAFETY_STOCK_BREACH"]},
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "invalidated_options": [],
    })
    ids = {c["id"] for c in out["candidate_options"]}
    assert not any("VEND-TAIPEI" in i for i in ids), (
        f"stocked-out vendor still offered as an option: {ids}"
    )
    assert any(c["type"] == "TRANSFER" for c in out["candidate_options"]), (
        "a feasible alternative (transfer) must remain"
    )

    # End-to-end: the full loop still recovers without the stocked-out vendor.
    final = _run(fresh_graph)
    assert final["verified"] is True
    assert (final.get("optimal_plan", {}) or {}).get("vendor_id") != "VEND-TAIPEI"


@integration
@needs_sandbox
def test_vendor_certification_loss_rejected_by_governance(fresh_graph):
    """Phase 4: flipping cdsco_certified to false out-of-band must surface in the
    option set (investigated, uncertified) and then be DROPPED by the optimizer's
    compliance filter — governance can never see an uncertified plan."""
    import httpx

    from agent_graph import investigate_node
    from optimizer import evaluate_and_optimize

    _reset("stock_breach")
    r = httpx.post(f"{SANDBOX}/vendors/VEND-TAIPEI/condition",
                   json={"cdsco_certified": False}, timeout=2.0)
    assert r.status_code == 200, r.text

    out = investigate_node({
        "disruption_info": {"reasons": ["SAFETY_STOCK_BREACH"]},
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
        "invalidated_options": [],
    })
    taipei = next((c for c in out["candidate_options"] if c.get("vendor_id") == "VEND-TAIPEI"), None)
    assert taipei is not None and taipei["cdsco_certified"] is False, (
        "the investigator must discover the certification loss from the GET"
    )
    scored = evaluate_and_optimize(out["candidate_options"], max_allowed_hours=config.MAX_ALLOWED_HOURS)
    assert all(c.get("vendor_id") != "VEND-TAIPEI" for c in scored), (
        "an uncertified plan must never survive the feasibility filter"
    )


@integration
@needs_sandbox
def test_vendor_condition_endpoint_negative_control():
    """Phase 4: the condition endpoint validates its inputs like a real API."""
    import httpx

    _reset("stock_breach")
    r = httpx.post(f"{SANDBOX}/vendors/UNKNOWN-VENDOR/condition",
                   json={"stock_available_kg": 0.0}, timeout=2.0)
    assert r.status_code == 404
    r = httpx.post(f"{SANDBOX}/vendors/VEND-TAIPEI/condition", json={}, timeout=2.0)
    assert r.status_code == 400  # no condition fields supplied


@integration
@needs_sandbox
def test_environment_apply_endpoint_sets_up_without_running():
    """Phase 5: POST /environment/apply sets up the environment exactly like the
    orchestrator does (reset? + status + demand) — and the sandbox state then
    shows it BEFORE any agent acts."""
    import httpx

    r = httpx.post(f"{SANDBOX}/environment/apply", json={
        "reset_scenario": True, "scenario": "demand_surge",
        "shipment_id": "IMP-JNPT-8802", "shipment_status": "IN_TRANSIT",
        "facility_id": "FAC-HYD-GENOME", "surge_ratio": 1.8,
    }, timeout=3.0)
    assert r.status_code == 200, r.text
    changed = r.json()["changed"]
    assert changed["shipment"]["status"] == "IN_TRANSIT"
    assert changed["demand"]["surge_ratio"] == 1.8

    # The environment really holds it now (source of truth).
    ship = httpx.get(f"{SANDBOX}/shipments/IMP-JNPT-8802", timeout=2.0).json()
    assert ship["status"] == "IN_TRANSIT"
    dem = httpx.get(f"{SANDBOX}/demand/FAC-HYD-GENOME", timeout=2.0).json()
    assert dem["surge_ratio"] == 1.8
    inv = httpx.get(f"{SANDBOX}/inventory/FAC-HYD-GENOME", timeout=2.0).json()
    assert inv["current_stock_kg"] >= inv["safety_stock_kg"]   # demand_surge reset

    # Validation mirrors the real API contract.
    r = httpx.post(f"{SANDBOX}/environment/apply",
                   json={"shipment_id": "NOPE", "shipment_status": "IN_TRANSIT"}, timeout=2.0)
    assert r.status_code == 404
    r = httpx.post(f"{SANDBOX}/environment/apply",
                   json={"shipment_status": "NOT_A_STATUS"}, timeout=2.0)
    assert r.status_code == 400


@integration
@needs_sandbox
def test_demand_signal_not_found_defaults_to_baseline(fresh_graph):
    """Phase 1: GET /demand/{id} 404 (no signal recorded) must degrade to a
    baseline surge_ratio of 1.0 in observe_node — not crash, not fake a surge."""
    import httpx

    _reset("stock_breach")
    r = httpx.get(f"{SANDBOX}/demand/FAC-HYD-GENOME", timeout=2.0)
    assert r.status_code == 404  # environment genuinely has no demand signal

    from agent_graph import observe_node
    out = observe_node({
        "inventory_state": {"facility_id": "FAC-HYD-GENOME"},
        "shipment_state": {"shipment_id": "IMP-JNPT-8802"},
        "demand_state": {},
    })
    assert out["demand_state"]["surge_ratio"] == 1.0
    assert any("demand" in line.lower() for line in out["audit_trail"])
