# Phase 7 — Persistence & CI (internal notes)

## What persistence means now

- `sandbox_snapshot.json` — the whole DB (inventory, shipments, vendors, lanes,
  transfers, allocations, demand), written atomically (tmp + os.replace) on
  EVERY mutation: transfer dispatch, purchase, reroute, allocate, reefer
  telemetry, shipment status, demand signal, vendor condition, `/reset`,
  `/environment/apply`.
- `run_history.json` — last 200 run summaries; loaded at startup.
- On startup the sandbox loads the snapshot if present (healed from seed if a
  collection is missing; corrupt/empty snapshots are ignored, never fatal).

## Escape hatches

- `SANDBOX_PERSIST=0` — fully in-memory (used by CI; also handy for demos where
  you want restart-to-seed semantics back).
- `SANDBOX_SNAPSHOT_PATH` / `SANDBOX_HISTORY_PATH` — relocate the files
  (tests can point these at a temp dir if needed).
- `POST /api/v1/reset {"clear_checkpoints": true}` — full clean slate
  (sandbox state + LangGraph checkpoint rows). The reset itself is persisted.

## Demo implication (important)

Restarting the sandbox NO LONGER resets the demo state. To get a fresh
environment for a demo run, either:
- click "Reset environment first" in the dashboard (scenario picker), or
- `curl -X POST .../api/v1/reset -H "Content-Type: application/json" -d '{}'`, or
- delete `sandbox_snapshot.json` and restart, or
- run with `SANDBOX_PERSIST=0` for classic ephemeral behavior.

## Files (Phase 7)

- `.gitignore` — runtime state (`agent_state.db*`, `sandbox_snapshot.json`,
  `run_history.json`), `.venv`, `node_modules`, logs, `.freebuff`.
- `.github/workflows/ci.yml` — three jobs:
  1. `unit` — `pytest -m "not integration"` (no sandbox).
  2. `integration` — boots uvicorn with `SANDBOX_PERSIST=0` on :8000, waits for
     `/health`, runs the full suite with `SANDBOX_PORT=8000`.
  3. `dashboard` — `npm ci` + `npm run build` (React 19 + Vite).
