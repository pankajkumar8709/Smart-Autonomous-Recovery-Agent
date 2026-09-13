"""Central configuration for the Autonomous Supply Chain Recovery Agent.

Keeping these in one place so the sandbox, the agent graph, and the scenario
runner all agree on URLs, ports, and the hard operational bounds the optimizer
and governance layer enforce.
"""
import os

# --- Sandbox service ---
# Port is env-overridable so a zombie socket on the default port never blocks a
# demo: run `SANDBOX_PORT=8001 uvicorn sandbox_api:app --port 8001` and point
# the dashboard proxy at the same value.
SANDBOX_HOST = "127.0.0.1"
SANDBOX_PORT = int(os.environ.get("SANDBOX_PORT", "8000"))
API_PREFIX = "/api/v1"
SANDBOX_URL = f"http://{SANDBOX_HOST}:{SANDBOX_PORT}{API_PREFIX}"

# --- Optimizer hard bounds (feasibility filter, applied before scoring) ---
MAX_ALLOWED_HOURS = 16.0          # any option slower than this is infeasible
REQUIRE_CDSCO_CERTIFIED = True    # domain layer: drop non-compliant vendors outright

# --- Optimizer scoring weights (lower score == better; normalized 0..1 each) ---
WEIGHT_COST = 0.5
WEIGHT_TIME = 0.3
WEIGHT_CARBON = 0.2

# --- Governance bounded-autonomy limits ---
MAX_AUTONOMOUS_SPEND_INR = 15_000_000.0   # total spend (unit_cost * qty) the agent may commit unattended
MAX_AUTONOMOUS_QTY_KG = 10_000.0          # single-action quantity ceiling

# --- Cold-chain envelope (domain specialization) ---
COLD_CHAIN_MIN_C = 2.0
COLD_CHAIN_MAX_C = 8.0
# Excursion temperature for injected reefer disruptions, derived from the
# envelope so scenario code never hardcodes a magic number.
REEFER_EXCURSION_TEMP_C = COLD_CHAIN_MAX_C + 6.0

# --- Demand conditions (Phase 1: demand is a real environment signal) ---
DEMAND_SURGE_THRESHOLD = 1.3   # surge_ratio above this is a DEMAND_SURGE disruption

# --- Discovery-driven candidate math (Phase 2: nothing hardcoded) ---
# Surge buffer: fraction of the deficit-to-floor added as demand headroom when
# observed burn exceeds forecast (candidates.compute_required_kg).
SURGE_BUFFER_FRACTION = 0.5
# Handling costs per kg — internal policy rates, NOT lane physics.
TRANSFER_HANDLING_COST_PER_KG = 360.0   # cold-store-to-cold-store handling
REROUTE_HANDLING_COST_PER_KG = 90.0     # interchange re-handling fee
ALLOCATE_HANDLING_COST_PER_KG = 20.0    # internal reservation handling

# --- Replan loop safety ---
MAX_REPLANS = 3   # route_* edges escalate to END once replan_count exceeds this

# --- Checkpoint store ---
CHECKPOINT_DB = "agent_state.db"
