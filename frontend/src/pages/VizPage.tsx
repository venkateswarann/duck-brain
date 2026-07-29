import { useMemo, useState } from "react";
import { useTelemetry } from "../hooks/useTelemetry";

export default function VizPage() {
  const { snapshot } = useTelemetry();
  const [visible, setVisible] = useState<Record<string, boolean>>({
    robot: true,
    motors: true,
    video: true,
  });

  const motors = snapshot?.motors || {};
  const jointLines = useMemo(
    () =>
      Object.entries(motors).map(
        ([name, m]: [string, any]) => `${name}: ${(m.position ?? 0).toFixed(3)}`
      ),
    [motors]
  );

  const toggle = (k: string) =>
    setVisible((v) => ({ ...v, [k]: !v[k] }));

  return (
    <div className="page">
      <div className="page-title">
        <span>Viz</span>
        <span className="muted">URDF meshes bind later — live joint overlay now</span>
      </div>
      <div className="split split-tree">
        <div className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ marginBottom: 8 }}>
            Features / Sensors
          </div>
          {Object.keys(visible).map((k) => (
            <label
              key={k}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "6px 0",
                cursor: "pointer",
              }}
            >
              <span>{k}</span>
              <input
                type="checkbox"
                checked={!!visible[k]}
                onChange={() => toggle(k)}
              />
            </label>
          ))}
          <hr style={{ borderColor: "var(--border)" }} />
          <div className="muted">Node states</div>
          {Object.entries(snapshot?.nodes || {}).map(([id, st]) => (
            <div key={id} style={{ fontSize: 12, padding: "4px 0" }}>
              <span className={`status-dot status-${st}`} />
              {id}
            </div>
          ))}
        </div>
        <div
          className="panel"
          style={{
            display: "grid",
            placeItems: "center",
            background:
              "radial-gradient(circle at 50% 40%, #243044, #121820 70%)",
          }}
        >
          {visible.robot ? (
            <div style={{ textAlign: "center" }}>
              <div
                style={{
                  width: 120,
                  height: 160,
                  margin: "0 auto 16px",
                  borderRadius: 16,
                  background: "linear-gradient(180deg,#9aa3b2,#5c6575)",
                  boxShadow: "0 20px 40px rgba(0,0,0,.45)",
                }}
              />
              <div className="muted">Open Duck Mini (placeholder mesh)</div>
              {visible.motors && (
                <pre
                  className="log-view"
                  style={{
                    textAlign: "left",
                    maxHeight: 220,
                    marginTop: 16,
                    background: "rgba(0,0,0,.25)",
                    borderRadius: 8,
                  }}
                >
                  {jointLines.join("\n") || "waiting for motors…"}
                </pre>
              )}
              {visible.video && (
                <div className="muted" style={{ marginTop: 8 }}>
                  video: {snapshot?.video?.running ? "live" : "off"}
                </div>
              )}
            </div>
          ) : (
            <div className="muted">Robot hidden</div>
          )}
        </div>
      </div>
    </div>
  );
}
