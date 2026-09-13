"""Unit tests for candidates.py — Phase 2 discovery-driven investigation.

Pure functions, no server required: run with `pytest -m "not integration"`.
The fixture env mirrors seed_data.json so a regression here means the seed and
the discovery math have drifted apart.
"""
import json
import os
from datetime import datetime

import pytest

import config
from candidates import build_candidates, compute_required_kg, lane_quote
from optimizer import evaluate_and_optimize


@pytest.fixture
def env():
    """Live-environment fixture mirroring seed_data.json (pure dicts, no I/O)."""
    return {
        "inventory": {
            "FAC-HYD-GENOME": {
                "facility_id": "FAC-HYD-GENOME", "name": "Hyderabad Genome Valley Cold Store",
                "city": "Hyderabad", "sku_id": "API-AMX-9901",
                "current_stock_kg": 1200.0, "safety_stock_kg": 4000.0,
                "storage_temp_celsius": 4.0,
            },
            "FAC-VIZAG-COLD": {
                "facility_id": "FAC-VIZAG-COLD", "name": "Visakhapatnam Port Cold Chain Hub",
                "city": "Visakhapatnam", "sku_id": "API-AMX-9901",
                "current_stock_kg": 22000.0, "safety_stock_kg": 6000.0,
                "storage_temp_celsius": 4.0,
            },
        },
        "target": None,  # set per-test (defaults to FAC-HYD-GENOME record)
        "shipment": {
            "shipment_id": "IMP-JNPT-8802", "origin": "Taipei",
            "destination": "FAC-HYD-GENOME", "status": "CUSTOMS_HOLD",
            "quantity_kg": 5000.0,
        },
        "vendors": [
            {"vendor_id": "VEND-TAIPEI", "name": "Taipei Bio API Ltd", "location_city": "Taipei",
             "unit_cost_inr": 2400.0, "lead_time_hours": 2.0, "stock_available_kg": 20000.0,
             "cdsco_certified": True},
            {"vendor_id": "VEND-LOCAL", "name": "Local Grey-Market Supplier", "location_city": "Hyderabad",
             "unit_cost_inr": 180.0, "lead_time_hours": 6.0, "stock_available_kg": 8000.0,
             "cdsco_certified": False},
        ],
        "lanes": [
            {"lane_id": "LANE-TPE-HYD-AIR", "from_city": "Taipei", "to_city": "Hyderabad",
             "mode": "AIR_CARGO", "distance_km": 4400.0, "avg_speed_kmh": 400.0,
             "cost_per_km_per_kg": 0.5, "co2_per_km_per_kg": 0.0002},
            {"lane_id": "LANE-VZG-HYD-REEFER", "from_city": "Visakhapatnam", "to_city": "Hyderabad",
             "mode": "REEFER_TRUCK", "distance_km": 620.0, "avg_speed_kmh": 45.0,
             "cost_per_km_per_kg": 0.04, "co2_per_km_per_kg": 0.00012},
            {"lane_id": "LANE-HYD-LOCAL-TRUCK", "from_city": "Hyderabad", "to_city": "Hyderabad",
             "mode": "LOCAL_TRUCK", "distance_km": 45.0, "avg_speed_kmh": 30.0,
             "cost_per_km_per_kg": 0.02, "co2_per_km_per_kg": 0.0001},
        ],
        "demand": None,
        "now": datetime(2026, 9, 13, 12, 0, 0),
    }


def _with_target(env, facility_id="FAC-HYD-GENOME"):
    env["target"] = env["inventory"][facility_id]
    return env


# ---------------------------------------------------------------------------
# Deficit math — quantity computed, never a constant
# ---------------------------------------------------------------------------
def test_required_kg_is_the_deficit():
    inv = {"current_stock_kg": 1200.0, "safety_stock_kg": 4000.0}
    assert compute_required_kg(inv, None) == 2800.0


def test_required_kg_adds_surge_buffer_only_above_threshold():
    healthy = {"current_stock_kg": 6000.0, "safety_stock_kg": 4000.0}
    # Baseline demand: no buffer.
    assert compute_required_kg(healthy, {"surge_ratio": 1.0}) == 0.0
    # Surge 1.8: buffer = safety * 0.8 * SURGE_BUFFER_FRACTION.
    expected = 4000.0 * 0.8 * config.SURGE_BUFFER_FRACTION
    assert compute_required_kg(healthy, {"surge_ratio": 1.8}) == pytest.approx(expected)


def test_required_kg_never_negative():
    overstocked = {"current_stock_kg": 9000.0, "safety_stock_kg": 4000.0}
    assert compute_required_kg(overstocked, None) == 0.0


# ---------------------------------------------------------------------------
# Lane pricing — deterministic, honest math
# ---------------------------------------------------------------------------
def test_lane_quote_deterministic_physics():
    lane = {"lane_id": "L", "mode": "REEFER_TRUCK", "distance_km": 620.0,
            "avg_speed_kmh": 45.0, "cost_per_km_per_kg": 0.04, "co2_per_km_per_kg": 0.00012}
    q = lane_quote(lane, 2800.0)
    assert q["transit_hours"] == pytest.approx(620.0 / 45.0 + 2.0, abs=0.01)   # + cold-chain handling
    assert q["freight_cost_inr"] == pytest.approx(2800.0 * 620.0 * 0.04)
    assert q["carbon_kg"] == pytest.approx(2800.0 * 620.0 * 0.00012)
    # Deterministic: same inputs, same numbers.
    assert lane_quote(lane, 2800.0) == q


# ---------------------------------------------------------------------------
# build_candidates — discovery from the environment fixture
# ---------------------------------------------------------------------------
def test_stock_breach_builds_purchases_and_transfer_from_live_data(env):
    _with_target(env)
    out = build_candidates(env, ["SAFETY_STOCK_BREACH"], [], 2800.0)

    types = {c["type"] for c in out}
    assert types == {"PURCHASE", "TRANSFER"}

    ids = {c["id"] for c in out}
    # Ids are composed from sandbox identifiers — proof of derivation.
    assert "PURCHASE-VEND-TAIPEI-LANE-TPE-HYD-AIR" in ids
    assert "PURCHASE-VEND-LOCAL-LANE-HYD-LOCAL-TRUCK" in ids
    assert "TRANSFER-FAC-VIZAG-COLD-LANE-VZG-HYD-REEFER" in ids

    taipei = next(c for c in out if c["vendor_id"] == "VEND-TAIPEI")
    assert taipei["quantity_kg"] == 2800.0                       # computed, not 5000
    assert taipei["unit_cost_inr"] == pytest.approx(2400.0 + 4400.0 * 0.5)   # vendor + freight/kg
    assert taipei["transit_time_hours"] == pytest.approx(2.0 + (4400.0 / 400.0 + 2.0))  # lead + transit


def test_uncertified_vendor_is_investigated_then_rejected_by_optimizer(env):
    """The investigator passes the uncertified vendor through; the optimizer's
    feasibility filter (not the investigator) drops it — so the UI can show it
    was considered and rejected (manual test plan bullet 3)."""
    _with_target(env)
    out = build_candidates(env, ["SAFETY_STOCK_BREACH"], [], 2800.0)
    local = next(c for c in out if c["vendor_id"] == "VEND-LOCAL")
    assert local["cdsco_certified"] is False          # passed through by the investigator

    scored = evaluate_and_optimize(out, max_allowed_hours=config.MAX_ALLOWED_HOURS)
    assert all(c.get("vendor_id") != "VEND-LOCAL" for c in scored)   # dropped by the optimizer


def test_out_of_stock_vendor_is_excluded_by_live_data(env):
    _with_target(env)
    env["vendors"][0]["stock_available_kg"] = 100.0   # Taipei can no longer supply
    out = build_candidates(env, ["SAFETY_STOCK_BREACH"], [], 2800.0)
    assert all(c.get("vendor_id") != "VEND-TAIPEI" for c in out)


def test_transfer_requires_real_surplus(env):
    _with_target(env)
    env["inventory"]["FAC-VIZAG-COLD"]["current_stock_kg"] = 6500.0   # surplus 500 < 2800
    out = build_candidates(env, ["SAFETY_STOCK_BREACH"], [], 2800.0)
    assert not any(c["type"] == "TRANSFER" for c in out)


def test_reroute_uses_alternative_lanes_and_computes_eta(env):
    _with_target(env)
    out = build_candidates(env, ["SHIPMENT_CUSTOMS_HOLD"], [], 0.0)
    reroutes = [c for c in out if c["type"] == "REROUTE"]
    assert reroutes, "pure shipment disruption must produce reroute candidates"
    # The lane the shipment is nominally on is not offered as an "alternative".
    assert all(c["lane_id"] != "LANE-TPE-HYD-AIR" for c in reroutes)
    for c in reroutes:
        # ETA is computed from lane physics + now, not a literal date string.
        eta = datetime.fromisoformat(c["new_eta"])
        assert eta > env["now"]
        assert c["quantity_kg"] == 5000.0   # the shipment's own quantity


def test_demand_surge_adds_allocate_candidate_sized_to_live_stock(env):
    _with_target(env)
    env["inventory"]["FAC-HYD-GENOME"]["current_stock_kg"] = 6000.0   # healthy
    env["demand"] = {"surge_ratio": 1.8}
    required = compute_required_kg(env["target"], env["demand"])
    out = build_candidates(env, ["DEMAND_SURGE"], [], required)
    alloc = [c for c in out if c["type"] == "ALLOCATE"]
    assert len(alloc) == 1
    assert alloc[0]["quantity_kg"] == pytest.approx(required)   # min(stock, required) = required
    assert alloc[0]["sku_id"] == "API-AMX-9901"                 # discovered from the facility


def test_zero_requirement_builds_no_zero_quantity_actions(env):
    """Healthy stock + baseline demand: nothing needs to move, so no 0-kg
    stock-adder is proposed (an 'action' that moves nothing is a fake).
    A classified-but-satisfied reason yields honest emptiness — no fallback."""
    _with_target(env)
    env["inventory"]["FAC-HYD-GENOME"]["current_stock_kg"] = 6000.0
    out = build_candidates(env, ["SAFETY_STOCK_BREACH"], [], 0.0)
    assert out == []
    # ...while a genuinely unclassified reason still gets the full option set.
    out_any = build_candidates(env, ["SOMETHING_ELSE"], [], 0.0)
    assert out_any, "unclassified reason must fall back to all action types"


def test_replan_with_zero_requirement_still_offers_reroute(env):
    """Replan after a stock recovery: required=0 means no 0-kg stock-adders, but
    a still-active shipment problem must still get its reroute candidates."""
    _with_target(env)
    env["inventory"]["FAC-HYD-GENOME"]["current_stock_kg"] = 9000.0   # breach cleared
    out = build_candidates(env, ["SAFETY_STOCK_BREACH", "SHIPMENT_CUSTOMS_HOLD"], [], 0.0)
    types = {c["type"] for c in out}
    assert "REROUTE" in types
    assert "PURCHASE" not in types and "TRANSFER" not in types


def test_invalidated_options_are_excluded(env):
    _with_target(env)
    out = build_candidates(env, ["SAFETY_STOCK_BREACH"],
                           ["TRANSFER-FAC-VIZAG-COLD-LANE-VZG-HYD-REEFER"], 2800.0)
    assert all(c["id"] != "TRANSFER-FAC-VIZAG-COLD-LANE-VZG-HYD-REEFER" for c in out)


def test_seed_and_fixture_env_agree():
    """Guard against drift: the fixture mirrors seed_data.json's vendor/lane data."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "seed_data.json"), encoding="utf-8") as f:
        seed = json.load(f)
    assert seed["vendors"]["VEND-TAIPEI"]["unit_cost_inr"] == 2400.0
    assert seed["vendors"]["VEND-TAIPEI"]["location_city"] == "Taipei"
    lanes = {l["lane_id"]: l for l in seed["lanes"]}
    assert lanes["LANE-VZG-HYD-REEFER"]["distance_km"] == 620.0
    assert seed["inventory"]["FAC-HYD-GENOME"]["city"] == "Hyderabad"
