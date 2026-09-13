import { useEffect, useMemo, useState } from "react";
import styled from "styled-components";
import { useScenarioStream } from "./useScenarioStream.js";
import {
  Page,
  Grid,
  Card,
  TopBar,
  Health,
  StatRow,
  StatCard,
  Tabs,
  Tab,
  Spinner,
} from "./components/styled.js";
import { applyEnvironment } from "./api.js";
import ControlPanel from "./components/ControlPanel.jsx";
import PipelineDiagram from "./components/PipelineDiagram.jsx";
import MonitorTab from "./components/MonitorTab.jsx";
import OptionsTab from "./components/OptionsTab.jsx";
import EventTimeline from "./components/EventTimeline.jsx";
import HistoryTab from "./components/HistoryTab.jsx";

const INITIAL_FORM = {
  facility_id: "FAC-HYD-GENOME",
  shipment_id: "IMP-JNPT-8802",
  shipment_status: "CUSTOMS_HOLD",
  surge_ratio: 1.0,
  inject_reefer: true,
  inject_vendor_failure: false,
  vendor_id: "VEND-TAIPEI",
  reset_scenario: false,
  scenario: "stock_breach",
};

const PipelineWrap = styled(Card)`
  margin-bottom: 22px;
`;

const TabBody = styled.div`
  animation: fadeIn 0.2s ease;
`;

export default function App() {
  const [form, setForm] = useState(INITIAL_FORM);
  const [tab, setTab] = useState("monitor");
  const [sandboxState, setSandboxState] = useState(null);
  const [healthy, setHealthy] = useState(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [applying, setApplying] = useState(false);

  const { run, events, live, activeNode, status, final, threadId, error, setError } = useScenarioStream();

  // Poll sandbox health + state snapshot (also refreshed after a run completes).
  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/health")
      .then((r) => r.json())
      .then(() => !cancelled && setHealthy(true))
      .catch(() => !cancelled && setHealthy(false));
    fetch("/api/v1/state")
      .then((r) => r.json())
      .then((d) => !cancelled && setSandboxState(d))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [historyKey]);

  // When a run finishes, refresh the sandbox snapshot + history list.
  useEffect(() => {
    if (status === "done") setHistoryKey((k) => k + 1);
  }, [status]);

  const visitedNodes = useMemo(
    () => new Set(events.filter((e) => e.node !== "telemetry").map((e) => e.node)),
    [events]
  );

  function onRun() {
    run(form);
    setTab("trail");
  }

  async function onApplyEnv() {
    setApplying(true);
    try {
      await applyEnvironment(form);
      setTab("monitor");            // show the environment the agent would see
      setHistoryKey((k) => k + 1);  // refresh the sandbox snapshot
    } catch (e) {
      setError(`${e.message} — environment not applied`);
    } finally {
      setApplying(false);
    }
  }

  const verified = final?.verified;
  const replans = final?.replan_count ?? (live.invalidated_options?.length || 0);
  const stockRecovered = live.inventory_state
    ? live.inventory_state.current_stock_kg >= live.inventory_state.safety_stock_kg
    : null;

  return (
    <>
      <TopBar>
        <div className="brand">
          <div className="logo">◆</div>
          <div>
            <h1>Supply Chain Recovery Agent</h1>
            <div className="sub">Autonomous · monitor → detect → investigate → optimize → govern → execute → verify → replan</div>
          </div>
        </div>
        <Health $ok={healthy}>
          {healthy == null ? "checking…" : healthy ? "sandbox online" : "sandbox offline"}
        </Health>
      </TopBar>

      <Page>
        <StatRow>
          <StatCard $tone={verified === true ? "green" : verified === false ? "red" : undefined}>
            <div className="k">Recovery status</div>
            <div className="v">
              {status === "running" ? (
                <>
                  <Spinner /> running
                </>
              ) : verified === true ? (
                "RECOVERED"
              ) : verified === false ? (
                "ESCALATED"
              ) : (
                "—"
              )}
            </div>
            <div className="hint">{threadId ? `thread ${threadId}` : "no active run"}</div>
          </StatCard>
          <StatCard>
            <div className="k">Replan cycles</div>
            <div className="v">{replans}</div>
            <div className="hint">invalidated options excluded</div>
          </StatCard>
          <StatCard $tone={stockRecovered === true ? "green" : stockRecovered === false ? "amber" : undefined}>
            <div className="k">Destination stock</div>
            <div className="v">
              {live.inventory_state
                ? `${(live.inventory_state.current_stock_kg / 1000).toFixed(1)}t`
                : "—"}
            </div>
            <div className="hint">
              {live.inventory_state
                ? `safety ${(live.inventory_state.safety_stock_kg / 1000).toFixed(1)}t`
                : "awaiting observe"}
            </div>
          </StatCard>
          <StatCard>
            <div className="k">Selected action</div>
            <div className="v" style={{ fontSize: 16 }}>
              {live.optimal_plan?.type || "—"}
            </div>
            <div className="hint">{live.optimal_plan?.id || "no plan yet"}</div>
          </StatCard>
        </StatRow>

        <PipelineWrap>
          <PipelineDiagram activeNode={activeNode} visitedNodes={visitedNodes} />
        </PipelineWrap>

        <Grid>
          <ControlPanel
            form={form}
            setForm={setForm}
            onRun={onRun}
            onApplyEnv={onApplyEnv}
            loading={status === "running"}
            applying={applying}
            error={error}
          />

          <div>
            <Tabs>
              <Tab $active={tab === "monitor"} onClick={() => setTab("monitor")}>
                Monitor
              </Tab>
              <Tab $active={tab === "options"} onClick={() => setTab("options")}>
                Options
                {live.scored_candidates?.length ? (
                  <span className="count">{live.scored_candidates.length}</span>
                ) : null}
              </Tab>
              <Tab $active={tab === "trail"} onClick={() => setTab("trail")}>
                Trail
                {events.length ? <span className="count">{events.length}</span> : null}
              </Tab>
              <Tab $active={tab === "history"} onClick={() => setTab("history")}>
                History
              </Tab>
            </Tabs>

            <TabBody key={tab}>
              {tab === "monitor" && <MonitorTab live={live} sandboxState={sandboxState} />}
              {tab === "options" && <OptionsTab live={live} />}
              {tab === "trail" && (
                <Card>
                  {events.length ? (
                    <EventTimeline events={events} />
                  ) : (
                    <div style={{ padding: 40, textAlign: "center", color: "#94a1b8" }}>
                      Press <b>Run recovery</b> — the agent's steps stream in here live.
                    </div>
                  )}
                </Card>
              )}
              {tab === "history" && <HistoryTab refreshKey={historyKey} />}
            </TabBody>
          </div>
        </Grid>
      </Page>
    </>
  );
}
