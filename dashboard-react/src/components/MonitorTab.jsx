import styled from "styled-components";
import { Card, CardTitle, StatusBadge, BarTrack, BarFill, Muted, Empty } from "./styled.js";

const Cols = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  @media (max-width: 720px) {
    grid-template-columns: 1fr;
  }
`;

const Alert = styled.div`
  background: ${(p) => p.theme.colors.amberSoft};
  border: 1px solid ${(p) => p.theme.colors.amber}55;
  border-radius: ${(p) => p.theme.radius.md};
  padding: 14px 16px;
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  .icon {
    font-size: 18px;
  }
  .txt {
    font-size: 13px;
    color: ${(p) => p.theme.colors.text};
    b {
      color: ${(p) => p.theme.colors.amber};
    }
  }
`;

const Facility = styled.div`
  padding: 14px 0;
  border-bottom: 1px solid ${(p) => p.theme.colors.border};
  &:last-child {
    border-bottom: none;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }
  .name {
    font-weight: 600;
    font-size: 14px;
  }
  .id {
    font-family: ${(p) => p.theme.mono};
    font-size: 11px;
    color: ${(p) => p.theme.colors.textFaint};
  }
  .nums {
    font-size: 12px;
    color: ${(p) => p.theme.colors.textMuted};
    margin: 8px 0 6px;
    font-variant-numeric: tabular-nums;
  }
`;

function tempTone(t) {
  if (t == null) return "textMuted";
  return t >= 2 && t <= 8 ? "green" : "red";
}

export default function MonitorTab({ live, sandboxState }) {
  const inv = live.inventory_state;
  const reasons = live.disruption_info?.reasons || [];
  const vendors = sandboxState?.vendors || [];
  const demand = sandboxState?.demand || [];

  // Prefer the sandbox snapshot (all facilities); fall back to the single live one.
  const facilities =
    sandboxState?.inventory?.length
      ? sandboxState.inventory
      : inv
      ? [inv]
      : [];

  // Shipment truth: the sandbox snapshot is the environment of record; the live
  // in-run shipment_state wins only while a run is actively streaming it.
  const shipment = live.shipment_state || sandboxState?.shipments?.[0] || null;

  return (
    <div>
      {reasons.length > 0 && (
        <Alert>
          <span className="icon">⚠️</span>
          <span className="txt">
            Disruption detected — <b>{reasons.join(", ")}</b>
          </span>
        </Alert>
      )}

      <Cols>
        <Card>
          <CardTitle>Inventory monitor</CardTitle>
          {facilities.length === 0 && <Empty>No inventory data yet. Run a scenario.</Empty>}
          {facilities.map((f) => {
            const pct = f.safety_stock_kg ? (f.current_stock_kg / f.safety_stock_kg) * 100 : 0;
            const breach = f.current_stock_kg < f.safety_stock_kg;
            return (
              <Facility key={f.facility_id}>
                <div className="head">
                  <span className="name">{f.name || f.facility_id}</span>
                  <StatusBadge $tone={breach ? "red" : "green"}>
                    {breach ? "Below safety" : "Healthy"}
                  </StatusBadge>
                </div>
                <div className="id">{f.facility_id}</div>
                <div className="nums">
                  {f.current_stock_kg?.toLocaleString()} kg / safety{" "}
                  {f.safety_stock_kg?.toLocaleString()} kg &nbsp;·&nbsp; cold-chain{" "}
                  <StatusBadge $tone={tempTone(f.storage_temp_celsius)}>
                    {f.storage_temp_celsius}°C
                  </StatusBadge>
                </div>
                <BarTrack>
                  <BarFill $pct={pct} $tone={breach ? "red" : "green"} />
                </BarTrack>
              </Facility>
            );
          })}
        </Card>

        <Card>
          <CardTitle>Shipment monitor</CardTitle>
          {!shipment && <Empty>No shipment data yet.</Empty>}
          {shipment && (
            <Facility>
              <div className="head">
                <span className="name">Inbound shipment</span>
                <StatusBadge
                  $tone={
                    ["CUSTOMS_HOLD", "DELAYED", "COMPROMISED"].includes(shipment.status)
                      ? "amber"
                      : shipment.status === "REROUTED"
                      ? "violet"
                      : "green"
                  }
                >
                  {shipment.status}
                </StatusBadge>
              </div>
              <div className="id">{shipment.shipment_id}</div>
              <div className="nums">
                {shipment.origin && <>from {shipment.origin} · </>}
                dest {shipment.destination || "—"}
                {shipment.eta && (
                  <>
                    {" "}
                    · ETA <Muted>{String(shipment.eta).replace("T", " ").slice(0, 16)}</Muted>
                  </>
                )}
              </div>
            </Facility>
          )}

          {sandboxState?.transfers?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <CardTitle style={{ marginBottom: 8 }}>In-transit reefer</CardTitle>
              {sandboxState.transfers.map((t) => (
                <Facility key={t.transfer_id}>
                  <div className="head">
                    <span className="id">{t.transfer_id}</span>
                    <StatusBadge $tone={tempTone(t.current_temp_celsius)}>
                      {t.current_temp_celsius}°C
                    </StatusBadge>
                  </div>
                </Facility>
              ))}
            </div>
          )}
        </Card>
      </Cols>

      <Cols style={{ marginTop: 18 }}>
        <Card>
          <CardTitle>Vendors — live conditions (discovered via GET /vendors)</CardTitle>
          {vendors.length === 0 && <Empty>No vendor data in the sandbox.</Empty>}
          {vendors.map((v) => {
            const stock = v.stock_available_kg ?? 0;
            const stockedOut = stock <= 0;
            return (
              <Facility key={v.vendor_id}>
                <div className="head">
                  <span className="name">{v.name || v.vendor_id}</span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <StatusBadge $tone={v.cdsco_certified ? "green" : "red"}>
                      {v.cdsco_certified ? "CDSCO ✓" : "uncertified"}
                    </StatusBadge>
                    <StatusBadge $tone={stockedOut ? "red" : "violet"}>
                      {stockedOut ? "STOCK OUT" : `${stock.toLocaleString()} kg`}
                    </StatusBadge>
                  </span>
                </div>
                <div className="id">{v.vendor_id}</div>
                <div className="nums">
                  {v.location_city || "?"} · unit ₹
                  {(v.unit_cost_inr ?? 0).toLocaleString()}/kg · lead {v.lead_time_hours ?? "?"}h
                </div>
              </Facility>
            );
          })}
        </Card>

        <Card>
          <CardTitle>Demand signal (discovered via GET /demand)</CardTitle>
          {demand.length === 0 && (
            <Empty>No demand signal recorded — the agent reads this as baseline (no surge).</Empty>
          )}
          {demand.map((d) => {
            const surged = (d.surge_ratio ?? 1.0) > 1.3;
            return (
              <Facility key={d.facility_id}>
                <div className="head">
                  <span className="name">{d.facility_id}</span>
                  <StatusBadge $tone={surged ? "amber" : "green"}>
                    {d.surge_ratio}× {surged ? "SURGE" : "baseline"}
                  </StatusBadge>
                </div>
                <div className="nums">
                  observed burn {d.observed_daily_burn_kg?.toLocaleString()} kg/day · forecast{" "}
                  {d.forecast_daily_burn_kg?.toLocaleString()} kg/day · sku {d.sku_id}
                </div>
              </Facility>
            );
          })}
        </Card>
      </Cols>
    </div>
  );
}
