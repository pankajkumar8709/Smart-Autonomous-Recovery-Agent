import styled from "styled-components";

const NODES = [
  { id: "observe", label: "Observe" },
  { id: "detect", label: "Detect" },
  { id: "investigate", label: "Investigate" },
  { id: "optimize", label: "Optimize" },
  { id: "governance", label: "Govern" },
  { id: "execute", label: "Execute" },
  { id: "verify", label: "Verify" },
];

const Row = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  padding: 6px 2px 10px;
`;

const Node = styled.div`
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  min-width: 84px;
  opacity: ${(p) => (p.$state === "pending" ? 0.4 : 1)};
  transition: opacity 0.3s;
  .dot {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    font-weight: 800;
    font-size: 15px;
    border: 2px solid
      ${(p) =>
        p.$state === "active"
          ? p.theme.node[p.$id]?.fg
          : p.$state === "done"
          ? p.theme.colors.green
          : p.theme.colors.border};
    background: ${(p) =>
      p.$state === "active"
        ? p.theme.node[p.$id]?.bg
        : p.$state === "done"
        ? p.theme.colors.greenSoft
        : p.theme.colors.surfaceAlt};
    color: ${(p) =>
      p.$state === "active"
        ? p.theme.node[p.$id]?.fg
        : p.$state === "done"
        ? p.theme.colors.green
        : p.theme.colors.textFaint};
    box-shadow: ${(p) => (p.$state === "active" ? `0 0 0 4px ${p.theme.node[p.$id]?.bg}` : "none")};
    transition: all 0.25s;
    animation: ${(p) => (p.$state === "active" ? "pulse 1.1s ease-in-out infinite" : "none")};
  }
  .lbl {
    font-size: 11px;
    font-weight: 600;
    color: ${(p) =>
      p.$state === "pending" ? p.theme.colors.textFaint : p.theme.colors.text};
  }
  @keyframes pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.08); }
  }
`;

const Arrow = styled.div`
  flex: 0 0 auto;
  width: 18px;
  height: 2px;
  border-radius: 2px;
  background: ${(p) => (p.$done ? p.theme.colors.green : p.theme.colors.border)};
  transition: background 0.3s;
`;

export default function PipelineDiagram({ activeNode, visitedNodes }) {
  const stateFor = (id) => {
    if (activeNode === id) return "active";
    if (visitedNodes.has(id)) return "done";
    return "pending";
  };
  return (
    <Row>
      {NODES.map((n, i) => (
        <div key={n.id} style={{ display: "flex", alignItems: "center" }}>
          <Node $id={n.id} $state={stateFor(n.id)}>
            <div className="dot">{n.label[0]}</div>
            <span className="lbl">{n.label}</span>
          </Node>
          {i < NODES.length - 1 && <Arrow $done={visitedNodes.has(NODES[i + 1].id) || activeNode === NODES[i + 1].id} />}
        </div>
      ))}
    </Row>
  );
}
