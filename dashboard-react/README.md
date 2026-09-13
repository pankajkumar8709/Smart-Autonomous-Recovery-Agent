# Supply Chain Recovery — Production Dashboard (React 19)

Vite + **React 19** + **styled-components**, fully light-themed. Production-grade,
tabbed, **live-streaming** control room for the autonomous recovery agent.

## What it shows (mapped to Problem Statement 6)

- **Live pipeline diagram** — the seven graph nodes (observe → detect → investigate
  → optimize → govern → execute → verify) light up **one-by-one via SSE** as the
  agent runs.
- **KPI row** — recovery status, replan cycles, destination stock vs safety, selected action.
- **Monitor tab** — facility stock bars vs safety stock, cold-chain temperature,
  shipment status, in-transit reefer temp, the detected-disruption alert — plus
  **vendors with live condition badges** (CDSCO certified/uncertified, stock level or
  STOCK OUT) and the **facility demand signal** (surge ratio vs baseline), both
  rendered from the sandbox snapshot, i.e. what the agent itself discovers.
- **Options tab** — the candidate comparison table with **per-option cost breakdown**
  (vendor + freight over lane distance + handling = landed unit cost), the computed
  deficit banner (required kg from live state, not a constant), winner highlighted,
  infeasible options struck through, the governance verdict, and the real execution
  result.
- **Trail tab** — every agent step as a color-coded card, grouped by disruption stage
  (0 = environment setup, 1 = primary, 2 = reefer, 3 = vendor condition), streaming live.
- **History tab** — every completed run with its outcome, params, and selected plan.

## Backend endpoints it uses

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/stream-scenario` | **SSE** — one frame per node; drives the live UI |
| `POST /api/v1/run-scenario` | non-streaming variant (batch) |
| `POST /api/v1/environment/apply` | set up environment (reset? + status + demand) **without running** |
| `GET /api/v1/state` | sandbox snapshot for the Monitor tab (inventory, shipments, transfers, vendors, lanes, demand) |
| `GET /api/v1/history` | past runs for the History tab |
| `GET /api/v1/health` | online indicator in the top bar |

## Run

```bash
cd dashboard-react
npm install
npm run dev        # http://localhost:5173
```

Start the sandbox first (from the project root) — Vite proxies `/api` to it. The
sandbox port follows `SANDBOX_PORT` (default 8000); set the same value for both
processes so the agent inside the sandbox points at itself:

```bash
uvicorn sandbox_api:app --host 127.0.0.1 --port 8000            # default
SANDBOX_PORT=8001 uvicorn sandbox_api:app --host 127.0.0.1 --port 8001   # alternate port
```

Phase 7: sandbox state persists across restarts (`sandbox_snapshot.json`). Use
the dashboard's "Reset environment first" checkbox or `POST /api/v1/reset` for
a fresh environment, or `SANDBOX_PERSIST=0` for classic in-memory behavior.

## Structure

```
src/
├── main.jsx                entry (createRoot + ThemeProvider + GlobalStyle)
├── theme.js                light-theme tokens (colors, per-node accents, spacing, shadows)
├── GlobalStyle.js          reset + body + keyframes
├── api.js                  runScenario() (batch)
├── useScenarioStream.js    SSE hook — accumulates events + live state + active node
├── App.jsx                 TopBar, KPI row, pipeline, tabs, layout
└── components/
    ├── styled.js           all shared primitives (Card, Tabs, Table, StatCard, Bar, badges…)
    ├── ControlPanel.jsx    disruption trigger card
    ├── PipelineDiagram.jsx node-by-node graph animation
    ├── MonitorTab.jsx      inventory + shipment monitor
    ├── OptionsTab.jsx      candidate table + governance + execution
    ├── EventTimeline.jsx   Trail — per-node event cards by stage
    └── HistoryTab.jsx      past runs
```

All styling is styled-components reading from the theme — no CSS files, no
hardcoded hex in components.
