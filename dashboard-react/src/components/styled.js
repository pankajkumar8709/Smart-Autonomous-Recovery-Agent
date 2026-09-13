import styled, { keyframes } from "styled-components";

export const Page = styled.div`
  max-width: 1180px;
  margin: 0 auto;
  padding: 40px 24px 72px;
`;

export const Header = styled.header`
  margin-bottom: 28px;
  h1 {
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.025em;
    margin: 0 0 6px;
  }
  p {
    margin: 0;
    color: ${(p) => p.theme.colors.textMuted};
    font-size: 14px;
  }
`;

export const Grid = styled.div`
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 22px;
  align-items: start;
  @media (max-width: 880px) {
    grid-template-columns: 1fr;
  }
`;

export const Card = styled.section`
  background: ${(p) => p.theme.colors.surface};
  border: 1px solid ${(p) => p.theme.colors.border};
  border-radius: ${(p) => p.theme.radius.lg};
  box-shadow: ${(p) => p.theme.shadow.card};
  padding: 22px;
`;

export const CardTitle = styled.h2`
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: ${(p) => p.theme.colors.textMuted};
  margin: 0 0 16px;
  display: flex;
  align-items: center;
  gap: 10px;
`;

export const Label = styled.label`
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: ${(p) => p.theme.colors.textMuted};
  margin: 14px 0 6px;
`;

const fieldStyles = `
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
`;

export const Input = styled.input`
  ${fieldStyles}
  background: ${(p) => p.theme.colors.surfaceAlt};
  border: 1px solid ${(p) => p.theme.colors.border};
  color: ${(p) => p.theme.colors.text};
  transition: border-color 0.15s, box-shadow 0.15s;
  &:focus {
    outline: none;
    border-color: ${(p) => p.theme.colors.accent};
    box-shadow: 0 0 0 3px ${(p) => p.theme.colors.accentSoft};
  }
`;

export const Select = styled.select`
  ${fieldStyles}
  background: ${(p) => p.theme.colors.surfaceAlt};
  border: 1px solid ${(p) => p.theme.colors.border};
  color: ${(p) => p.theme.colors.text};
  cursor: pointer;
  &:focus {
    outline: none;
    border-color: ${(p) => p.theme.colors.accent};
    box-shadow: 0 0 0 3px ${(p) => p.theme.colors.accentSoft};
  }
`;

export const Range = styled.input.attrs({ type: "range" })`
  width: 100%;
  accent-color: ${(p) => p.theme.colors.accent};
  cursor: pointer;
`;

export const CheckRow = styled.div`
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 16px;
  input {
    accent-color: ${(p) => p.theme.colors.accent};
    width: 16px;
    height: 16px;
    cursor: pointer;
  }
  label {
    margin: 0;
    font-size: 13px;
    color: ${(p) => p.theme.colors.text};
    cursor: pointer;
  }
`;

export const Button = styled.button`
  width: 100%;
  margin-top: 22px;
  padding: 12px 16px;
  border: none;
  border-radius: 11px;
  background: linear-gradient(90deg, ${(p) => p.theme.colors.accent}, #6a92ff);
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  transition: transform 0.06s ease, box-shadow 0.2s, opacity 0.2s;
  box-shadow: ${(p) => p.theme.shadow.hover};
  &:hover:not(:disabled) {
    transform: translateY(-1px);
  }
  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
    box-shadow: none;
  }
`;

export const Pill = styled.span`
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: ${(p) => p.theme.radius.pill};
  background: ${(p) => p.theme.colors.accentSoft};
  color: ${(p) => p.theme.colors.accent};
`;

export const Empty = styled.div`
  color: ${(p) => p.theme.colors.textFaint};
  font-size: 14px;
  text-align: center;
  padding: 48px 12px;
  line-height: 1.6;
`;

export const ErrorText = styled.div`
  color: ${(p) => p.theme.colors.red};
  background: ${(p) => p.theme.colors.redSoft};
  border: 1px solid ${(p) => p.theme.colors.red}33;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  margin-top: 14px;
`;

const spin = keyframes`to { transform: rotate(360deg); }`;
export const Spinner = styled.span`
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #ffffff;
  border-top-color: transparent;
  border-radius: 50%;
  animation: ${spin} 0.7s linear infinite;
  vertical-align: -2px;
  margin-right: 8px;
`;

// ---- Production layout & data-display primitives ----

export const TopBar = styled.header`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px;
  background: ${(p) => p.theme.colors.surface};
  border-bottom: 1px solid ${(p) => p.theme.colors.border};
  position: sticky;
  top: 0;
  z-index: 20;
  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .logo {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: linear-gradient(135deg, ${(p) => p.theme.colors.accent}, ${(p) => p.theme.colors.violet});
    display: grid;
    place-items: center;
    color: #fff;
    font-weight: 800;
  }
  h1 {
    font-size: 16px;
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.01em;
  }
  .sub {
    font-size: 12px;
    color: ${(p) => p.theme.colors.textMuted};
  }
`;

export const Health = styled.span`
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: ${(p) => (p.$ok ? p.theme.colors.green : p.theme.colors.red)};
  &::before {
    content: "";
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 0 3px ${(p) => (p.$ok ? p.theme.colors.greenSoft : p.theme.colors.redSoft)};
  }
`;

export const StatRow = styled.div`
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 22px;
  @media (max-width: 780px) {
    grid-template-columns: repeat(2, 1fr);
  }
`;

export const StatCard = styled.div`
  background: ${(p) => p.theme.colors.surface};
  border: 1px solid ${(p) => p.theme.colors.border};
  border-radius: ${(p) => p.theme.radius.lg};
  box-shadow: ${(p) => p.theme.shadow.card};
  padding: 16px 18px;
  .k {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: ${(p) => p.theme.colors.textMuted};
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .v {
    font-size: 24px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    color: ${(p) => p.$tone ? p.theme.colors[p.$tone] : p.theme.colors.text};
  }
  .hint {
    font-size: 11px;
    color: ${(p) => p.theme.colors.textFaint};
    margin-top: 4px;
  }
`;

export const Tabs = styled.div`
  display: flex;
  gap: 4px;
  background: ${(p) => p.theme.colors.surfaceAlt};
  border: 1px solid ${(p) => p.theme.colors.border};
  padding: 5px;
  border-radius: ${(p) => p.theme.radius.md};
  margin-bottom: 20px;
  width: fit-content;
  flex-wrap: wrap;
`;

export const Tab = styled.button`
  border: none;
  background: ${(p) => (p.$active ? p.theme.colors.surface : "transparent")};
  color: ${(p) => (p.$active ? p.theme.colors.accent : p.theme.colors.textMuted)};
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
  border-radius: 9px;
  cursor: pointer;
  box-shadow: ${(p) => (p.$active ? p.theme.shadow.card : "none")};
  transition: color 0.15s, background 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  .count {
    font-size: 11px;
    background: ${(p) => (p.$active ? p.theme.colors.accentSoft : p.theme.colors.border)};
    color: ${(p) => (p.$active ? p.theme.colors.accent : p.theme.colors.textMuted)};
    border-radius: ${(p) => p.theme.radius.pill};
    padding: 1px 7px;
    font-weight: 700;
  }
`;

export const Table = styled.table`
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  th {
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: ${(p) => p.theme.colors.textMuted};
    font-weight: 600;
    padding: 10px 12px;
    border-bottom: 1px solid ${(p) => p.theme.colors.border};
  }
  td {
    padding: 12px;
    border-bottom: 1px solid ${(p) => p.theme.colors.border};
    color: ${(p) => p.theme.colors.text};
    font-variant-numeric: tabular-nums;
  }
  tr:last-child td {
    border-bottom: none;
  }
  tr.winner td {
    background: ${(p) => p.theme.colors.greenSoft};
  }
  tr.rejected td {
    color: ${(p) => p.theme.colors.textFaint};
    text-decoration: line-through;
  }
`;

export const StatusBadge = styled.span`
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 4px 10px;
  border-radius: ${(p) => p.theme.radius.pill};
  color: ${(p) => p.theme.colors[p.$tone] || p.theme.colors.textMuted};
  background: ${(p) => p.theme.colors[`${p.$tone}Soft`] || p.theme.colors.surfaceAlt};
`;

export const BarTrack = styled.div`
  height: 8px;
  border-radius: ${(p) => p.theme.radius.pill};
  background: ${(p) => p.theme.colors.border};
  overflow: hidden;
`;

export const BarFill = styled.div`
  height: 100%;
  width: ${(p) => Math.min(100, Math.max(0, p.$pct))}%;
  border-radius: ${(p) => p.theme.radius.pill};
  background: ${(p) => p.theme.colors[p.$tone] || p.theme.colors.accent};
  transition: width 0.5s ease;
`;

export const Muted = styled.span`
  color: ${(p) => p.theme.colors.textMuted};
`;

