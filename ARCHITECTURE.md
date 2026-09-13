# System Architecture & Workflow — Autonomous Retail Supply Chain Recovery Agent

**Problem Statement 6.** A closed-loop autonomous agent that keeps a simulated
logistics network at its service objective when inventory, shipment, vendor, or
demand conditions change. Domain skin: pharma cold-chain (CDSCO compliance +
2–8 °C envelope) layered on a domain-agnostic recovery engine.

> Design contract ("real, no fake"): the agent reasons only over data it **reads
> from the environment**, every action is **executed and verified against real
> state**, and every disruption **originates in the environment** — nothing is
> told to the agent that it could discover itself.

---

## 1. High-level shape

Three processes, all local, talking over HTTP:

```
┌──────────────────────────┐        SSE (text/event-stream)         ┌───────────────────────────┐
│  React 19 Dashboard       │  ◀───────────────────────────────────  │  FastAPI Orchestrator      │
│  (Vite + styled-comp.)    │   GET /api/v1/stream-scenario           │  (inside sandbox_api.py)   │
│  Monitor / Options /      │  ───────────────────────────────────▶  │  drives the agent graph,   │
│  Trail / History tabs     │   POST /environment/apply, /reset       │  emits one frame per node  │
└──────────────────────────┘                                          └─────────────┬─────────────┘
                                                                                     │ in-process
                                                                                     ▼
                                                              ┌──────────────────────────────────┐
                                                              │  LangGraph Agent (agent_graph.py)  │
                                                              │  observe→detect→investigate→       │
                                                              │  optimize→govern→execute→verify    │
                                                              │  + two replan loops                │
                                                              └─────────────┬──────────────────────┘
                                                                            │ real HTTP (httpx), never in-process fakes
                                                                            ▼
                                                              ┌──────────────────────────────────┐
                                                              │  Simulated Logistics Sandbox       │
                                                              │  (FastAPI, sandbox_api.py)         │
                                                              │  state-changing + read + telemetry │
                                                              │  + discovery (vendors/routes/calc) │
                                                              │  persisted to sandbox_snapshot.json│
                                                              └────────────────────────────────────┘
```

The orchestrator and the agent graph live in the **same** FastAPI process
(`sandbox_api.py` imports `agent_graph` lazily); the sandbox is the same process
too. They still communicate over real HTTP (`127.0.0.1:8000`) so every
agent↔environment interaction is a genuine network call with real state
mutation — not an in-process shortcut.

---

## 2. Component map (what each file is)

| File | Role |
|---|---|
| `config.py` | Single source of constants: sandbox URL/port (env-overridable), optimizer hard bounds + scoring weights, governance ceilings, cold-chain envelope, surge threshold, handling-cost rates, replan cap, checkpoint path. |
| `models.py` | Pydantic request models — one per action type (`TransferRequest`, `PurchaseRequest`, `RerouteRequest`, `AllocationRequest`) + `DemandSignal`. |
| `sandbox_api.py` | The simulated environment **and** the SSE orchestrator. ~27 endpoints: state-changing, reads, telemetry, discovery, tools, scenario control, persistence. |
| `candidates.py` | **Pure** discovery logic. `compute_required_kg` (deficit + surge buffer) and `build_candidates` (vendors×lanes, surplus facilities×lanes, reroute lanes, own-stock allocation) priced by lane physics. No I/O — unit-testable without a server. |
| `optimizer.py` | Feasibility filter (transit-time bound + CDSCO) then weighted cost/time/carbon score. Lower score wins. |
| `governance.py` | Bounded-autonomy veto: compliance, quantity ceiling, spend ceiling → `(approved, reason)`. |
| `digital_twin.py` | In-memory mirror of observed telemetry; `detect_node` reads shipment status from its snapshot (load-bearing). |
| `agent_graph.py` | The LangGraph state machine: 7 nodes, 3 conditional edges, 2 replan loops, `_get`/`_post` graceful-degradation helpers, SQLite checkpointer. |
| `scenarios.py` | CLI runner for the multi-disruption scenario. |
| `dashboard-react/` | React 19 + styled-components live dashboard (SSE-driven, tabbed, light theme). |
| `tests/` | `test_agent.py` + `test_candidates.py` — unit + integration (all four action types, replan, tamper/RAW checks). |
| `seed_data.json` | Initial environment: facilities (with city), shipments, vendors (location/stock/lead/cost/cert), lanes (distance/speed/cost/CO₂), demand. |
| `sandbox_snapshot.json` / `run_history.json` | Persisted runtime state (Phase 7). |

---

## 3. The core workflow — one recovery cycle (maps 1:1 to PS bullets)

The agent is a **LangGraph state machine** over a typed `SupplyState`. Each node
is named for what it does and actually does it against the sandbox.

```
        START
          │
          ▼
    ┌───────────┐   PS-1  Monitor inventory AND shipment (AND demand)
    │  observe  │   GET /inventory/{id}, /shipments/{id}, /demand/{id}
    └─────┬─────┘   → syncs the digital twin (both domains)
          ▼
    ┌───────────┐   PS-2  Detect disruption / constraint violation
    │  detect   │   SAFETY_STOCK_BREACH | SHIPMENT_* | DEMAND_SURGE
    └─────┬─────┘   (reads shipment status from the twin snapshot)
          │  route_detection: disruption? → investigate : END
          ▼
    ┌─────────────┐  PS-3  Investigate vendors / routes / allocations
    │ investigate │  GET /vendors, /routes, /inventory, /demand;
    └──────┬──────┘  POST /tools/cost-carbon; candidates.build_candidates()
          │          quantity = computed deficit + surge buffer (not a constant)
          ▼
    ┌───────────┐   PS-4  Optimize FEASIBLE actions
    │ optimize  │   feasibility filter (time bound + CDSCO) → cost/time/carbon score
    └─────┬─────┘   emits scored_candidates (feasible + infeasible-with-reason) for UI
          ▼
    ┌────────────┐  Bounded autonomy gate
    │ governance │  compliance / qty / spend ceilings → (approved, reason)
    └─────┬──────┘  route_governance: approved → execute
          │                          rejected  → investigate (exclude option) ↺
          │                          exhausted → END (human escalation)
          ▼
    ┌───────────┐   PS-5  Execute a REAL reroute/purchase/allocate/transfer
    │  execute  │   POST /orders/purchase | /transfers/dispatch |
    └─────┬─────┘   /shipments/reroute | /allocations/reserve  (idempotent)
          ▼
    ┌───────────┐   PS-6  Verify inventory AND delivery state
    │  verify   │   RAW GET of inventory + re-GET the mutated record
    └─────┬─────┘   (order/transfer/shipment/reservation) + cold-chain + recovery gate
          │  route_verification:
          │     verified            → END (recovered)
          │     failed & <cap       → investigate (exclude option) ↺  PS-7 Replan
          │     failed & ≥cap       → END (human escalation)
          ▼
         END
```

### Node-by-node detail

- **observe** — real GETs for inventory, shipment, and **demand** (demand is an
  environment signal, discovered over HTTP, not injected). Synchronizes the
  digital twin with both inventory and shipments. If the sandbox is unreachable
  it does **not** invent a healthy world — it flags `SANDBOX_UNREACHABLE` and the
  router escalates to a human.
- **detect** — flags `SAFETY_STOCK_BREACH` (stock < safety), `SHIPMENT_<status>`
  (customs hold / delayed / compromised), and `DEMAND_SURGE`
  (`surge_ratio > DEMAND_SURGE_THRESHOLD`). Reads shipment status from the twin
  snapshot (twin is load-bearing).
- **investigate** — discovers the option set from live data: GETs vendors,
  routes/lanes, all facility inventories, demand; computes the required quantity
  (`max(0, safety − current) + surge buffer`); calls the sandbox cost-carbon tool
  to corroborate lane math; delegates to the pure `build_candidates`. A
  `resolves` filter admits only action types that can structurally fix the active
  disruption (breach → PURCHASE/TRANSFER; surge → ALLOCATE/PURCHASE/TRANSFER;
  shipment → REROUTE/PURCHASE/TRANSFER). Nothing is hardcoded — editing
  `seed_data.json` changes what the agent finds.
- **optimize** — drops infeasible options (over the transit-time bound or not
  CDSCO-certified) then scores the rest on weighted cost/time/carbon; lowest
  score wins. Publishes the full scored table (with reasons for the dropped ones)
  for the Options tab.
- **governance** — enforces bounded autonomy: compliance, single-action quantity
  ceiling, total-spend ceiling. Rejection loops back to investigation with the
  option excluded; exhaustion escalates to a human.
- **execute** — makes the real, idempotent (`x-idempotency-key`) state-changing
  call for the chosen action type. A sandbox blip yields `SANDBOX_UNREACHABLE`
  routed into replan — never a fabricated success.
- **verify** — Read-After-Write: RAW GET of destination inventory **plus** a
  re-GET of the exact record the action mutated (order / transfer / shipment /
  reservation). The recovery gate requires stock to clear the safety floor when
  the disruption was a stock/demand problem, so a reroute or allocation that adds
  no physical stock cannot be reported as a stock-breach recovery. A cold-chain
  excursion on the transfer record (from out-of-band reefer telemetry) fails
  verification into a replan.

### The three conditional edges (PS-7 replan)

- `route_detection`: no disruption → END; sandbox unreachable → END (escalate).
- `route_governance`: approved → execute; rejected & under cap → investigate;
  over cap → END.
- `route_verification`: verified → END; failed & under cap → investigate; over
  cap → END.

Replans exclude the failed/rejected option (`invalidated_options`, a reducer
list) so the agent never re-proposes a known-bad action, and the `MAX_REPLANS`
cap turns an unresolvable situation into a clean human escalation instead of an
infinite loop.

---

## 4. State, persistence & resume

- **Agent state** is a LangGraph `SupplyState` (TypedDict) checkpointed in SQLite
  (`agent_state.db`) via `SqliteSaver`. This is what makes the multi-disruption
  demo real: after Stage 1 recovers, an out-of-band event (reefer telemetry)
  mutates the sandbox, then `graph.update_state(...) + stream(None, ...)`
  **resumes the same thread mid-graph** — the agent re-enters `verify`,
  independently discovers the excursion, and replans.
- **Sandbox state** is persisted to `sandbox_snapshot.json` atomically on every
  mutation, and `run_history.json` keeps the last 200 run summaries. On startup
  the sandbox loads the snapshot (healed from seed if a collection is missing;
  corrupt snapshots are ignored). `SANDBOX_PERSIST=0` gives classic
  in-memory / reset-on-restart behavior (used by CI).

---

## 5. Sandbox endpoint surface (the environment API)

| Group | Endpoints |
|---|---|
| Reads | `GET /inventory`, `/inventory/{id}`, `/shipments/{id}`, `/transfers/{id}`, `/orders/{id}`, `/allocations/{id}`, `/demand/{id}`, `/vendors`, `/vendors/{id}`, `/routes`, `/state`, `/health` |
| State-changing (idempotent) | `POST /transfers/dispatch`, `/orders/purchase`, `/shipments/reroute`, `/allocations/reserve` |
| Environment conditions | `POST /shipments/{id}/status`, `/demand/signal`, `/vendors/{id}/condition`, `/telemetry/reefer/{transfer_id}`, `DELETE /allocations/{id}` |
| Tools | `POST /tools/cost-carbon` (deterministic transit/cost/carbon from lane physics) |
| Orchestration | `GET /stream-scenario` (SSE), `POST /run-scenario`, `GET /history`, `POST /environment/apply`, `POST /reset` |

Every state-changing endpoint takes an `x-idempotency-key` so a replan retry is
safe; every mutation persists the snapshot.

---

## 6. Frontend workflow (React 19)

The dashboard opens an `EventSource` on `GET /stream-scenario`. The
`useScenarioStream` hook accumulates: the ordered node events (Trail + pipeline),
the latest live state slices (Monitor/Options), the active node, and the final
summary. As each SSE frame arrives, the **pipeline diagram lights the node**, the
KPI row updates, and the tab bodies re-render:

- **Monitor** — facility stock bars vs safety, cold-chain temp badges, shipment
  status, in-transit reefer temp, disruption alert.
- **Options** — the scored candidate table (cost/transit/carbon/CDSCO/score),
  winner highlighted, infeasible struck-through, governance verdict, execution
  result.
- **Trail** — every node event as a card, grouped by disruption stage.
- **History** — past runs with outcome, params, and selected plan.

Vite proxies `/api` → `127.0.0.1:8000`, so the browser stays same-origin.

---

## 7. Data flow of one full "double disruption" run

1. Dashboard `POST /environment/apply` (+ optional `/reset`) sets the disruption
   in the **environment**, then opens the SSE stream.
2. `observe` reads inventory/shipment/demand; `detect` flags `SAFETY_STOCK_BREACH`.
3. `investigate` discovers vendors/lanes, computes the deficit, prices candidates.
4. `optimize` picks the reefer transfer; `governance` approves it within limits.
5. `execute` POSTs `/transfers/dispatch` — stock physically moves; `verify` RAW-reads
   inventory (recovered) and the transfer record (cold-chain OK) → **verified**.
6. Out-of-band: `POST /telemetry/reefer/{transfer_id}` reports +14 °C — a real
   second disruption the agent was never told about.
7. The graph resumes mid-thread; `verify` re-reads the transfer record, sees the
   excursion, fails, and **replans** — investigate excludes the failed transfer,
   optimize picks the air purchase, execute + verify → **recovered, replan_count=1**.

Every step above is a real HTTP call against real, persisted state.

---

## 8. Tech stack

- **Agent:** Python, LangGraph (state machine + SQLite checkpoint resume), httpx.
- **Environment/API:** FastAPI + Uvicorn, Pydantic v2, JSON-snapshot persistence.
- **Frontend:** React 19, styled-components, Vite, SSE (EventSource).
- **Reasoning:** deterministic rule-based (no LLM) — a reliability choice;
  "autonomous" here means the closed detect→act→verify→replan loop.
- **Tests/CI:** pytest (unit + integration), GitHub Actions (unit / integration
  with ephemeral sandbox / dashboard build).

---

## 9. Honest limits (state these openly)

- The environment is a **simulation** — but all agent↔environment interaction is
  real HTTP with real state mutation and RAW reads.
- Reasoning is deterministic rule-based, not an LLM — deliberate for reliability
  and auditability.
- The sandbox and orchestrator share a process; they still use real HTTP between
  the agent and the environment, so the "real, not faked" property holds.
