import { useEffect, useState } from "react";
import styled from "styled-components";
import { Card, CardTitle, StatusBadge, Empty, Muted, Table } from "./styled.js";

const RunCard = styled.div`
  border: 1px solid ${(p) => p.theme.colors.border};
  border-radius: ${(p) => p.theme.radius.md};
  padding: 14px 16px;
  margin-bottom: 12px;
  background: ${(p) => p.theme.colors.surfaceAlt};
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }
  .tid {
    font-family: ${(p) => p.theme.mono};
    font-size: 12px;
    font-weight: 600;
  }
  .meta {
    font-size: 12px;
    color: ${(p) => p.theme.colors.textMuted};
    font-variant-numeric: tabular-nums;
  }
`;

// `refreshKey` bumps after each run so the list re-fetches.
export default function HistoryTab({ refreshKey }) {
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/history")
      .then((r) => r.json())
      .then((d) => !cancelled && setRuns(d.runs || []))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (error) return <Empty>Could not load history: {error}</Empty>;
  if (!runs.length) return <Empty>No runs yet. Completed scenarios appear here.</Empty>;

  return (
    <Card>
      <CardTitle>Run history ({runs.length})</CardTitle>
      {runs.map((r) => (
        <RunCard key={r.thread_id + r.at}>
          <div className="top">
            <span className="tid">{r.thread_id}</span>
            <StatusBadge $tone={r.verified ? "green" : "red"}>
              {r.verified ? "recovered" : "escalated"}
            </StatusBadge>
          </div>
          <div className="meta">
            {r.params?.facility_id} · {r.params?.shipment_status} · surge{" "}
            {Number(r.params?.surge_ratio).toFixed(1)}× · replans {r.replan_count} ·{" "}
            plan <Muted>{r.final_plan?.id || "none"}</Muted>
          </div>
          <div className="meta">
            <Muted>{String(r.at).replace("T", " ").slice(0, 19)} UTC</Muted>
          </div>
        </RunCard>
      ))}
    </Card>
  );
}
