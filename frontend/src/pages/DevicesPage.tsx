import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { apiUrl, wsUrl } from "../config";
import { useTelemetry } from "../hooks/useTelemetry";

/* ── Types ─────────────────────────────────────────────────────── */

type Joint = { name: string; id: number; min: number; max: number };
type Scales = Record<string, { min: number; max: number }>;

type TelemetrySample = {
  key: string;
  ts: number;
  val: number;
};

type PlotPane = {
  id: string;
  title: string;
  metricKeys: string[];
  paused: boolean;
  timeWindowSec: number;
  autoScale: boolean;
  minVal: number;
  maxVal: number;
  zoomOffsetSec: number;
};

const METRIC_COLORS = [
  "#ff6b6b",
  "#3dd68c",
  "#5b9cff",
  "#f0c14a",
  "#c084fc",
  "#fb923c",
  "#38bdf8",
  "#f43f5e",
];

const PARAM_UNITS: Record<string, string> = {
  position: "rad",
  voltage_v: "V",
  current_ma: "mA",
  temperature_c: "°C",
  speed: "rad/s",
  load: "raw",
};

/* ── Main Component ────────────────────────────────────────────── */

export default function DevicesPage() {
  const { snapshot, connected } = useTelemetry();
  const [joints, setJoints] = useState<Joint[]>([]);
  const [scales, setScales] = useState<Scales>({});
  const [selectedJointName, setSelectedJointName] = useState<string | null>(null);
  const [filterText, setFilterText] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Enable/Toggle States for selected joint
  const [jointEnabled, setJointEnabled] = useState<Record<string, boolean>>({});
  const [jointOutputEnable, setJointOutputEnable] = useState<Record<string, boolean>>({});
  const [targetPositions, setTargetPositions] = useState<Record<string, number>>({});

  // Plot Panes State
  const [plotPanes, setPlotPanes] = useState<PlotPane[]>([
    {
      id: "plot_1",
      title: "Plot 1",
      metricKeys: [],
      paused: false,
      timeWindowSec: 10,
      autoScale: true,
      minVal: 0,
      maxVal: 4096,
      zoomOffsetSec: 0,
    },
  ]);

  // Buffer storing historical samples per metric key (e.g. "head_yaw.position")
  const telemetryBuf = useRef<Record<string, TelemetrySample[]>>({});

  // Load configuration
  useEffect(() => {
    fetch(apiUrl("/api/config"))
      .then((r) => r.json())
      .then((c) => {
        const list = Object.entries(c.joints || {}).map(
          ([name, j]: [string, any]) => ({ name, ...j })
        );
        setJoints(list);
        setScales(c.telemetry_scales || {});
        if (list.length) {
          setSelectedJointName(list[0].name);
          // Default enable state
          const initEn: Record<string, boolean> = {};
          const initOut: Record<string, boolean> = {};
          list.forEach((j) => {
            initEn[j.name] = true;
            initOut[j.name] = true;
          });
          setJointEnabled(initEn);
          setJointOutputEnable(initOut);
        }
      })
      .catch(() => undefined);
  }, []);

  // Subscribe to device logs
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/nodes/motors.telemetry/logs"));
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          const line = msg.line || JSON.stringify(msg);
          setLogs((prev) => [...prev.slice(-200), `${new Date().toLocaleTimeString()} ${line}`]);
        } catch {}
      };
      ws.onclose = () => {
        if (!closed) setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      ws?.close();
    };
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // Record incoming motor telemetry into historical buffer
  useEffect(() => {
    if (!snapshot?.motors) return;
    const now = Date.now() / 1000;
    const buf = telemetryBuf.current;

    Object.entries(snapshot.motors).forEach(([jointName, motorData]: [string, any]) => {
      if (!motorData) return;
      const metrics = ["position", "voltage_v", "current_ma", "temperature_c", "speed", "load"];
      metrics.forEach((m) => {
        const val = motorData[m];
        if (typeof val === "number" && Number.isFinite(val)) {
          const key = `${jointName}.${m}`;
          if (!buf[key]) buf[key] = [];
          buf[key].push({ key, ts: now, val });
          if (buf[key].length > 1000) buf[key] = buf[key].slice(-1000);
        }
      });
    });
  }, [snapshot]);

  // Filter joints
  const filteredJoints = useMemo(() => {
    if (!filterText) return joints;
    return joints.filter(
      (j) => j.name.toLowerCase().includes(filterText.toLowerCase()) || String(j.id).includes(filterText)
    );
  }, [joints, filterText]);

  const joint = useMemo(
    () => joints.find((j) => j.name === selectedJointName) || joints[0],
    [joints, selectedJointName]
  );

  const motorData = selectedJointName ? snapshot?.motors?.[selectedJointName] : null;
  const motorsNodeState = snapshot?.nodes?.["motors.telemetry"] ?? "offline";

  // Position control slider handler
  const handlePositionChange = async (targetRad: number) => {
    if (!joint) return;
    setTargetPositions((prev) => ({ ...prev, [joint.name]: targetRad }));
    try {
      await fetch(apiUrl("/api/setup/calibration/joint/goto-zero"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ joint_name: joint.name, offset: targetRad }),
      });
    } catch {}
  };

  // Toggle motor torque / enable
  const toggleJointEnable = async (jointName: string, active: boolean) => {
    setJointEnabled((prev) => ({ ...prev, [jointName]: !active }));
    const ep = active
      ? "/api/setup/calibration/joint/disable-torque"
      : "/api/setup/calibration/joint/enable-torque";
    try {
      await fetch(apiUrl(ep), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ joint_name: jointName }),
      });
    } catch {}
  };

  // Plot Pane Management
  const addPlotPane = () => {
    setPlotPanes((prev) => [
      ...prev,
      {
        id: `plot_${Date.now()}`,
        title: `Plot ${prev.length + 1}`,
        metricKeys: [],
        paused: false,
        timeWindowSec: 10,
        autoScale: true,
        minVal: 0,
        maxVal: 4096,
        zoomOffsetSec: 0,
      },
    ]);
  };

  const removePlotPane = (id: string) => {
    if (plotPanes.length <= 1) return;
    setPlotPanes((prev) => prev.filter((p) => p.id !== id));
  };

  const updatePlotPane = (id: string, patch: Partial<PlotPane>) => {
    setPlotPanes((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  };

  const toggleMetricInPlot = (paneId: string, key: string) => {
    const pane = plotPanes.find((p) => p.id === paneId);
    if (!pane) return;
    const exists = pane.metricKeys.includes(key);
    const nextKeys = exists ? pane.metricKeys.filter((k) => k !== key) : [...pane.metricKeys, key];
    updatePlotPane(paneId, { metricKeys: nextKeys });
  };

  return (
    <div className="page devices-workbench">
      {/* Page Title & Status Header */}
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Devices & Servo Telemetry Workbench</span>
          <span className="muted" style={{ fontSize: 11 }}>
            WS {connected ? "Connected" : "Offline"} · Motors Node: {motorsNodeState}
          </span>
        </div>
        <div className="btn-row">
          <span className={`badge ${connected ? "" : "badge-off"}`}>
            {connected ? "Bus Active" : "Bus Offline"}
          </span>
        </div>
      </div>

      {/* Main 3-Column Grid */}
      <div className="devices-main-grid">
        {/* Left Column: Device Tree List */}
        <div className="devices-tree-col">
          <div className="devices-tree-header">
            <input
              className="devices-search-input"
              placeholder="🔍 Filter devices..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
          </div>
          <div className="devices-tree-list">
            {filteredJoints.map((j) => {
              const active = j.name === selectedJointName;
              return (
                <button
                  key={j.name}
                  className={`device-tree-item ${active ? "active" : ""}`}
                  onClick={() => setSelectedJointName(j.name)}
                >
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <span>⚙️ {j.name}</span>
                    <span className="muted" style={{ fontSize: 10 }}>ID #{j.id}</span>
                  </div>
                  <span className="calib-status calibrated" style={{ fontSize: 9, padding: "1px 4px" }}>
                    Active
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Middle Column: Selected Device Controls & Parameters */}
        <div className="devices-params-col">
          {joint ? (
            <>
              {/* Selected Device Title & Config */}
              <div className="device-section-box">
                <div className="device-section-header">
                  <span>⚙️ {joint.name} (ID #{joint.id})</span>
                  <span className="calib-status calibrated" style={{ fontSize: 10 }}>Online</span>
                </div>

                {/* Enable & Output Enable Toggles */}
                <div className="toggle-switch-row">
                  <span>Enable</span>
                  <button
                    className={`toggle-switch ${jointEnabled[joint.name] !== false ? "on" : ""}`}
                    onClick={() => toggleJointEnable(joint.name, jointEnabled[joint.name] !== false)}
                  >
                    <span className="toggle-knob" />
                  </button>
                </div>

                <div className="toggle-switch-row">
                  <span>Output Enable</span>
                  <button
                    className={`toggle-switch ${jointOutputEnable[joint.name] !== false ? "on" : ""}`}
                    onClick={() => setJointOutputEnable((prev) => ({ ...prev, [joint.name]: !prev[joint.name] }))}
                  >
                    <span className="toggle-knob" />
                  </button>
                </div>
              </div>

              {/* Status Box */}
              <div className="device-section-box">
                <div className="device-section-header">Status</div>
                <div className="toggle-switch-row">
                  <span className="muted">Status</span>
                  <span className="value-badge high">Ready</span>
                </div>
                <div className="toggle-switch-row">
                  <span className="muted">Error</span>
                  <span className="value-badge low">No Error</span>
                </div>
                <div className="toggle-switch-row">
                  <span className="muted">Loop Time</span>
                  <span style={{ fontFamily: "IBM Plex Mono", fontSize: 11 }}>0.0010s</span>
                </div>
              </div>

              {/* Position Control Slider & Range Limits */}
              <div className="device-section-box">
                <div className="device-section-header">
                  <span>Position Servo Control</span>
                  <span className="param-card-val">
                    {(motorData?.position ?? 0).toFixed(2)} rad ({((motorData?.position ?? 0) * (180 / Math.PI)).toFixed(1)}°)
                  </span>
                </div>
                <div className="range-slider-box">
                  <input
                    type="range"
                    className="range-slider-input"
                    min={joint.min}
                    max={joint.max}
                    step={0.01}
                    value={targetPositions[joint.name] ?? motorData?.position ?? 0}
                    onChange={(e) => handlePositionChange(Number(e.target.value))}
                  />
                  <div className="range-slider-labels">
                    <span>Min: {joint.min.toFixed(2)} rad</span>
                    <span>Max: {joint.max.toFixed(2)} rad</span>
                  </div>
                </div>
              </div>

              {/* Sensors & Parameters List */}
              <div className="device-section-box">
                <div className="device-section-header">Sensors & Telemetry</div>

                {[
                  { m: "position", label: "Position", val: motorData?.position ?? 0, unit: "rad" },
                  { m: "voltage_v", label: "Voltage", val: motorData?.voltage_v ?? 0, unit: "V" },
                  { m: "current_ma", label: "Current", val: motorData?.current_ma ?? 0, unit: "mA" },
                  { m: "temperature_c", label: "Temperature", val: motorData?.temperature_c ?? 0, unit: "°C" },
                  { m: "speed", label: "Speed", val: motorData?.speed ?? 0, unit: "rad/s" },
                  { m: "load", label: "Load", val: motorData?.load ?? 0, unit: "raw" },
                ].map(({ m, label, val, unit }) => {
                  const key = `${joint.name}.${m}`;
                  const isPlotted = plotPanes[0].metricKeys.includes(key);

                  return (
                    <div key={m} className="param-card">
                      <div className="param-card-header">
                        <span>{label}</span>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span className="param-card-val">
                            {Number.isFinite(val) ? val.toFixed(2) : "—"} {unit}
                          </span>
                          <button
                            className={`btn ${isPlotted ? "primary" : ""}`}
                            style={{ fontSize: 10, padding: "2px 6px" }}
                            onClick={() => toggleMetricInPlot(plotPanes[0].id, key)}
                            title={isPlotted ? "Remove from Plot" : "Plot on Graph"}
                          >
                            {isPlotted ? "✓ Plotted" : "📈 + Graph"}
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="placeholder">Select a device from the left panel</div>
          )}
        </div>

        {/* Right Column: Telemetry Plot Workbench */}
        <div style={{ display: "flex", flexDirection: "column", minHeight: 0, minWidth: 0, height: "100%" }}>
          {plotPanes.map((pane) => (
            <DevicePlotPaneView
              key={pane.id}
              pane={pane}
              telemetryBuf={telemetryBuf}
              canClose={plotPanes.length > 1}
              onUpdate={(patch) => updatePlotPane(pane.id, patch)}
              onClose={() => removePlotPane(pane.id)}
              onAddPane={addPlotPane}
              onRemoveKey={(key) => toggleMetricInPlot(pane.id, key)}
            />
          ))}
        </div>
      </div>

      {/* Bottom Console Log Drawer */}
      <div className="devices-log-footer">
        <div className="gpio-section-title" style={{ padding: "4px 10px" }}>
          System & Device Host Log Stream
        </div>
        <div className="devices-log-scroll">
          {logs.length === 0 && <div className="placeholder" style={{ padding: 6 }}>No log entries yet</div>}
          {logs.map((l, i) => (
            <div key={i} className="gpio-log-line">{l}</div>
          ))}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
}

/* ── Telemetry Plot Pane View ──────────────────────────────────── */

function DevicePlotPaneView({
  pane,
  telemetryBuf,
  canClose,
  onUpdate,
  onClose,
  onAddPane,
  onRemoveKey,
}: {
  pane: PlotPane;
  telemetryBuf: React.MutableRefObject<Record<string, TelemetrySample[]>>;
  canClose: boolean;
  onUpdate: (patch: Partial<PlotPane>) => void;
  onClose: () => void;
  onAddPane: () => void;
  onRemoveKey: (key: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isDraggingTime = useRef(false);
  const dragStartX = useRef(0);
  const dragStartOffset = useRef(0);

  // Active Metric Keys: explicitly mapped or defaulted
  const activeKeys = pane.metricKeys;

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let raf = 0;

    const draw = () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;

      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      const W = rect.width, H = rect.height;

      // Dark background
      ctx.fillStyle = "#090c10";
      ctx.fillRect(0, 0, W, H);

      const paddingLeft = 50;
      const paddingRight = 15;
      const paddingTop = 15;
      const paddingBottom = 32;
      const graphW = W - paddingLeft - paddingRight;
      const graphH = H - paddingTop - paddingBottom;

      // Draw Y-axis grid
      ctx.strokeStyle = "#161d28";
      ctx.lineWidth = 1;
      const yTicks = 4;
      for (let i = 0; i <= yTicks; i++) {
        const y = paddingTop + (i / yTicks) * graphH;
        ctx.beginPath();
        ctx.moveTo(paddingLeft, y);
        ctx.lineTo(W - paddingRight, y);
        ctx.stroke();

        ctx.fillStyle = "#586579";
        ctx.font = "10px IBM Plex Mono, monospace";
        ctx.textAlign = "right";
        const val = pane.autoScale
          ? (1 - i / yTicks).toFixed(1)
          : (pane.maxVal - (i / yTicks) * (pane.maxVal - pane.minVal)).toFixed(1);
        ctx.fillText(String(val), paddingLeft - 6, y + 3);
      }

      // Draw X-axis grid & Dual Timestamps
      const xTicks = 10;
      const now = Date.now() / 1000;
      const effNow = pane.paused ? now - pane.zoomOffsetSec : now;

      for (let i = 0; i <= xTicks; i++) {
        const x = paddingLeft + (i / xTicks) * graphW;
        ctx.beginPath();
        ctx.moveTo(x, paddingTop);
        ctx.lineTo(x, H - paddingBottom);
        ctx.stroke();

        const ageSec = pane.timeWindowSec * (1 - i / xTicks) + pane.zoomOffsetSec;
        const absTime = new Date((effNow - ageSec) * 1000);
        const relLabel = ageSec === 0 ? "0.0s" : `-${ageSec.toFixed(1)}s`;
        const absLabel = absTime.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

        ctx.fillStyle = "#6e7d96";
        ctx.font = "9px system-ui";
        ctx.textAlign = "center";
        ctx.fillText(relLabel, x, H - paddingBottom + 12);
        ctx.fillStyle = "#48566b";
        ctx.font = "8px IBM Plex Mono, monospace";
        ctx.fillText(absLabel, x, H - paddingBottom + 22);
      }

      // If no active keys
      if (activeKeys.length === 0) {
        ctx.fillStyle = "#8b98ad";
        ctx.font = "12px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Click '📈 + Graph' on any parameter to plot live telemetry", W / 2, H / 2);
      }

      // Draw waveforms for each active metric
      const buf = telemetryBuf.current;

      activeKeys.forEach((key, idx) => {
        const samples = buf[key] || [];
        const color = METRIC_COLORS[idx % METRIC_COLORS.length];

        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        let started = false;

        for (const s of samples) {
          const ageSec = effNow - s.ts;
          if (ageSec < 0 || ageSec > pane.timeWindowSec + pane.zoomOffsetSec) continue;

          const normX = 1 - (ageSec - pane.zoomOffsetSec) / pane.timeWindowSec;
          if (normX < 0 || normX > 1) continue;

          const x = paddingLeft + normX * graphW;
          let normY = s.val;
          if (!pane.autoScale && pane.maxVal !== pane.minVal) {
            normY = (s.val - pane.minVal) / (pane.maxVal - pane.minVal);
          } else {
            // Auto scale fallback range
            normY = Math.max(0, Math.min(1, normY));
          }

          const y = paddingTop + graphH - normY * graphH * 0.85 - graphH * 0.07;

          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.stroke();

        // Draw sample points
        ctx.fillStyle = color;
        for (const s of samples) {
          const ageSec = effNow - s.ts;
          if (ageSec < 0 || ageSec > pane.timeWindowSec + pane.zoomOffsetSec) continue;
          const normX = 1 - (ageSec - pane.zoomOffsetSec) / pane.timeWindowSec;
          if (normX < 0 || normX > 1) continue;
          const x = paddingLeft + normX * graphW;
          let normY = s.val;
          if (!pane.autoScale && pane.maxVal !== pane.minVal) {
            normY = (s.val - pane.minVal) / (pane.maxVal - pane.minVal);
          } else {
            normY = Math.max(0, Math.min(1, normY));
          }
          const y = paddingTop + graphH - normY * graphH * 0.85 - graphH * 0.07;
          ctx.beginPath();
          ctx.arc(x, y, 2.5, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      if (!pane.paused) raf = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(raf);
  }, [pane, activeKeys, telemetryBuf]);

  // Zoom & Pan Mouse Events
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 2 : -2;
    const nextSec = Math.max(2, Math.min(120, pane.timeWindowSec + delta));
    onUpdate({ timeWindowSec: nextSec });
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    isDraggingTime.current = true;
    dragStartX.current = e.clientX;
    dragStartOffset.current = pane.zoomOffsetSec;
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDraggingTime.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dx = e.clientX - dragStartX.current;
    const secShift = (dx / rect.width) * pane.timeWindowSec;
    onUpdate({ zoomOffsetSec: Math.max(0, dragStartOffset.current - secShift) });
  };

  const handleMouseUp = () => {
    isDraggingTime.current = false;
  };

  return (
    <div className="gpio-graph-panel" style={{ flex: 1 }}>
      {/* Header Toolbar */}
      <div className="plot-header">
        <div className="plot-header-title">
          <span>📊 {pane.title}</span>
          <span className="muted" style={{ fontSize: 10 }}>({pane.timeWindowSec}s window)</span>
        </div>
        <div className="plot-toolbar">
          <button
            className={`plot-toolbar-btn ${pane.paused ? "active" : ""}`}
            onClick={() => onUpdate({ paused: !pane.paused })}
            title={pane.paused ? "Play stream" : "Pause stream"}
          >
            {pane.paused ? "▶ Play" : "⏸ Pause"}
          </button>
          <select
            className="plot-toolbar-btn"
            value={pane.timeWindowSec}
            onChange={(e) => onUpdate({ timeWindowSec: Number(e.target.value) })}
          >
            <option value={5}>5s</option>
            <option value={10}>10s</option>
            <option value={30}>30s</option>
            <option value={60}>60s</option>
          </select>
          <button
            className="plot-toolbar-btn"
            onClick={() => onUpdate({ zoomOffsetSec: 0, timeWindowSec: 10 })}
            title="Reset Zoom / Pan"
          >
            ↺ Reset
          </button>
          <button className="plot-toolbar-btn" onClick={onAddPane} title="Add Plot Pane">
            + Add Plot
          </button>
          {canClose && (
            <button
              className="plot-toolbar-btn"
              style={{ color: "var(--danger)" }}
              onClick={onClose}
              title="Close Plot"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Main Plot Area & Controls */}
      <div className="plot-body">
        <div
          className="gpio-canvas-wrapper"
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => { isDraggingTime.current = false; }}
        >
          <canvas ref={canvasRef} className="gpio-canvas" />
        </div>

        {/* Legend Sidebar & Scale Controls */}
        <div className="plot-sidebar">
          <div className="plot-sidebar-section">
            <div className="plot-sidebar-title">Active Traces</div>
            {activeKeys.length === 0 && (
              <div className="muted" style={{ fontStyle: "italic", fontSize: 10 }}>
                No metrics mapped. Click "+ Graph" on any parameter.
              </div>
            )}
            {activeKeys.map((key, idx) => {
              const color = METRIC_COLORS[idx % METRIC_COLORS.length];
              const samples = telemetryBuf.current[key] || [];
              const latest = samples.length > 0 ? samples[samples.length - 1].val : null;

              return (
                <div key={key} className="plot-trace-badge">
                  <div className="plot-trace-info">
                    <span className="plot-trace-dot" style={{ background: color }} />
                    <strong style={{ fontSize: 10 }}>{key}</strong>
                  </div>
                  <span className="plot-trace-val" style={{ color }}>
                    {latest !== null ? latest.toFixed(1) : "—"}
                  </span>
                  <button
                    className="btn danger"
                    style={{ padding: "0 4px", fontSize: 10, lineHeight: "14px" }}
                    onClick={() => onRemoveKey(key)}
                    title="Remove trace"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
          </div>

          {/* Scale Controls */}
          <div className="plot-sidebar-section" style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
            <div className="plot-sidebar-title">Scale Settings</div>
            <label className="toggle-switch-row" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Auto min/max</span>
              <button
                className={`toggle-switch ${pane.autoScale ? "on" : ""}`}
                style={{ width: 32, height: 18 }}
                onClick={() => onUpdate({ autoScale: !pane.autoScale })}
              >
                <span className="toggle-knob" style={{ width: 12, height: 12, top: 2, left: pane.autoScale ? 16 : 2 }} />
              </button>
            </label>

            {!pane.autoScale && (
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <div style={{ flex: 1 }}>
                  <span className="muted" style={{ fontSize: 9 }}>Minimum value</span>
                  <input
                    type="number"
                    className="plot-scale-input"
                    value={pane.minVal}
                    onChange={(e) => onUpdate({ minVal: Number(e.target.value) })}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <span className="muted" style={{ fontSize: 9 }}>Maximum value</span>
                  <input
                    type="number"
                    className="plot-scale-input"
                    value={pane.maxVal}
                    onChange={(e) => onUpdate({ maxVal: Number(e.target.value) })}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
