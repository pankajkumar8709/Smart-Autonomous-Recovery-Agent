"""Multi-constraint optimizer: filter feasible actions, then score them.

Contract used by agent_graph.optimize_node:
    evaluate_and_optimize(candidates, max_allowed_hours) -> list[dict]
    - returns candidates sorted best-first, each augmented with a "score" key
    - an empty list means nothing satisfied the hard bounds

Scoring is lower-is-better across normalized cost / time / carbon, so a cheap,
fast, low-carbon option wins. Hard bounds (transit time, CDSCO certification)
are applied as a feasibility filter BEFORE scoring — an infeasible option is
never scored, never selected.
"""
from typing import Any, Dict, List

import config


def _normalize(values: List[float]) -> List[float]:
    """Min-max normalize to 0..1; degenerate (all-equal) ranges map to 0.0."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _is_feasible(c: Dict[str, Any], max_allowed_hours: float) -> bool:
    if c.get("transit_time_hours", float("inf")) > max_allowed_hours:
        return False
    if config.REQUIRE_CDSCO_CERTIFIED and not c.get("cdsco_certified", False):
        return False
    return True


def evaluate_and_optimize(
    candidates: List[Dict[str, Any]],
    max_allowed_hours: float = config.MAX_ALLOWED_HOURS,
) -> List[Dict[str, Any]]:
    feasible = [c for c in candidates if _is_feasible(c, max_allowed_hours)]
    if not feasible:
        return []

    costs = _normalize([c["unit_cost_inr"] * c["quantity_kg"] for c in feasible])
    times = _normalize([c["transit_time_hours"] for c in feasible])
    carbons = _normalize([c["carbon_per_kg_co2"] * c["quantity_kg"] for c in feasible])

    scored: List[Dict[str, Any]] = []
    for c, nc, nt, ncarb in zip(feasible, costs, times, carbons):
        score = (
            config.WEIGHT_COST * nc
            + config.WEIGHT_TIME * nt
            + config.WEIGHT_CARBON * ncarb
        )
        scored.append({**c, "score": score})

    scored.sort(key=lambda c: c["score"])
    return scored
