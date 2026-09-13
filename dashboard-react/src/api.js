// Talks to the FastAPI sandbox. In dev, Vite proxies /api -> 127.0.0.1:8000
// (see vite.config.js), so the browser stays same-origin and CORS-free.
const BASE = "/api/v1";

export async function runScenario(params) {
  const res = await fetch(`${BASE}/run-scenario`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Phase 5: set up the environment (reset? + shipment status + demand signal)
// WITHOUT running the agent — proves disruptions enter via HTTP and the
// Monitor tab then shows them before the agent acts.
export async function applyEnvironment(params) {
  const res = await fetch(`${BASE}/environment/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
