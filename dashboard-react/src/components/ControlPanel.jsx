import styled from "styled-components";
import {
  Card,
  CardTitle,
  Label,
  Input,
  Select,
  Range,
  CheckRow,
  Button,
  ErrorText,
  Spinner,
} from "./styled.js";

const RangeValue = styled.span`
  color: ${(p) => p.theme.colors.accent};
  font-weight: 700;
  font-variant-numeric: tabular-nums;
`;

const Dot = styled.span`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: ${(p) => p.theme.colors.accent};
  display: inline-block;
`;

export default function ControlPanel({ form, setForm, onRun, onApplyEnv, loading, applying, error }) {
  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm({ ...form, [k]: v });
  };

  return (
    <Card>
      <CardTitle>
        <Dot /> Environment setup & run
      </CardTitle>

      <Label>Facility</Label>
      <Input value={form.facility_id} onChange={set("facility_id")} />

      <Label>Shipment</Label>
      <Input value={form.shipment_id} onChange={set("shipment_id")} />

      <Label>Shipment status</Label>
      <Select value={form.shipment_status} onChange={set("shipment_status")}>
        <option>CUSTOMS_HOLD</option>
        <option>DELAYED</option>
        <option>COMPROMISED</option>
        <option>IN_TRANSIT</option>
      </Select>

      <Label>
        Demand surge ratio{" "}
        <RangeValue>{Number(form.surge_ratio).toFixed(1)}×</RangeValue>
      </Label>
      <Range
        min="1"
        max="3"
        step="0.1"
        value={form.surge_ratio}
        onChange={(e) => setForm({ ...form, surge_ratio: parseFloat(e.target.value) })}
      />

      <CheckRow>
        <input
          id="reefer"
          type="checkbox"
          checked={form.inject_reefer}
          onChange={set("inject_reefer")}
        />
        <label htmlFor="reefer">Inject reefer excursion after Stage 1</label>
      </CheckRow>

      <CheckRow>
        <input
          id="vendorfail"
          type="checkbox"
          checked={form.inject_vendor_failure}
          onChange={set("inject_vendor_failure")}
        />
        <label htmlFor="vendorfail">Vendor stock-out after Stage 1 (3rd disruption)</label>
      </CheckRow>

      {form.inject_vendor_failure && (
        <>
          <Label>Vendor to stock out</Label>
          <Select value={form.vendor_id} onChange={set("vendor_id")}>
            <option value="VEND-TAIPEI">VEND-TAIPEI (certified)</option>
            <option value="VEND-LOCAL">VEND-LOCAL (uncertified)</option>
          </Select>
        </>
      )}

      <CheckRow>
        <input
          id="reset"
          type="checkbox"
          checked={form.reset_scenario}
          onChange={set("reset_scenario")}
        />
        <label htmlFor="reset">Reset environment first (fresh sandbox + run)</label>
      </CheckRow>

      {form.reset_scenario && (
        <>
          <Label>Reset to scenario</Label>
          <Select value={form.scenario} onChange={set("scenario")}>
            <option value="stock_breach">stock_breach — stock below safety</option>
            <option value="shipment_only">shipment_only — customs hold, stock healthy</option>
            <option value="demand_surge">demand_surge — surge conditions, stock healthy</option>
          </Select>
        </>
      )}

      <Button onClick={onRun} disabled={loading || applying}>
        {loading ? (
          <>
            <Spinner /> Running agent…
          </>
        ) : (
          "Run recovery"
        )}
      </Button>

      <Button onClick={onApplyEnv} disabled={loading || applying} style={{ marginTop: 10 }}>
        {applying ? (
          <>
            <Spinner /> Applying…
          </>
        ) : (
          "Apply environment (no run)"
        )}
      </Button>

      {error && <ErrorText>{error}</ErrorText>}
    </Card>
  );
}
