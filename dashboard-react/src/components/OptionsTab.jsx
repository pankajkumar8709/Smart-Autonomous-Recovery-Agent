import styled from "styled-components";
import { Card, CardTitle, Table, StatusBadge, Empty, Muted } from "./styled.js";

const Verdict = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: ${(p) => p.theme.radius.md};
  margin-bottom: 18px;
  background: ${(p) => (p.$ok ? p.theme.colors.greenSoft : p.theme.colors.redSoft)};
  border: 1px solid ${(p) => (p.$ok ? p.theme.colors.green : p.theme.colors.red)}44;
  .lbl {
    font-weight: 800;
    font-size: 14px;
    color: ${(p) => (p.$ok ? p.theme.colors.green : p.theme.colors.red)};
  }
  .reason {
    font-size: 13px;
    color: ${(p) => p.theme.colors.text};
  }
`;

const money = (n) => (n == null ? "—" : `₹${n.toLocaleString()}`);

export default function OptionsTab({ live }) {
  const scored = live.scored_candidates || live.candidate_options || [];
  const winner = live.optimal_plan;
  const invalidated = new Set(live.invalidated_options || []);
  const gov = live.governance_approved;
  const exec = live.execution_result;
  const requiredKg = live.computed_required_kg;

  if (!scored.length) {
    return <Empty>No candidates investigated yet. Run a scenario to see the option comparison.</Empty>;
  }

  return (
    <div>
      {requiredKg != null && (
        <Verdict $ok={true}>
          <span className="lbl">COMPUTED DEFICIT</span>
          <span className="reason">
            required = {requiredKg.toLocaleString()} kg — computed from the live sandbox
            (max(0, safety − current) + surge buffer), not a constant.
          </span>
        </Verdict>
      )}

      {gov != null && (
        <Verdict $ok={gov}>
          <span className="lbl">GOVERNANCE {gov ? "APPROVED" : "REJECTED"}</span>
          <span className="reason">
            {winner?.id
              ? `${winner.id} · ₹${(winner.unit_cost_inr * winner.quantity_kg).toLocaleString()} committed`
              : "no plan"}
          </span>
        </Verdict>
      )}

      <Card>
        <CardTitle>Candidate options — feasibility & multi-constraint score</CardTitle>
        <Table>
          <thead>
            <tr>
              <th>Option</th>
              <th>Type</th>
              <th>Unit cost breakdown</th>
              <th>Transit</th>
              <th>Carbon</th>
              <th>CDSCO</th>
              <th>Score</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {scored.map((c) => {
              const isWinner = winner?.id === c.id;
              const rejected = c.feasible === false || invalidated.has(c.id);
              return (
                <tr key={c.id} className={isWinner ? "winner" : rejected ? "rejected" : ""}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{c.id}</td>
                  <td>{c.type}</td>
                  <td>
                    {c.breakdown ? (
                      <span style={{ fontSize: 12 }}>
                        {money(c.unit_cost_inr)}
                        <Muted>
                          {" "}
                          = ₹{c.breakdown.vendor_unit_cost.toLocaleString()} vendor + ₹
                          {c.breakdown.freight_per_kg.toLocaleString()} freight ({c.breakdown.distance_km.toLocaleString()} km) + ₹
                          {c.breakdown.handling_per_kg.toLocaleString()} handling
                        </Muted>
                      </span>
                    ) : (
                      money(c.unit_cost_inr)
                    )}
                  </td>
                  <td>{c.transit_time_hours}h</td>
                  <td>{c.carbon_per_kg_co2} kg</td>
                  <td>
                    {c.cdsco_certified ? (
                      <StatusBadge $tone="green">yes</StatusBadge>
                    ) : (
                      <StatusBadge $tone="red">no</StatusBadge>
                    )}
                  </td>
                  <td>{c.score == null ? <Muted>—</Muted> : c.score.toFixed(4)}</td>
                  <td>
                    {isWinner ? (
                      <StatusBadge $tone="green">selected</StatusBadge>
                    ) : c.feasible === false ? (
                      <StatusBadge $tone="red">infeasible</StatusBadge>
                    ) : invalidated.has(c.id) ? (
                      <StatusBadge $tone="amber">invalidated</StatusBadge>
                    ) : (
                      <Muted>feasible</Muted>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>

      {exec && (
        <Card style={{ marginTop: 16 }}>
          <CardTitle>Execution result (real sandbox call)</CardTitle>
          <Table>
            <tbody>
              {Object.entries(exec).map(([k, v]) => (
                <tr key={k}>
                  <td style={{ color: "var(--muted)", width: 200 }}>
                    <Muted>{k}</Muted>
                  </td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
