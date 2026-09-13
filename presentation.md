# Autonomous Retail Supply Chain Recovery Agent — Presentation

Problem Statement 6: an autonomous agent that maintains service objectives when inventory, shipment, vendor, or demand conditions change. Domain skin: pharma cold-chain (CDSCO compliance + 2–8 °C reefer envelope).

> One-liner: **"An autonomous agent that keeps a pharma cold-chain supply network at its service level when things break — customs holds, demand spikes, vendor stock-outs, even a refrigeration failure in transit — and proves every recovery with real reads, not claims."**

---

## Slide 1 — The Problem

Supply chains break constantly: a customs hold traps an inbound API shipment, demand spikes 1.8×, a certified vendor sells out, a reefer truck's compressor fails at +14 °C.

Humans firefight these by hand; scripted automation fakes success. The problem statement explicitly demands:

1. Monitor inventory **and** shipment state (we add demand + vendor conditions)
2. Detect a disruption or constraint violation
3. Investigate alternative vendors / routes / allocations
4. Optimize under cost / delivery / carbon constraints
5. Execute a reroute, purchase, allocation, or transfer
6. Verify the resulting inventory and delivery state
7. **Replan** when the chosen alternative fails or a new disruption occurs

And it warns against fixed prompt chains that pretend to succeed. Our answer: a closed loop where every stage does the real thing.

## Slide 2 — The Anti-Fake Contract (our differentiator)

Judges have seen scripted prompt chains. This project is provably different — four rules, enforced by the test suite:

1. **Environment is the single source of truth.** No disruption parameter ever reaches the agent except via an HTTP read the agent itself performs. Disruptions are injected into the sandbox (`POST /shipments/{id}/status`, `POST /demand/signal`, out-of-band reefer telemetry, vendor condition) and *discovered* by the agent's own `observe`/`investigate` GETs.
2. **Nothing is hardcoded.** Candidate options, quantities, ETAs, and costs are discovered or computed from live sandbox data at runtime. Editing `seed_data.json` demonstrably changes the option set; there are no constants to delete because there are none.
3. **Every write is checked by a read.** `verify_node` re-reads the exact record it mutated (Read-After-Write) before claiming success. Tamper tests revert sandbox state behind the agent's back and prove it gets caught.
4. **Every failure is survivable.** Sandbox errors degrade to audit + replan or human escalation — never a crash, never a fabricated success.

## Slide 3 — Architecture

```
observe → detect → investigate → optimize → governance → execute → verify
    ^          |         ^                          |            |
    |          |         └─────── replan loops ─────┴────────────┘
    └── stage re-entry (vendor stock-out re-observes the world)
```

Two processes, both real HTTP:

| Component | Stack | Role |
|---|---|---|
| **Sandbox** (`sandbox_api.py`) | FastAPI, port 8000 (env `SANDBOX_PORT`) | The simulated logistics environment — the world |
| **Agent** (`agent_graph.py`) | LangGraph state machine, httpx | The autonomous decision-maker — the brain |
| **Dashboard** (`dashboard-react/`) | React 19 + Vite + styled-components | Live control room, streaming over SSE |
| **Checkpoint store** | SQLite via LangGraph `SqliteSaver` | `agent_state.db` — genuine mid-graph resume |

## Slide 4 — The Sandbox: a world that keeps state

FastAPI app under `/api/v1`. Read endpoints: `/inventory`, `/inventory/{id}`, `/shipments/{id}`, `/transfers/{id}`, `/orders/{id}`, `/allocations/{id}`, `/vendors`, `/routes`, `/demand/{id}`, `/tools/cost-carbon`, `/health`, `/state`.

State-changing endpoints (all **idempotent** via `x-idempotency-key`):
- `POST /orders/purchase` — buy from a vendor
- `POST /transfers/dispatch` — move stock between facilities
- `POST /shipments/reroute` — reroute an in-flight shipment
- `POST /allocations/reserve` — reserve on-hand stock

Environment-mutation endpoints the *world* uses (never the agent): `POST /shipments/{id}/status`, `POST /telemetry/reefer/{id}`, `POST /vendors/{id}/condition`, `POST /demand/signal`. Plus `POST /reset`, `POST /environment/apply`, `GET /stream-scenario` (SSE), `GET /history`.

Persistence: JSON snapshot (`sandbox_snapshot.json`, `run_history.json`) with atomic write-through on every mutation; corrupt snapshots fall back to seed; `SANDBOX_PERSIST=0` for in-memory (CI uses this).

## Slide 5 — The Agent: seven nodes, two replan loops

`agent_graph.py` is a LangGraph `StateGraph` whose nodes map 1:1 to the seven PS bullets. All I/O goes through `_get`/`_post` wrappers that return `None` on any failure — callers branch on `None` and escalate/replan instead of crashing.

1. **observe_node** — real GETs: `/inventory/{facility}`, `/shipments/{id}` (refreshed *every* tick so replans never read stale status), `/demand/{facility}`; syncs the digital twin. If the sandbox is unreachable it reports `SANDBOX_UNREACHABLE` rather than inventing a healthy world.
2. **detect_node** — reads shipment status from the digital twin's snapshot (making the twin load-bearing), then flags: `SAFETY_STOCK_BREACH` (stock < floor), `SHIPMENT_CUSTOMS_HOLD / COMPROMISED / DELAYED`, `DEMAND_SURGE` (surge_ratio > 1.3).
3. **investigate_node** — GETs every vendor, lane, and facility inventory; prices one live lane through `POST /tools/cost-carbon` as a tool-verification audit line; computes `required_kg`; delegates to `candidates.build_candidates`. Logs *why* vendors are absent: `VEND-TAIPEI:STOCK_OUT`, `VEND-…:UNCERTIFIED`.
4. **optimize_node** — feasibility filter first, then weighted score; builds the full decision table for the UI including *why* each infeasible option was dropped.
5. **governance_node** — bounded-autonomy veto; a rejected plan is invalidated and the loop tries the next-best option.
6. **execute_node** — one real idempotent POST per action type; a mid-action sandbox blip is reported honestly as `SANDBOX_UNREACHABLE`, never faked.
7. **verify_node** — RAW re-GET of inventory + the exact mutated record (order status + vendor match / transfer temp / shipment status / reservation quantity), a cold-chain envelope check (2–8 °C), and a **recovery gate**: a stock disruption is only "recovered" when real stock clears the floor — this is what stops a reroute (which adds no stock) from being reported as a fix for a stock breach.

Conditional edges: `route_detection` (no disruption → END; sandbox-unreachable → escalate), `route_governance` and `route_verification` (fail → invalidate option → back to `investigate`; replans exhausted → END, human-on-the-loop). The vendor stock-out scenario re-enters at `observe` on the same thread — the agent re-observes and *discovers* the vendor is gone.

## Slide 6 — Discovery & pricing: candidates.py (pure, unit-tested)

No option list exists anywhere in the repo. Everything is computed:

- **Required quantity** = `max(0, safety − current)` (the real deficit) `+ safety × max(0, surge − 1) × 0.5` (demand headroom).
- **Lane quote** (deterministic physics): `transit = distance / avg_speed` (+2 h cold-chain handling for REEFER_TRUCK / AIR_CARGO); `cost = qty × distance × cost_per_km_per_kg`; `carbon = qty × distance × co2_per_km_per_kg`.
- **PURCHASE** — for each vendor with enough live stock, over the cheapest lane from its city; landed unit cost = vendor price + freight per kg. Vendor lead time adds to transit.
- **TRANSFER** — from every other facility whose actual surplus covers the deficit.
- **REROUTE** — every alternative lane for the in-flight shipment, ETA computed from `now`, priced against the shipment's own quantity.
- **ALLOCATE** — reserve own stock (valid precisely when there IS stock and demand surged).

The "resolves" filter admits only action types that structurally fix the detected disruption — a reroute can't add stock, so it's excluded for a stock breach. The uncertified vendor **passes through discovery** so the optimizer's filter visibly rejects it (investigated, then rejected — shown in the UI).

## Slide 7 — Optimizer + Governance: bounded autonomy

**Optimizer** (`optimizer.py`): hard bounds applied *before* scoring — transit ≤ 16 h, CDSCO certification required. Survivors scored by min-max-normalized weighted sum: **score = 0.5·cost + 0.3·time + 0.2·carbon** (lower is better). The full table, including rejected options and their reasons, goes to the dashboard.

**Governance** (`governance.py`): the agent may only act autonomously inside bounds —
1. compliance veto (never commit to a non-CDSCO-certified source),
2. quantity ceiling (10,000 kg),
3. spend ceiling (₹1.5 Cr committed value).

A veto invalidates the option and loops to the next-best; exhausted options escalate to a human (`MAX_REPLANS = 3`). Autonomy is real but *bounded* — the key safety story for judges.

## Slide 8 — The digital twin

`digital_twin.py` is an in-memory, merge-based mirror of observed telemetry, kept separate from the authoritative sandbox. `observe` syncs it; `detect` reads shipment status from its snapshot — so it is load-bearing, not decoration. Separating "what the world says" from "what I last saw" is the seam where drift detection would live next.

## Slide 9 — The dashboard: watching the agent think

React 19 + Vite + styled-components, light theme, no CSS files. `useScenarioStream` consumes `GET /stream-scenario` (SSE) — one frame per node:

- **Pipeline diagram** — seven nodes light up one-by-one as the agent runs.
- **KPI row** — recovery status, replan cycles, stock vs safety floor, selected action.
- **Monitor tab** — facility stock bars, cold-chain temp, shipment status, in-transit reefer temp, disruption alert, **vendor cards with live condition badges** (CERTIFIED / UNCERTIFIED / STOCK OUT) and the demand-surge ratio — rendered from the same snapshot the agent reads.
- **Options tab** — the real decision table: per-option cost breakdown (vendor + freight + handling = landed unit cost), computed-deficit banner, winner highlighted, infeasible options struck through, governance verdict, execution result.
- **Trail tab** — every step as color-coded cards grouped by disruption stage, streaming live.
- **History tab** — every completed run with outcome and selected plan.

## Slide 10 — Proof: tests & CI

**39 tests, all green** (`pytest -v`; integration needs the sandbox up):

- `tests/test_candidates.py` — 14 unit tests: deficit math, deterministic pricing, live-data filters, uncertified passthrough.
- `tests/test_agent.py` — 8 unit (optimizer/governance) + 17 integration driving the **real agent against the live sandbox**: all four action types, both replan loops, environment-as-source-of-truth (editing seed data changes options), sandbox-down escalation, vendor condition changes, `/environment/apply`, per-action RAW re-GETs, and **tamper tests** that revert state behind the agent's back.

CI (`.github/workflows/ci.yml`): unit job (no sandbox) + integration job (boots ephemeral sandbox, `SANDBOX_PERSIST=0`) + dashboard production build.

## Slide 11 — How it works: one full run (the story)

1. **Inject** — `CUSTOMS_HOLD` set on shipment `IMP-JNPT-8802` via the environment; the agent knows nothing.
2. **Observe** — real GETs of inventory, shipment, demand; twin synced.
3. **Detect** — stock below floor → `SAFETY_STOCK_BREACH`; shipment in hold → `SHIPMENT_CUSTOMS_HOLD`.
4. **Investigate** — live vendors/lanes/inventories fetched; required kg computed from the actual deficit; candidates built and priced; reroute excluded (can't add stock); `VEND-…:UNCERTIFIED` logged.
5. **Optimize** — filter → score → cold-chain transfer wins.
6. **Govern** — within spend/qty/compliance bounds → approved.
7. **Execute** — real `POST /transfers/dispatch` with an idempotency key; stock moves above the floor.
8. **Verify** — RAW re-GET: stock ≥ floor, temp within 2–8 °C, transfer record holds → **RECOVERED**.
9. **Stage 2 (the money shot)** — out-of-band reefer telemetry (+14 °C, like an IoT webhook). Nobody tells the agent. Its own verify check discovers the excursion, invalidates the option, and replans: investigate → optimize → govern → execute → verify → **RECOVERED, replans: 1**.
10. **Variant** — vendor stock-out + 1.8× surge injected out-of-band; the graph re-enters at observe; the agent's own GET finds `VEND-TAIPEI` at 0 kg and steers to a feasible option. The stock-out vendor never appears as an option — excluded by *live data*.

## Slide 12 — Zero API key, zero LLM — on purpose

This is an agent, and it runs **without any LLM and without any API key**. That is a design decision, not a missing feature:

- **Agency lives in the loop, not in a language model**: perceive → decide → act → verify → replan, with self-initiated re-observation when the world changes. The problem statement rewards the *closed loop*, not conversation.
- **Deterministic = testable = provable**: same inputs always produce the same plan, which is exactly what the 39-test suite locks in. You cannot unit-test a prompt's judgment.
- **No hallucinated actions on physical goods**: a hallucination here misroutes cold-chain medicine. Rules don't improvise; governance bounds stay hard bounds.
- **Zero marginal cost and zero latency per decision**: no per-call LLM spend, no rate limits, no provider outage in the critical path — it recovers at machine speed, forever, for free.
- **Runs air-gapped**: no data egress to a third-party model — a real requirement in pharma and regulated supply chains.
- **The seam is ready**: an LLM could slot in later as a policy/explanation layer inside `investigate`/`optimize` (e.g., natural-language incident summaries) without touching the safety contract. LangGraph is the same orchestration framework LLM agents use — swap the policy, keep the contract.

**Judge framing:** "We didn't avoid an LLM because we couldn't wire one — we avoided it because in this domain the decision policy must be auditable, reproducible, and free to run at high frequency. That's why there's no API key anywhere in this repo."

## Slide 13 — Honest limits (state them first, don't wait to be asked)

- The environment is a simulation — that's what the PS asks for. But all agent ↔ environment interaction is real HTTP with real state mutation and RAW reads.
- The agent's reasoning is deterministic rules — a deliberate reliability choice (see Slide 12). "Autonomous" here means the closed loop, not a chatbot.
- Sandbox persistence is a JSON snapshot, not a transactional DB — right-sized for the demo.

## Slide 14 — Close

> "Real monitoring of inventory, shipments, demand and vendor conditions; detection driven entirely by the environment; discovery-driven options priced by a real calculator; real state-changing execution; read-after-write verification; and autonomous replanning on disruptions it was never told about — every bullet of Problem Statement 6, proven live and by 39 automated tests."

**Tech stack in one breath:** Python, LangGraph + SQLite checkpointing, FastAPI sandbox with idempotent endpoints, httpx, React 19 + Vite + styled-components over SSE, pytest, GitHub Actions CI — **no LLM, no API key, nothing to pay per decision**.

---

## Judge Q&A (rapid fire)

- **"Is the optimization real or hardcoded?"** — Two layers: discovery from live `GET /vendors` + `GET /routes` priced by the cost-carbon math, then hard feasibility bounds + a normalized 0.5/0.3/0.2 cost/time/carbon score. The Options tab shows every candidate's breakdown; the deficit banner shows the computed requirement.
- **"What makes it autonomous vs a prompt chain?"** — Every disruption is an out-of-band environment event; the agent re-observes and decides to replan. The vendor stock-out is the strongest proof: its own GET discovers the vendor is gone — no rule names that vendor. Governance, not a human, gates each action.
- **"What if the chosen option fails?"** — It's invalidated and the next-best feasible option is tried; exhausted options escalate to a human (`MAX_REPLANS`).
- **"Why pharma / cold-chain?"** — Domain realism on a generic engine; the 2–8 °C envelope is what makes the reefer excursion a meaningful second disruption. The seven-stage loop is domain-agnostic.
- **"Where's the LLM? / Is it an agent without one?"** — Agency is the perceive-decide-act-verify-replan loop with self-initiated re-observation, not the language model. The policy is deterministic on purpose: auditable, reproducible, unit-testable, zero marginal cost per decision, no API key, runs air-gapped. LangGraph is the same framework LLM agents use — an LLM can slot into `investigate`/`optimize` later without touching the safety contract.
- **"How would this scale to production?"** — The sandbox interface is the contract: swap FastAPI for real WMS/TMS APIs, keep the idempotency keys and read-after-write discipline; the graph, governance bounds, and audit trail carry over unchanged.
