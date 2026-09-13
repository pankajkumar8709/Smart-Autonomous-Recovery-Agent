# Manual Test Plan — verify against Problem Statement 6

Each section maps to a PS-6 requirement. Do the ACTION, check the EXPECTED result.
If every EXPECTED holds, the application satisfies the problem statement.

## Setup (fresh state every time)

```powershell
# Terminal 1 — sandbox
cd TechRebels_Github_agentic
.\.venv\Scripts\Activate.ps1
# Use port 8001 everywhere if 8000 is occupied (set SANDBOX_PORT for both processes)
# NOTE (Phase 7): state now PERSISTS across restarts (sandbox_snapshot.json).
# For a fresh environment use the dashboard's "Reset environment first", or
# POST /api/v1/reset, or run with SANDBOX_PERSIST=0 for restart-clears-state.
uvicorn sandbox_api:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend
cd dashboard-react
npm run dev
```

Open http://localhost:5173 . Top bar should show **sandbox online** (green dot).
Sanity: browse http://127.0.0.1:8000/api/v1/health → `{"status":"ok",...}`.
All endpoint URLs below assume :8000 — substitute :8001 if you ran the sandbox there.
Port note (Windows): if :8000 is wedged by a stale process (health answers but
requests hang), run EVERYTHING on 8001: `SANDBOX_PORT=8001` for the sandbox and
the Vite proxy picks it up automatically.

---

## PS bullet 1 — Monitor inventory AND shipment state (+ demand, + vendors)

**Action:** Open the **Monitor** tab (default).
**Expected:**
- Inventory monitor lists facilities with a stock bar and a cold-chain temp badge.
- Shipment monitor shows `IMP-JNPT-8802` with a status badge.
- **Phase 5:** a **Vendors** card (both vendors with CDSCO ✓/uncertified badges,
  live stock levels, unit cost, lead time) and a **Demand signal** card (or the
  honest "no signal recorded — baseline" empty state).
- These are REAL reads: hit http://127.0.0.1:8000/api/v1/state in a browser and
  confirm the same numbers appear. (The UI is showing sandbox truth, not mock data.)

## PS bullet 2 — Detect a disruption / constraint violation

**Action:** Control panel → Shipment status **CUSTOMS_HOLD**, surge **1.0×** → **Run recovery**.
**Expected:**
- An amber alert appears: `Disruption detected — SAFETY_STOCK_BREACH` (and/or
  `SHIPMENT_CUSTOMS_HOLD`).
- The Detect node in the pipeline lights up. The **Trail** tab shows
  `DetectNode: ALERT - ...`.
- Control test (two ways to run it):
  - **Apply environment (no run)** with status **IN_TRANSIT** and surge **1.0×** on
    healthy stock → the Monitor tab shows the flipped environment and the top bar
    still says **no active run**. Then **Run recovery** → detect finds NO disruption
    and the run ends without acting. (Proves detection follows the environment, and
    that setup and action are separate concerns.)
  - Or directly: status **IN_TRANSIT**, surge **1.0×**, reset to `shipment_only` on a
    fresh sandbox → same no-disruption outcome.

## PS bullet 3 — Investigate alternative vendors / routes / allocations

**Action:** Open the **Options** tab after a run.
**Expected:**
- A table of candidate options across action types (PURCHASE / TRANSFER / REROUTE /
  ALLOCATE depending on the disruption).
- **Phase 2:** the option ids are built from live sandbox data — e.g.
  `PURCHASE-VEND-TAIPEI-LANE-TPE-HYD-AIR`, `TRANSFER-FAC-VIZAG-COLD-LANE-VZG-HYD-REEFER`,
  `REROUTE-IMP-JNPT-8802-<lane>`, `ALLOCATE-FAC-HYD-GENOME-existing` — with prices
  derived from the cost-carbon calculator (vendor unit cost + freight over lane physics).
  Editing `seed_data.json` (vendor stock, lane speed, a new vendor) changes this table.
  (N.B. the sandbox holds seed data in memory — restart it after editing the file.)
- The uncertified vendor (`PURCHASE-VEND-LOCAL-...`) is shown **infeasible / struck
  through** — it was investigated then rejected by the feasibility filter, not silently ignored.

## PS bullet 4 — Optimize under cost / delivery / carbon

**Action:** Still on the **Options** tab.
**Expected:**
- A green **COMPUTED DEFICIT** banner shows the required kg computed from live
  state (`max(0, safety − current) + surge buffer`) — not a constant 5,000.
- Each feasible option shows its **landed-cost breakdown**: `₹<total> = ₹<vendor> +
  ₹<freight> (<distance> km) + ₹<handling>` — every number traceable to the
  cost-carbon calculator and seed data.
- Each feasible option shows a numeric **score**; the selected one is highlighted.
- The winner is the best trade-off (lowest score). Options over the transit-time
  bound or not CDSCO-certified are marked infeasible with no score.
- Cross-check the KPI row: **Selected action** matches the highlighted winner.

## PS bullet 5 — Execute a REAL rerouting / purchase / allocation / transfer

**Action:** Watch the Execute node; then read sandbox state back.
**Expected:**
- Trail shows `ExecuteNode: <TYPE> dispatched ... sandbox_status=<DISPATCHED/ORDERED/REROUTED/RESERVED>`.
- The sandbox state actually changed. For a TRANSFER/PURCHASE, GET
  http://127.0.0.1:8000/api/v1/inventory/FAC-HYD-GENOME → `current_stock_kg` has RISEN
  above the pre-run value. This is the key anti-"fake chain" check.
- To prove all four action types execute, run these on a freshly restarted sandbox:
  - **Stock breach** (default): CUSTOMS_HOLD, surge 1.0 → selects PURCHASE or TRANSFER.
  - **Pure shipment**: first `POST /api/v1/reset {"scenario":"shipment_only"}`, then
    run with CUSTOMS_HOLD → REROUTE becomes selectable.
  - **Demand surge**: `POST /api/v1/reset {"scenario":"demand_surge"}`, then run with
    surge ≥ 1.4 → ALLOCATE becomes selectable.

## PS bullet 6 — Verify the resulting inventory and delivery state

**Action:** Watch the Verify node / read the Trail.
**Expected:**
- Trail shows `VerifyNode: SUCCESS - RAW check: stock=<N>kg (safety=<M>kg, ok=True), cold-chain ok=True, record check: ...` — the record check names the mutated record the agent re-GET (order / transfer / shipment / reservation, per action type).
- The stock number in the SUCCESS line equals what GET `/inventory/...` returns — the
  agent verified by reading real state (Read-After-Write), not by trusting its own plan.
- Result banner shows **RECOVERED**.
- **Tamper check (Phase 3, optional):** after a REROUTE recovery, revert the shipment
  with `POST /api/v1/shipments/IMP-JNPT-8802/status {"status":"CUSTOMS_HOLD"}` — a
  subsequent verify against the recorded result reports
  `record check failed` and triggers replan (locked in by automated tests:
  `test_tampered_shipment_revert_caught_by_verify`, `test_vanished_allocation_caught_by_verify`).

## PS bullet 7 — Replan when an alternative fails / a new disruption occurs

**Action:** Run with **"Inject reefer excursion after Stage 1" CHECKED**.
**Expected:**
- Stage 1 recovers via TRANSFER (has a reefer leg).
- A telemetry event reports the transfer at +14°C (out-of-band, not fed to the agent).
- Verify RE-RUNS, reports `FAILURE - cold_chain_ok=False ... Triggering replan`.
- Pipeline loops back through Investigate → Optimize → Govern → Execute → Verify.
- The failed option (the Stage-1 transfer, e.g. `TRANSFER-FAC-VIZAG-COLD-LANE-VZG-HYD-REEFER`)
  is excluded; a new option is chosen and succeeds. Result: **RECOVERED**, **Replan cycles = 1**.
- This is the autonomy proof: the agent was never told the plan failed — it found out
  by re-reading state.

## PS intro — vendor conditions change (Phase 4)

**Action:** Run with **"Vendor stock-out after Stage 1" CHECKED** (vendor `VEND-TAIPEI`),
"Inject reefer excursion" UNCHECKED, reset to `stock_breach`.
**Expected:**
- Stage 1 recovers as usual.
- An out-of-band event fires: `Vendor condition change: VEND-TAIPEI STOCK_OUT` — plus a
  fresh 1.8× demand surge. The agent is told NEITHER.
- The graph re-enters at Observe on the same thread; the Trail shows the
  re-investigation discovering the world again, with the audit line naming
  `vendor conditions: VEND-TAIPEI:STOCK_OUT, VEND-LOCAL:UNCERTIFIED`.
- **No `PURCHASE-VEND-TAIPEI-...` candidate appears** after the stock-out (it was
  excluded by live data, not by a rule); the agent recovers via the remaining
  feasible option. Cross-check: GET http://127.0.0.1:8001/api/v1/vendors/VEND-TAIPEI
  → `stock_available_kg: 0`.
- Result: **RECOVERED** — three genuine disruptions, all originating in the environment.

## Bonus — governance veto (bounded autonomy)

**Action:** In `config.py` set `MAX_AUTONOMOUS_SPEND_INR = 1_000_000`, restart sandbox,
run a stock-breach scenario where the only feasible option costs more.
**Expected:** Trail shows `GovernanceNode: REJECTED - SPEND_LIMIT ...`; the agent tries
the next option or escalates instead of over-committing.

---

## Automated backstop

```powershell
python -m pytest -v      # sandbox must be running (set SANDBOX_PORT if not on :8000)
```
**Expected: 39 passed** — 22 unit (8 optimizer/governance + 14 pure discovery
engine) + 17 integration driving the real agent against the sandbox: all four
action types, the replan loops, environment-as-source-of-truth, sandbox-down
escalation, vendor stock-out/certification discovery, `/environment/apply`, and
the Phase 3 tamper tests (reverted shipment / vanished allocation caught by RAW
re-GET).

## Pass criteria
The application satisfies PS-6 if: all 7 bullets above show their EXPECTED result,
the stock number genuinely changes in the sandbox after execution, the reefer replan
loop fires on its own, the vendor stock-out is discovered (never told), a tampered
record is caught by verification, and `pytest -v` is 39/39 green.
