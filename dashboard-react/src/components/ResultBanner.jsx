import styled from "styled-components";

const Banner = styled.div`
  margin-top: 22px;
  padding: 18px 20px;
  border-radius: ${(p) => p.theme.radius.lg};
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  align-items: center;
  background: ${(p) => (p.$ok ? p.theme.colors.greenSoft : p.theme.colors.redSoft)};
  border: 1px solid ${(p) => (p.$ok ? p.theme.colors.green : p.theme.colors.red)}55;
`;

const Verdict = styled.div`
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: ${(p) => (p.$ok ? p.theme.colors.green : p.theme.colors.red)};
`;

const Metric = styled.div`
  .k {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: ${(p) => p.theme.colors.textMuted};
    margin-bottom: 2px;
  }
  .v {
    font-size: 16px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: ${(p) => p.theme.colors.text};
  }
`;

export default function ResultBanner({ result }) {
  const ok = !!result.verified;
  return (
    <Banner $ok={ok}>
      <Verdict $ok={ok}>{ok ? "RECOVERED" : "ESCALATED"}</Verdict>
      <Metric>
        <div className="k">Verified</div>
        <div className="v">{String(result.verified)}</div>
      </Metric>
      <Metric>
        <div className="k">Replans</div>
        <div className="v">{result.replan_count}</div>
      </Metric>
      {result.final_plan?.id && (
        <Metric>
          <div className="k">Final plan</div>
          <div className="v">{result.final_plan.id}</div>
        </Metric>
      )}
      {result.reefer_injected && (
        <Metric>
          <div className="k">Reefer excursion</div>
          <div className="v">{result.reefer_injected}</div>
        </Metric>
      )}
    </Banner>
  );
}
