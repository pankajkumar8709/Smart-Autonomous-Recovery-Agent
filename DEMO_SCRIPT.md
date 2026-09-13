# Demo Script — Autonomous Retail Supply Chain Recovery Agent (PS-6)

**Total time: ~6 minutes.** Goal: prove the agent *acts* on a live system and
*recovers from disruptions it was never told about* — not a scripted prompt chain.

---

## 0. Pre-demo setup (do this BEFORE judges are watching)

```powershell
# Terminal 1 — sandbox (restart fresh so no stale state shows)
cd TechRebels_Github_agentic
.\.venv\Scripts\Activate.ps1
uvicorn sandbox_api:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend
cd dashboard-react
npm run dev        # http://localhost:5173
```

Open `http://localhost:5173` in the browser. Leave it on the **Monitor** tab.
Have a second browser tab on `http://127.0.0.1:8000/docs` (FastAPI Swagger) ready
as backup proof the endpoints are real.

**One-liner you can say while it loads:** "This is an autonomous agent that keeps
a pharma cold-chain supply network at its service level when things break —
customs holds, stock-outs, demand spikes, even a refrigeration failure in transit."

---

## 1. Frame the problem (30 sec)

> "Problem Statement 6 asks for an agent that monitors inventory and shipments,
> detects disruptions, investigates alternatives, optimizes under cost / delivery /
> carbon constraints, executes a *real* action, verifies the result, and replans
> when something else breaks. The rules specifically warn against fixed prompt
> chains that fake success — so everything you'll see hits a live sandbox and reads
> real state back."

Point at the **pipeline diagram**: "These seven stages are a LangGraph state
machine. Watch them light up as the agent runs."

---

## 2. The headline run — double disruption (2 min)

On the control panel (left):
- Facility `FAC-HYD-GENOME`, Shipment `IMP-JNPT-8802`
- Shipment status **CUSTOMS_HOLD**
- **Leave "Inject reefer excursion after Stage 1" checked** ← this is the money shot
- Click **Run recovery**

**Narrate as the pipeline animates (it streams over SSE, node by node):**

1. **Observe** — "It's pulling real inventory and shipment state from the sandbox."
2. **Detect** — "Safety-stock breach detected — stock is below the floor."
3. **Investigate** — "It's pulling the vendor list, transport lanes, and every
   facility's stock from the sandbox right now, pricing each option with its
   cost-carbon calculator, and computing the required quantity from the actual
   deficit. It only considers actions that can fix a stock breach — a reroute
   can't add stock, so it's excluded."
4. **Optimize** — "It scores the feasible options on cost, delivery time, and
   carbon, and picks the cold-chain transfer."
5. **Govern** — "A governance layer checks spend and compliance limits before it's
   allowed to act autonomously — approved, within bounds."
6. **Execute** — "This is a *real* state-changing call to the sandbox — stock moves
   from 1,200 up over the safety floor."
7. **Verify** — "It reads the state back — Read-After-Write — and confirms genuine
   recovery, not a claimed one."

Then, without you touching anything:

> "Now a **second, independent disruption** — the refrigerated truck's telemetry
> reports a temperature excursion, +14°C. This isn't scripted into the agent; it's
> an out-of-band event, like a real IoT sensor webhook. Watch — **the agent
> discovers it on its own next verify check**, invalidates the failed option, and
> replans."

Pipeline loops back: Investigate → Optimize → Govern → Execute → Verify. Ends
**RECOVERED**, replan count **1**.

> "That closed loop — detect, act, verify, and *re-plan on a new disruption it was
> never told about* — is the core ask of the problem statement, and it's fully
> autonomous."

---

## 3. Show it's real, not a mock (1 min)

Switch tabs to make the point concrete:

- **Options tab** — "Here's the actual decision table the optimizer built — every
  candidate with its cost, transit time, carbon, and compliance flag. The winner is
  highlighted; the grey-market uncertified vendor was dropped by the compliance
  filter, not by luck."
- **Trail tab** — "Every step is audit-logged with the real sandbox status codes."
- (Backup) **Swagger `/docs`** — "These are the real state-changing endpoints:
  purchase, transfer, reroute, allocate — the agent calls these over HTTP."

---

## 4. Prove robustness — the tests (45 sec)

```powershell
# Terminal 2 (stop the frontend or use a third terminal)
python -m pytest -v      # sandbox must be running (set SANDBOX_PORT if not on :8000)
```

> "39 automated tests, all green. Seventeen drive the *real* agent against the live
> sandbox: all four action types, both replan loops, environment-as-source-of-truth,
> sandbox-down escalation, vendor condition changes, and tamper tests that revert
> sandbox state behind the agent's back and prove its read-after-write check catches
> it — so this behavior is locked in, not a one-time lucky run."

---

## 5. The autonomy capstone — vendor stock-out (1 min)

On the control panel:
- **UNCHECK** "Inject reefer excursion"
- **CHECK** "Vendor stock-out after Stage 1" (vendor `VEND-TAIPEI`)
- Keep "Reset environment first" checked → **Run recovery**

Narrate while Stage 1 recovers, then the stage 3 banner fires:

> "Now something no one told the agent about: our certified supplier just sold
> out — an out-of-band condition change, plus a fresh demand spike. Watch the
> re-investigation: it re-reads the vendor list and the audit line says
> `VEND-TAIPEI:STOCK_OUT`. The stock-out vendor simply never appears as an
> option — it was excluded by *live data*, not by a hardcoded rule — and the
> agent recovers with what's actually feasible."

Ends **RECOVERED**. Then, on the **Monitor** tab:

> "And here's the vendor card showing the stock-out — the dashboard shows what
> the agent sees, because it's the same GET."

## 6. Close (15 sec)

> "So: real monitoring of inventory, shipments, demand and vendor conditions;
> detection driven entirely by the environment; discovery-driven options priced by
> a real calculator; real state-changing execution; read-after-write verification;
> and autonomous replanning on disruptions it was never told about — every bullet
> of Problem Statement 6, proven live and by automated tests."

---

## Backup answers for likely judge questions

- **"Is the optimization real or hardcoded?"** — Two layers: discovery (candidates
  built from live `GET /vendors` + `GET /routes`, priced by the deterministic
  cost-carbon calculator, quantities computed from the actual deficit) then a
  feasibility filter (hard bounds on transit time + CDSCO compliance) and a weighted
  score over cost / time / carbon. Show the Options tab: every option carries its
  cost breakdown and the deficit banner shows the computed requirement.
- **"What makes it *autonomous* vs a prompt chain?"** — Every disruption is an
  out-of-band environment event; the agent re-observes real sandbox state and
  decides to replan. The vendor stock-out is the strongest proof: the agent's own
  GET discovers the vendor is gone — no rule names that vendor. And a governance
  layer, not a human, gates each action against spend/compliance limits.
- **"What if the chosen option also fails?"** — It invalidates that option and
  tries the next-best feasible one; after exhausting options it escalates
  (human-on-the-loop) instead of looping forever. That's the replan cap.
- **"Why pharma / cold-chain?"** — Domain realism layered on a generic engine; the
  seven-stage loop is domain-agnostic. The cold-chain temperature envelope is what
  makes the reefer excursion a meaningful second disruption.
- **"What's simulated vs real?"** — The environment is a simulation (that's the
  assignment); all agent–environment interaction is real HTTP with real state
  mutation and read-after-write verification. The agent's reasoning is
  deterministic rules, deliberately, for reliability.
- **"Tech stack?"** — LangGraph state machine + SQLite checkpointing (real mid-graph
  resume), FastAPI sandbox with idempotent state-changing endpoints, React 19 +
  styled-components dashboard streaming over SSE.

## Demo hygiene
- **State persists across restarts now (Phase 7):** the Monitor may show state
  from a previous demo. For a fresh environment either check "Reset environment
  first" on the first run, `POST /api/v1/reset`, or start the sandbox with
  `SANDBOX_PERSIST=0` for classic restart-clears-state behavior.
- If a run shows a stray red reefer temp from a prior run, that's stale display
  state — a reset clears it.
- **Port note:** if :8000 is occupied/wedged, run everything on 8001:
  `SANDBOX_PORT=8001 uvicorn sandbox_api:app --port 8001` — the Vite proxy and
  the test suite follow the same env var. The agent inside the sandbox process
  inherits the port, so one env var keeps the whole stack consistent.
