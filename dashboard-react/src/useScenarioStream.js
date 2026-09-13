import { useCallback, useRef, useState } from "react";

// Drives the SSE stream from GET /api/v1/stream-scenario. Accumulates:
//   events         — every node frame, in order (Trail tab + pipeline)
//   live           — latest known agent state slices (Monitor/Options/Optimize)
//   activeNode     — the node currently lit in the pipeline diagram
//   status         — idle | running | done | error
//   final          — the summary frame (result banner)
const EMPTY_LIVE = {
  inventory_state: null,
  shipment_state: null,
  disruption_info: null,
  candidate_options: null,
  scored_candidates: null,
  optimal_plan: null,
  governance_approved: null,
  execution_result: null,
  invalidated_options: [],
  computed_required_kg: null,
};

export function useScenarioStream() {
  const [events, setEvents] = useState([]);
  const [live, setLive] = useState(EMPTY_LIVE);
  const [activeNode, setActiveNode] = useState(null);
  const [status, setStatus] = useState("idle");
  const [final, setFinal] = useState(null);
  const [threadId, setThreadId] = useState(null);
  const [error, setError] = useState(null);
  const esRef = useRef(null);

  const stop = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const run = useCallback(
    (params) => {
      stop();
      setEvents([]);
      setLive(EMPTY_LIVE);
      setActiveNode(null);
      setFinal(null);
      setThreadId(null);
      setError(null);
      setStatus("running");

      const qs = new URLSearchParams({
        facility_id: params.facility_id,
        shipment_id: params.shipment_id,
        shipment_status: params.shipment_status,
        surge_ratio: String(params.surge_ratio),
        inject_reefer: String(params.inject_reefer),
        inject_vendor_failure: String(params.inject_vendor_failure || false),
        vendor_id: params.vendor_id || "VEND-TAIPEI",
        reset_scenario: String(params.reset_scenario || false),
        scenario: params.scenario || "stock_breach",
      });
      const es = new EventSource(`/api/v1/stream-scenario?${qs}`);
      esRef.current = es;

      es.onmessage = (e) => {
        let msg;
        try {
          msg = JSON.parse(e.data);
        } catch {
          return;
        }

        if (msg.kind === "meta") {
          setThreadId(msg.thread_id);
        } else if (msg.kind === "node") {
          setEvents((prev) => [...prev, msg]);
          setActiveNode(msg.node);
          setLive((prev) => {
            const next = { ...prev };
            for (const k of Object.keys(EMPTY_LIVE)) {
              if (msg[k] !== undefined && msg[k] !== null) next[k] = msg[k];
            }
            return next;
          });
        } else if (msg.kind === "disruption") {
          const frame =
            msg.stage === 3
              ? {
                  kind: "node",
                  stage: 3,
                  node: "telemetry",
                  message: `Vendor condition change: ${msg.vendor_id} STOCK_OUT (out-of-band).`,
                }
              : {
                  kind: "node",
                  stage: 2,
                  node: "telemetry",
                  message: `Reefer excursion: transfer ${msg.transfer_id} now ${msg.temp_celsius}°C (out-of-band).`,
                };
          setEvents((prev) => [...prev, frame]);
        } else if (msg.kind === "final") {
          setFinal(msg);
        } else if (msg.kind === "warning") {
          setEvents((prev) => [
            ...prev,
            { kind: "node", stage: 0, node: "environment", message: msg.message },
          ]);
        } else if (msg.kind === "error") {
          setError(`${msg.detail} — is the sandbox running on 127.0.0.1:8000?`);
          setStatus("error");
          stop();
        } else if (msg.kind === "done") {
          setActiveNode(null);
          setStatus((s) => (s === "error" ? s : "done"));
          stop();
        }
      };

      es.onerror = () => {
        setError("Stream connection failed — is the sandbox running on 127.0.0.1:8000?");
        setStatus("error");
        stop();
      };
    },
    [stop]
  );

  return { run, stop, events, live, activeNode, status, final, threadId, error };
}
