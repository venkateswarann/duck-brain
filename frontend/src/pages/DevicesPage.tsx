import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config";
import { useTelemetry } from "../hooks/useTelemetry";

type Joint = { name: string; id: number; min: number; max: number };
type Scales = Record<string, { min: number; max: number }>;

function clamp01(v: number) {
  return Math.max(0, Math.min(1, v));
}

function RangeBar({
  label,
  value,
  min,
  max,
  unit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  unit?: string;
}) {
  const pct = clamp01((value - min) / (max - min || 1)) * 100;
  return (
    <div className="range-row">
      <div className="muted">{label}</div>
      <div className="bar">
        <span style={{ width: `${pct}%` }} />
      </div>
      <div>
        {Number.isFinite(value) ? value.toFixed(2) : "—"}
        {unit ? ` ${unit}` : ""}
      </div>
    </div>
  );
}

export default function DevicesPage() {
  const { snapshot, connected } = useTelemetry();
  const [joints, setJoints] = useState<Joint[]>([]);
  const [scales, setScales] = useState<Scales>({});
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    fetch(apiUrl("/api/config"))
      .then((r) => r.json())
      .then((c) => {
        const list = Object.entries(c.joints || {}).map(
          ([name, j]: [string, any]) => ({ name, ...j })
        );
        setJoints(list);
        setScales(c.telemetry_scales || {});
        if (list.length) setSelected(list[0].name);
      })
      .catch(() => undefined);
  }, []);

  const motor = selected ? snapshot?.motors?.[selected] : null;
  const joint = useMemo(
    () => joints.find((j) => j.name === selected),
    [joints, selected]
  );
  const motorsNode = snapshot?.nodes?.["motors.telemetry"];

  return (
    <div className="page">
      <div className="page-title">
        <span>Devices / Motors</span>
        <span className="muted">
          WS {connected ? "connected" : "offline"} · motors node:{" "}
          {motorsNode ?? "—"}
        </span>
      </div>
      <div className="split split-tree">
        <div className="panel motor-list">
          {joints.map((j) => (
            <button
              key={j.name}
              className={j.name === selected ? "active" : ""}
              onClick={() => setSelected(j.name)}
            >
              <div>{j.name}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                ID {j.id}
              </div>
            </button>
          ))}
        </div>
        <div className="panel" style={{ padding: 16 }}>
          {!joint && <div className="placeholder">Select a motor</div>}
          {joint && (
            <>
              <h3 style={{ marginTop: 0 }}>
                {joint.name}{" "}
                <span className="muted">#{joint.id}</span>
              </h3>
              {motorsNode !== "running" && (
                <p className="muted">
                  Motors telemetry node is not running — start it under System /
                  Nodes.
                </p>
              )}
              <RangeBar
                label="Position"
                value={motor?.position ?? 0}
                min={joint.min}
                max={joint.max}
                unit="rad"
              />
              <RangeBar
                label="Temperature"
                value={motor?.temperature_c ?? 0}
                min={scales.temperature_c?.min ?? 0}
                max={scales.temperature_c?.max ?? 80}
                unit="°C"
              />
              <RangeBar
                label="Voltage"
                value={motor?.voltage_v ?? 0}
                min={scales.voltage_v?.min ?? 4}
                max={scales.voltage_v?.max ?? 8.5}
                unit="V"
              />
              <RangeBar
                label="Current"
                value={motor?.current_ma ?? 0}
                min={scales.current_ma?.min ?? 0}
                max={scales.current_ma?.max ?? 3000}
                unit="mA"
              />
              <RangeBar
                label="Load"
                value={motor?.load ?? 0}
                min={scales.load?.min ?? -1024}
                max={scales.load?.max ?? 1023}
              />
              <RangeBar
                label="Speed"
                value={motor?.speed ?? 0}
                min={scales.speed?.min ?? -3400}
                max={scales.speed?.max ?? 3400}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
