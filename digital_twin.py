"""Digital-twin substrate — an in-memory mirror of sandbox telemetry.

Contract used by agent_graph:
    twin = DigitalTwinSubstrate(initial_state={"inventory": {}, "shipments": {}})
    twin.synchronize_telemetry({"inventory": {facility_id: {...}}})

The twin keeps the agent's latest observed view of the world separate from the
authoritative sandbox, so reasoning nodes can inspect a coherent snapshot and a
future extension could detect drift between twin and sandbox. It merges rather
than replaces, so a partial telemetry push only updates the keys it carries.
"""
from typing import Any, Dict


class DigitalTwinSubstrate:
    def __init__(self, initial_state: Dict[str, Any] | None = None):
        self.state: Dict[str, Any] = initial_state or {"inventory": {}, "shipments": {}}
        self.sync_count: int = 0

    def synchronize_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Deep-merge a telemetry payload into the twin's current view."""
        for domain, records in telemetry.items():
            bucket = self.state.setdefault(domain, {})
            if isinstance(records, dict):
                bucket.update(records)
            else:
                self.state[domain] = records
        self.sync_count += 1

    def snapshot(self, domain: str, key: str) -> Dict[str, Any]:
        return self.state.get(domain, {}).get(key, {})
