# Demo Video Script — Autonomous Retail Supply Chain Recovery Agent (PS-6)

**Total runtime target: ~5:30.** Format: screen recording with voiceover. Goal:
prove the agent *acts* on a live system and *recovers from disruptions it was
never told about* — not a scripted prompt chain.

---

## Before recording (checklist)

- [ ] Terminal 1 — sandbox fresh: `uvicorn sandbox_api:app --host 127.0.0.1 --port 8000`
      (if :8000 is wedged, run everything on `SANDBOX_PORT=8001` — sandbox, Vite proxy, and tests all honor it)
- [ ] Terminal 2 — `cd dashboard-react && npm run dev` → http://localhost:5173
- [ ] Browser tab 1: dashboard on the **Monitor** tab, full-screen, 100% zoom
- [ ] Browser tab 2 (backup proof): `http://127.0.0.1:8000/docs` (Swagger)
- [ ] Terminal 3 staged for `python -m pytest -v` and `python scenarios.py`
- [ ] Microphone level checked; close Slack/Teams notifications
- [ ] On the control panel: Facility `FAC-HYD-GENOME`, Shipment `IMP-JNPT-8802`,
      status `CUSTOMS_HOLD`
- If state persists from a prior take: keep **"Reset environment first"** checked for the first run.

---

## Scene 1 — Title & hook (0:00–0:25)

**On screen:** dashboard loading, then the Monitor tab. Optional title card:
*"Autonomous Retail Supply Chain Recovery Agent — Problem Statement 6"*.

**Voiceover:**
> "Supply chains break: a customs hold traps a shipment, demand spikes, a vendor
> sells out, a refrigerated truck fails in transit. This is an autonomous agent
> that keeps a pharma cold-chain network at its service level when things break —
> and it proves every recovery with real reads from a live environment, not claims."

**Action:** none — let the Monitor tab breathe on screen for a beat.

---

## Scene 2 — Frame the problem & architecture (0:25–1:00)

**On screen:** the pipeline diagram under the KPI row (observe → detect →
investigate → optimize → govern → execute → verify). Then a 5-second flash of
the repo file tree (`agent_graph.py`, `sandbox_api.py`, `candidates.py`,
`optimizer.py`, `governance.py`).

**Voiceover:**
> "Problem Statement 6 asks for seven things: monitor inventory and shipments,
> detect disruptions, investigate alternatives, optimize under cost, delivery and
> carbon constraints, execute a real action, verify the outcome, and replan when
> something else breaks. These seven stages are a LangGraph state machine — each
> node maps to one requirement. On the right, a FastAPI sandbox is the simulated
> logistics world; every arrow between agent and world is real HTTP."

---

## Scene 3 — Set the trap (1:00–1:30)

**On screen:** the Control Panel. Type Facility `FAC-HYD-GENOME`, Shipment
`IMP-JNPT-8802`, pick status **CUSTOMS_HOLD**. Pause visibly on the checkbox
**"Inject reefer excursion after Stage 1"** — leave it CHECKED.

**Voiceover:**
> "First I break the world. A customs hold on the inbound shipment — set through
> the environment, exactly how reality would do it. The agent knows nothing yet.
> And — this is the important part — I'm arming a second, independent disruption:
> a refrigeration failure that will fire mid-recovery. The agent will have to
> discover it on its own."

**Action:** click **Run recovery**.

---

## Scene 4 — Stage 1: the recovery, narrated node by node (1:30–3:00)

**On screen:** pipeline nodes lighting up one-by-one over SSE; KPI row updating;
Trail tab streaming cards. Cut to the Options tab at the optimize beat.

**Voiceover — time each line to its node lighting up:**

- **Observe:** "It's pulling real inventory, shipment and demand state from the sandbox over HTTP."
- **Detect:** "Detected: safety-stock breach — stock is below the floor — plus the customs hold."
- **Investigate:** "Now it investigates: live vendor list, transport lanes, every facility's stock — priced by the cost-carbon calculator, with the required quantity computed from the actual deficit. A reroute can't add stock, so it's excluded. The uncertified grey-market vendor is investigated, then dropped by the compliance filter — not by luck."
- **Optimize:** "Feasible options are scored on cost, time and carbon — the cold-chain transfer wins."
- **Govern:** "A governance layer checks spend, quantity and compliance limits before the agent is allowed to act autonomously. Approved."
- **Execute:** "This is a real state-changing call — dispatch the transfer. Watch the stock."
- **Verify:** "And now the proof: it reads the state back — read-after-write — stock is above the floor, temperature inside the 2-to-8-degree envelope. Recovery confirmed, not claimed."

**On screen cut:** Options tab for 4–5 seconds during the Optimize/Govern lines —
show the decision table with per-option cost breakdown, winner highlighted,
infeasible options struck through. Then back to the pipeline for Execute/Verify.

---

## Scene 5 — Stage 2: the disruption nobody announced (3:00–3:50)

**On screen:** the stage-2 banner fires on its own; the pipeline loops back to
Investigate; replan counter ticks to 1.

**Voiceover:**
> "Now — without me touching anything — the refrigerated truck's telemetry reports
> a temperature excursion: plus fourteen degrees. This wasn't scripted into the
> agent; it's an out-of-band event, exactly like a real IoT webhook. Watch the
> verify step: the agent discovers the excursion itself, invalidates the failed
> option, and replans — investigate, optimize, govern, execute, verify — recovery
> confirmed, one replan. That closed loop — detect, act, verify, re-plan on a
> disruption it was never told about — is the core of Problem Statement 6."

**Action:** none. Do NOT touch the mouse — the autonomy is the point.

---

## Scene 6 — It's real: audit trail & raw endpoints (3:50–4:20)

**On screen:** Trail tab — scroll through color-coded event cards with real
sandbox status codes; then quickly switch to the Swagger tab (`/docs`), show the
four state-changing POSTs; then back.

**Voiceover:**
> "Every step is audit-logged with real sandbox status codes. And these are the
> real endpoints — purchase, transfer, reroute, allocate — each one idempotent,
> each one mutating state the agent then reads back. Nothing is faked in-process."

---

## Scene 7 — Locked in: the test suite (4:20–4:45)

**On screen:** Terminal: `python -m pytest -v` running; let the last ~39 green
lines scroll; stop on the summary line.

**Voiceover:**
> "Thirty-nine automated tests, all green. Seventeen drive the real agent against
> the live sandbox: all four action types, both replan loops, environment-as-source-
> of-truth, sandbox-down escalation, and tamper tests that revert state behind the
> agent's back and prove the read-after-write check catches it. This behavior is
> locked in — not a lucky run."

---

## Scene 8 — Capstone: vendor stock-out (4:45–5:15)

**On screen:** Control Panel — UNCHECK reefer, CHECK **"Vendor stock-out after
Stage 1"** (`VEND-TAIPEI`), keep **"Reset environment first"** checked → **Run
recovery**. When the stage-3 banner fires, cut to the Monitor tab vendor card
showing **STOCK OUT**.

**Voiceover:**
> "One more: our certified supplier sells out — an out-of-band condition change,
> plus a fresh demand spike. Nobody tells the agent. On re-entry it re-observes
> the world, and the audit line says `VEND-TAIPEI:STOCK_OUT`. The stock-out vendor
> never appears as an option — excluded by live data, not a hardcoded rule — and
> the agent recovers with what's actually feasible. And this vendor card on the
> Monitor is exactly what the agent sees — same GET."

---

## Scene 9 — Close (5:15–5:30)

**On screen:** back to the pipeline, final RECOVERED state; end card with repo
name + stack line.

**Voiceover:**
> "Real monitoring of inventory, shipments, demand and vendors; detection driven
> entirely by the environment; discovery-driven options priced by a real
> calculator; real state-changing execution; read-after-write verification; and
> autonomous replanning on disruptions it was never told about. Every bullet of
> Problem Statement 6 — proven live, and by tests. LangGraph, FastAPI, React —
> and not a single fake success. No LLM, no API key: agency lives in the loop,
> not in a prompt."

---

## Production notes

- **The "no LLM" talking point (expect this question in comments/Q&A):** "This is
  an agent without an LLM — on purpose. Agency is the perceive → decide → act →
  verify → replan loop with self-initiated re-observation; the policy is
  deterministic so it's auditable, reproducible, unit-testable, free to run at
  high frequency, and runs air-gapped. In pharma logistics you don't want a
  model improvising with cold-chain medicine. LangGraph is the same framework
  LLM agents use, so an LLM can slot in later as an explanation layer without
  touching the safety contract."

- **Pacing:** scenes 4 and 5 are the heart — let the pipeline animation play;
  don't rush the verify beat, it's the credibility moment.
- **Zoom cuts:** punch in (125–150%) on: detect alert banner, Options table cost
  breakdown, audit line `VEND-TAIPEI:STOCK_OUT`, pytest summary.
- **If a run fails on camera:** that's the product — say "watch the audit trail:
  it surfaced the failure and replanned" and cut to the Trail tab.
- **CLI fallback (if the dashboard misbehaves):** run `python scenarios.py`
  (double disruption) or `python scenarios.py vendor` (stock-out) in the terminal
  and narrate the printed audit trail; `python scenarios.py vendor` prints
  `OK: the stocked-out vendor was discovered and avoided.` — a clean closing line.
- **Two takes tip:** state persists across sandbox restarts; use "Reset
  environment first" or `POST /api/v1/reset` between takes.
- **Music/bed:** low, if any; duck under scenes 4–5.

## Alt cuts (if a shorter video is needed)

- **90-second cut:** Scenes 1, 3, 4 (compressed — one line per node), 5, 9.
- **60-second cut:** hook (Scene 1 shortened to two sentences), run Scene 3–5
  sped up 1.5× with only Detect / Execute / Verify / replan narrated, Scene 9.
