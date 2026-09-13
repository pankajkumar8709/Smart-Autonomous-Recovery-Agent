# Autonomous Retail Supply Chain Recovery Agent

Problem Statement 6. A closed-loop agent that monitors a simulated logistics
environment, detects disruptions, investigates alternatives, optimizes under
cost/delivery/carbon constraints, executes a real state-changing action against
the sandbox, verifies the result with a Read-After-Write check, and replans when
an alternative fails or a new disruption occurs.

Domain skin: pharma cold-chain (CDSCO compliance + 2–8 °C reefer envelope). This
is realism flavor layered on top of the seven generic PS requirements — none of
it is load-bearing to the workflow.

**The anti-fake contract** (enforced by the test suite):

1. **Environment is the single source of truth.** No disruption parameter
   reaches the agent except via an HTTP read of the sandbox — shipment status,
   demand, vendor conditions are set through environment endpoints and
   *discovered* by the agent's own `observe`/`investigate` GETs.
2. **Nothing hardcoded.** Candidate options, quantities, ETAs, and costs are
   discovered or computed from sandbox data (vendors, lanes, cost-carbon
   calculator) at run time. Editing `seed_data.json` demonstrably changes the
   option set; deleting the candidate-generation loops changes nothing because
   there are no constants to delete.
3. **Every write is checked by a read.** `verify_node` re-reads real state
   (Read-After-Write) before claiming success.
4. **Every failure is survivable.** Sandbox errors degrade to audit + replan or
   escalation — never a crash, never a fabricated success.

## Architecture

```
observe → detect → investigate → optimize → governance → execute → verify
    ^          |         ^                          |            |
    |          |         └─────── replan loops ─────┴────────────┘
    └── stage re-entry (vendor stock-out re-observes the world)
```

Every action node calls the sandbox for real:
- `observe_node` → real GETs: inventory, shipment, **demand signal**; syncs the
  digital twin (which `detect_node` reads — the twin is load-bearing)
- `investigate_node` → real GETs: `/vendors`, `/routes`, `/inventory`; prices
  each (option × lane) via `/tools/cost-carbon`; builds candidates from live
  data only (`candidates.py` — pure, unit-tested)
- `execute_node` → real HTTP POST to `/orders/purchase`, `/transfers/dispatch`,
  `/shipments/reroute`, or `/allocations/reserve` (idempotent via
  `x-idempotency-key`)
- `verify_node` → real RAW GET on inventory and (for reefer transfers) the
  transfer record; discovers a cold-chain excursion on its own

Three genuine disruptions, all originating in the environment:
1. **Primary** — customs hold / safety-stock breach / demand surge (set via
   `POST /shipments/{id}/status`, `POST /demand/signal`)
2. **Secondary** — reefer excursion (out-of-band `POST /telemetry/reefer/{id}`)
3. **Tertiary** — vendor stock-out (out-of-band `POST /vendors/{id}/condition`);
   the graph re-enters at observe and the agent *discovers* the vendor is gone

State persists in SQLite via LangGraph's `SqliteSaver`, so the graph genuinely
resumes mid-flow rather than restarting.

## PS requirement → code

| PS bullet | Where |
|---|---|
| Monitor inventory **and** shipment (+ demand, + vendor conditions) | `observe_node` (real GETs each tick); Monitor tab shows all four |
| Detect disruption / constraint violation | `detect_node` (safety stock via inventory, shipment status via twin, demand surge via discovered signal); negative control passes end-to-end |
| Investigate vendors/routes/allocations | `candidates.build_candidates` from `GET /vendors` + `GET /routes`, priced via `POST /tools/cost-carbon`; computed deficit `max(0, safety−current) + surge buffer`; editing seed data changes the option set |
| Optimize feasible actions | `optimizer.evaluate_and_optimize` (hard-bound filter → cost/time/carbon score); uncertified vendor investigated then rejected by the filter |
| Execute reroute/purchase/allocate/transfer | `execute_node` (4 real idempotent endpoints); quantities computed from the deficit |
| Verify inventory + delivery state | `verify_node` — per-action RAW re-GET of the mutated record: PURCHASE → `GET /orders/{id}` (status ORDERED, vendor matches), REROUTE → `GET /shipments/{id}` (status REROUTED/IN_TRANSIT), ALLOCATE → `GET /allocations/{id}` (exists, quantity matches), TRANSFER → `GET /transfers/{id}` (+ reefer temp); plus inventory RAW read and the recovery gate (stock disruptions require stock to clear the floor). Tamper tests prove a server-side revert or vanished record is caught and fails into replan |
| Replan on failure / new disruption | verify-fail loop + governance-reject loop (both exclude the failed option) + stage re-entry for the vendor stock-out; all three disruptions are real environment events |

## Run

```bash
pip install -r requirements.txt

# 1. Start the sandbox (port follows SANDBOX_PORT, default 8000 — set the same
#    value for both processes so the agent inside the sandbox points at itself)
uvicorn sandbox_api:app --host 127.0.0.1 --port 8000
#    or:  SANDBOX_PORT=8001 uvicorn sandbox_api:app --host 127.0.0.1 --port 8001

# 2a. Run the scripted demos
python scenarios.py          # double disruption: breach → reefer excursion → replan
python scenarios.py vendor   # vendor stock-out: breach → out-of-band stock-out + surge → replan

# 2b. Or the React 19 dashboard (Vite + styled-components, light theme):
#     cd dashboard-react && npm install && npm run dev   -> http://localhost:5173
#     (Vite proxies /api to the sandbox; port follows SANDBOX_PORT — see dashboard-react/README.md)

# 3. Run the test suite
#    unit only (no server):    pytest -v -m "not integration"
#    full (sandbox running):   pytest -v
```

Sandbox port conflicts: if 8000 is occupied by a stale process, run everything
on 8001 via `SANDBOX_PORT=8001` (sandbox, tests, and Vite proxy all honor it).

## Files

| File | Role |
|---|---|
| `config.py` | URLs/ports (`SANDBOX_PORT`), optimizer weights, governance limits, cold-chain bounds, discovery constants |
| `models.py` | Pydantic request models (one per action type + demand signal) |
| `sandbox_api.py` | FastAPI simulated logistics environment: 4 state-changing action endpoints, read endpoints, vendor/demand/condition mutations, cost-carbon calculator, SSE orchestrator, `/environment/apply`, JSON-snapshot persistence |
| `seed_data.json` | Facilities (with cities) / shipments / vendors (with location, cost, lead, stock) / lanes — the single source of candidate data |
| `candidates.py` | **Pure** discovery engine: `compute_required_kg`, `lane_quote` (deterministic lane physics), `build_candidates` |
| `optimizer.py` | Feasibility filter + multi-constraint scoring |
| `governance.py` | Bounded-autonomy veto (compliance / qty / spend ceilings) |
| `digital_twin.py` | In-memory telemetry mirror (load-bearing: detect reads it) |
| `agent_graph.py` | LangGraph state machine (the agent) with `_get`/`_post` graceful degradation |
| `scenarios.py` | Demo runners: `python scenarios.py [vendor]` |
| `dashboard-react/` | React 19 + styled-components dashboard (Vite, light theme; see its own README) |
| `tests/test_agent.py` | 8 unit (optimizer/governance) + 17 integration (all 4 action types, replan loops, environment-as-truth, sandbox-down escalation, vendor conditions, `/environment/apply`, per-action RAW re-GET + tamper tests) |
| `tests/test_candidates.py` | 14 unit tests for the discovery engine (deficit math, deterministic pricing, live-data filters, uncertified passthrough) |
| `pytest.ini` | pytest config (registers the `integration` marker) |
| `PERSISTENCE.md` | Persistence design notes (snapshot semantics, escape hatches, demo implications) |
| `.github/workflows/ci.yml` | CI: unit + integration (boots ephemeral sandbox) + dashboard build |

## Honest limits (state these to judges, don't hide them)

- The environment is a simulation (that's what the PS asks for) — but all
  agent ↔ environment interaction is real HTTP with real state mutation and
  RAW reads.
- The agent's reasoning is deterministic rule-based (no LLM) — a deliberate
  reliability choice; "autonomous" here means the closed loop, not a chatbot.
- Sandbox persistence is a JSON snapshot (write-through on every mutation), not
  a transactional database — right-sized for a demo; see `PERSISTENCE.md`.

## Persistence (Phase 7)

Sandbox state and run history survive restarts via `sandbox_snapshot.json` /
`run_history.json` (atomic write-through on every mutation; corrupt snapshots
fall back to seed). Escape hatches: `SANDBOX_PERSIST=0` for fully in-memory
(CI uses this), `SANDBOX_SNAPSHOT_PATH` / `SANDBOX_HISTORY_PATH` to relocate,
and `POST /reset` to return to seed — which is also persisted. **Note:**
restarting the sandbox no longer resets the demo; use `/reset` or the
dashboard's "Reset environment first" for a fresh environment.

## CI

`.github/workflows/ci.yml` runs three jobs on push/PR: unit tests (no sandbox),
the full integration suite against a booted ephemeral sandbox
(`SANDBOX_PERSIST=0`), and a dashboard production build.
