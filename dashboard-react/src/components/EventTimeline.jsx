import styled from "styled-components";

const StageLabel = styled.div`
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: ${(p) => p.theme.colors.violet};
  margin: 20px 0 10px;
  &:first-child {
    margin-top: 4px;
  }
`;

const EventRow = styled.div`
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: ${(p) => p.theme.colors.surfaceAlt};
  border: 1px solid ${(p) => p.theme.colors.border};
  border-left: 3px solid ${(p) => p.theme.node[p.$node]?.fg || p.theme.colors.accent};
  border-radius: ${(p) => p.theme.radius.md};
  padding: 12px 14px;
  margin-bottom: 10px;
  animation: fadeIn 0.25s ease;
`;

const NodeBadge = styled.span`
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 5px 9px;
  border-radius: ${(p) => p.theme.radius.sm};
  white-space: nowrap;
  min-width: 96px;
  text-align: center;
  color: ${(p) => p.theme.node[p.$node]?.fg || p.theme.colors.accent};
  background: ${(p) => p.theme.node[p.$node]?.bg || p.theme.colors.accentSoft};
`;

const Message = styled.span`
  font-size: 13px;
  line-height: 1.5;
  color: ${(p) => p.theme.colors.text};
`;

function EventCard({ ev }) {
  return (
    <EventRow $node={ev.node}>
      <NodeBadge $node={ev.node}>{ev.node}</NodeBadge>
      <Message>{ev.message}</Message>
    </EventRow>
  );
}

const STAGE_LABELS = {
  0: "Stage 0 — environment setup",
  1: "Stage 1 — primary disruption",
  2: "Stage 2 — real secondary disruption (reefer excursion)",
  3: "Stage 3 — vendor condition change (out-of-band)",
};

export default function EventTimeline({ events }) {
  // Group by stage dynamically so new disruption stages render without
  // changes here. Stages appear in the order first seen (run order).
  const stages = [];
  const byStage = new Map();
  for (const ev of events) {
    const s = ev.stage ?? 1;
    if (!byStage.has(s)) {
      byStage.set(s, []);
      stages.push(s);
    }
    byStage.get(s).push(ev);
  }
  return (
    <div>
      {stages.map((s) => (
        <div key={s}>
          <StageLabel>{STAGE_LABELS[s] || `Stage ${s}`}</StageLabel>
          {(byStage.get(s) || []).map((ev, i) => (
            <EventCard key={`${s}-${i}`} ev={ev} />
          ))}
        </div>
      ))}
    </div>
  );
}
