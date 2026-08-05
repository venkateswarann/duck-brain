import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { apiUrl, wsUrl } from "../config";

/* ── Types ─────────────────────────────────────────────────────── */

type BoardPin = {
  phys: number;
  bcm: number | null;
  name: string;
  type: string;
  alt?: string[];
};
type Board = { id: string; name: string; pins: BoardPin[] };

type Device = {
  id: string;
  type: string;
  label?: string;
  pins: Record<string, number | string>;
  mode?: string;
  pull?: string;
  default_value?: number;
  enabled?: boolean;
  reserved?: boolean;
  probe?: boolean;
  probe_rate_hz?: number;
  frequency?: number;
  duty_cycle?: number;
};

type Pinout = {
  schema_version?: number;
  board: string;
  devices: Device[];
};

type PinApiState = {
  bcm: number;
  direction: string;
  value: number;
  is_pwm: boolean;
  pwm_freq: number;
  pwm_duty: number;
  probing: boolean;
  device_id: string | null;
  label: string | null;
};

type ProbeSample = { bcm: number; value: number; ts: number };

type PlotPane = {
  id: string;
  title: string;
  bcms: number[];
  paused: boolean;
  timeWindowSec: number;
  autoScale: boolean;
  minVal: number;
  maxVal: number;
  zoomOffsetSec: number;
};

/* ── Helpers ───────────────────────────────────────────────────── */

const DEVICE_ICONS: Record<string, string> = {
  led: "💡",
  digital_input: "📥",
  pwm: "🎛️",
  actuator: "🎛️",
  i2c_sensor: "📡",
  i2s_audio: "🔊",
};

const TRACE_COLORS = [
  "#ff6b6b",
  "#3dd68c",
  "#5b9cff",
  "#f0c14a",
  "#c084fc",
  "#fb923c",
  "#38bdf8",
  "#f43f5e",
];

function deviceIcon(type: string) {
  return DEVICE_ICONS[type] || "⚙️";
}

/* ── Component ─────────────────────────────────────────────────── */

export default function BoardPinsPage() {
  const [boards, setBoards] = useState<Board[]>([]);
  const [pinout, setPinout] = useState<Pinout>({ board: "rpi_zero_2w", devices: [] });
  const [gpioState, setGpioState] = useState<PinApiState[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [selectedBcm, setSelectedBcm] = useState<number | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [gpioRunning, setGpioRunning] = useState(false);
  const [gpioMock, setGpioMock] = useState(false);

  // Layout State
  const [showLogs, setShowLogs] = useState(true);
  const [showGraph, setShowGraph] = useState(true);
  const [layoutPos, setLayoutPos] = useState<"bottom" | "right">("bottom");
  const [panelSize, setPanelSize] = useState(320);
  const [splitRatio, setSplitRatio] = useState(40);

  // Plot Panes State
  const [plotPanes, setPlotPanes] = useState<PlotPane[]>([
    {
      id: "plot_1",
      title: "Plot 1",
      bcms: [],
      paused: false,
      timeWindowSec: 10,
      autoScale: true,
      minVal: 0,
      maxVal: 1,
      zoomOffsetSec: 0,
    },
  ]);

  // Resize Handlers
  const startResizePanel = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startSize = panelSize;
    const startPos = layoutPos === "bottom" ? e.clientY : e.clientX;
    const onMove = (ev: MouseEvent) => {
      if (layoutPos === "bottom") {
        const delta = startPos - ev.clientY;
        setPanelSize(Math.max(120, Math.min(startSize + delta, window.innerHeight - 150)));
      } else {
        const delta = startPos - ev.clientX;
        setPanelSize(Math.max(250, Math.min(startSize + delta, window.innerWidth - 300)));
      }
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
    };
    document.body.style.cursor = layoutPos === "bottom" ? "ns-resize" : "ew-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [panelSize, layoutPos]);

  const startResizeSplit = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startRatio = splitRatio;
    const isRow = layoutPos === "bottom";
    const startPos = isRow ? e.clientX : e.clientY;
    const container = (e.target as HTMLElement).parentElement;
    const totalSize = isRow ? container?.clientWidth || window.innerWidth : container?.clientHeight || window.innerHeight;

    const onMove = (ev: MouseEvent) => {
      const delta = (isRow ? ev.clientX : ev.clientY) - startPos;
      const percentChange = (delta / totalSize) * 100;
      setSplitRatio(Math.max(10, Math.min(90, startRatio + percentChange)));
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
    };
    document.body.style.cursor = isRow ? "ew-resize" : "ns-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [splitRatio, layoutPos]);

  // Probe graph data: bcm → last N samples
  const probeBuf = useRef<Record<number, ProbeSample[]>>({});
  const logsEndRef = useRef<HTMLDivElement>(null);

  // ── Fetch boards + pinout ──────────────────────────────────────
  useEffect(() => {
    fetch(apiUrl("/api/boards")).then(r => r.json()).then(setBoards).catch(() => {});
    fetch(apiUrl("/api/pinout")).then(r => r.json()).then(setPinout).catch(() => {});
  }, []);

  // ── Poll GPIO state ────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    const poll = async () => {
      while (active) {
        try {
          const r = await fetch(apiUrl("/api/gpio/state"));
          if (r.ok) {
            const data = await r.json();
            setGpioState(data.pins || []);
            setGpioRunning(true);
            setGpioMock(data.mock === true);
          } else {
            setGpioRunning(false);
          }
        } catch { setGpioRunning(false); }
        await new Promise(res => setTimeout(res, 1000));
      }
    };
    poll();
    return () => { active = false; };
  }, []);

  // ── WebSocket for probe samples + logs ─────────────────────────
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/gpio/probe"));
      ws.onmessage = (ev) => {
        try {
          const sample: ProbeSample = JSON.parse(ev.data);
          const buf = probeBuf.current;
          if (!buf[sample.bcm]) buf[sample.bcm] = [];
          buf[sample.bcm].push(sample);
          if (buf[sample.bcm].length > 1000) buf[sample.bcm] = buf[sample.bcm].slice(-1000);
        } catch {}
      };
      ws.onclose = () => { if (!closed) setTimeout(connect, 2000); };
    };
    connect();
    return () => { closed = true; ws?.close(); };
  }, []);

  // ── Subscribe to gpio.pins node logs ───────────────────────────
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/nodes/gpio.pins/logs"));
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          const line = msg.line || JSON.stringify(msg);
          setLogs(prev => [...prev.slice(-200), `${new Date().toLocaleTimeString()} ${line}`]);
        } catch {}
      };
      ws.onclose = () => { if (!closed) setTimeout(connect, 2000); };
    };
    connect();
    return () => { closed = true; ws?.close(); };
  }, []);

  // Auto-scroll logs
  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  // ── Pin maps ───────────────────────────────────────────────────
  const board = boards.find(b => b.id === pinout.board) || boards[0];
  const usedBcms = useMemo(() => {
    const s = new Set<number>();
    for (const d of pinout.devices || [])
      Object.values(d.pins || {}).forEach(p => { const n = Number(p); if (!isNaN(n)) s.add(n); });
    return s;
  }, [pinout]);

  const gpioMap = useMemo(() => {
    const m: Record<number, PinApiState> = {};
    for (const p of gpioState) m[p.bcm] = p;
    return m;
  }, [gpioState]);

  const probingBcms = useMemo(
    () => new Set(gpioState.filter(p => p.probing).map(p => p.bcm)),
    [gpioState]
  );

  const left = (board?.pins || []).filter(p => p.phys % 2 === 1);
  const right = (board?.pins || []).filter(p => p.phys % 2 === 0);

  // ── Actions ────────────────────────────────────────────────────
  const save = async (next: Pinout) => {
    setPinout(next);
    await fetch(apiUrl("/api/pinout"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
  };

  const setupDeviceOnHardware = async (dev: Device) => {
    const signalPin = Number(dev.pins?.signal);
    if (isNaN(signalPin) || dev.reserved) return;

    await fetch(apiUrl("/api/gpio/setup"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        bcm: signalPin,
        direction: dev.mode || "OUT",
        pull: dev.pull || "NONE",
        device_id: dev.id,
        label: dev.label,
      }),
    });

    if (dev.mode === "OUT") {
      await fetch(apiUrl("/api/gpio/write"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bcm: signalPin, value: dev.default_value || 0 }),
      });
    }

    if (dev.mode === "IN" && dev.probe) {
      await fetch(apiUrl("/api/gpio/probe/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bcm: signalPin, rate_hz: dev.probe_rate_hz || 50 }),
      });
    }
  };

  const togglePin = async (bcm: number, currentVal: number) => {
    // Ensure the pin is set up first if not already registered in the GPIO service
    if (!gpioMap[bcm]) {
      const dev = pinout.devices.find(d => Number(d.pins?.signal) === bcm);
      if (dev) await setupDeviceOnHardware(dev);
    }
    await fetch(apiUrl("/api/gpio/write"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bcm, value: currentVal ? 0 : 1 }),
    });
  };

  const toggleProbe = async (bcm: number, probing: boolean) => {
    const ep = probing ? "/api/gpio/probe/stop" : "/api/gpio/probe/start";
    await fetch(apiUrl(ep), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bcm, rate_hz: 50 }),
    });
  };

  const ensurePinProbing = async (bcm: number) => {
    if (!probingBcms.has(bcm)) {
      await fetch(apiUrl("/api/gpio/probe/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bcm, rate_hz: 50 }),
      });
    }
  };

  const removeDevice = async (devId: string) => {
    const dev = pinout.devices.find(d => d.id === devId);
    if (dev) {
      const signalPin = Number(dev.pins?.signal);
      if (!isNaN(signalPin) && !dev.reserved) {
        await fetch(apiUrl(`/api/gpio/cleanup/${signalPin}`), { method: "POST" });
      }
    }
    const next = { ...pinout, devices: pinout.devices.filter(d => d.id !== devId) };
    await save(next);
  };

  // ── Plot Pane Controls ──────────────────────────────────────────
  const addPlotPane = () => {
    const num = plotPanes.length + 1;
    setPlotPanes(prev => [
      ...prev,
      {
        id: `plot_${Date.now()}`,
        title: `Plot ${num}`,
        bcms: [],
        paused: false,
        timeWindowSec: 10,
        autoScale: true,
        minVal: 0,
        maxVal: 1,
        zoomOffsetSec: 0,
      },
    ]);
  };

  const removePlotPane = (id: string) => {
    if (plotPanes.length <= 1) return;
    setPlotPanes(prev => prev.filter(p => p.id !== id));
  };

  const updatePlotPane = (id: string, patch: Partial<PlotPane>) => {
    setPlotPanes(prev => prev.map(p => (p.id === id ? { ...p, ...patch } : p)));
  };

  const addBcmToPlot = (paneId: string, bcm: number) => {
    updatePlotPane(paneId, {
      bcms: Array.from(new Set([...(plotPanes.find(p => p.id === paneId)?.bcms || []), bcm])),
    });
    ensurePinProbing(bcm);
  };

  const removeBcmFromPlot = (paneId: string, bcm: number) => {
    const pane = plotPanes.find(p => p.id === paneId);
    if (!pane) return;
    updatePlotPane(paneId, { bcms: pane.bcms.filter(b => b !== bcm) });
  };

  // ── Pin rendering helper ───────────────────────────────────────
  const renderPin = (p: BoardPin) => {
    const isUsed = p.bcm != null && usedBcms.has(p.bcm);
    const isProbing = p.bcm != null && probingBcms.has(p.bcm);
    const gs = p.bcm != null ? gpioMap[p.bcm] : undefined;
    const isHigh = gs?.value === 1;
    const isLeft = p.phys % 2 === 1;

    let cls = `pin-dot ${p.type}`;
    if (isUsed) cls += " used";
    if (isProbing) cls += " probing";
    if (isHigh) cls += " high";
    if (p.bcm === selectedBcm) cls += " selected";

    return (
      <div
        key={p.phys}
        className={`pin-row ${isLeft ? "" : "pin-row-right"}`}
        draggable={p.bcm != null}
        onDragStart={(e) => {
          if (p.bcm != null) {
            e.dataTransfer.setData("text/plain", String(p.bcm));
          }
        }}
        onClick={() => p.bcm != null && setSelectedBcm(p.bcm)}
      >
        {isLeft ? (
          <>
            <span className="pin-label">{p.name}{p.bcm != null ? ` (${p.bcm})` : ""}</span>
            <span className="pin-num">{p.phys}</span>
            <span className={cls} title={`Phys ${p.phys}${p.bcm != null ? ` / BCM ${p.bcm}` : ""} — Drag into plot to graph`} />
          </>
        ) : (
          <>
            <span className={cls} title={`Phys ${p.phys}${p.bcm != null ? ` / BCM ${p.bcm}` : ""} — Drag into plot to graph`} />
            <span className="pin-num">{p.phys}</span>
            <span className="pin-label">{p.name}{p.bcm != null ? ` (${p.bcm})` : ""}</span>
          </>
        )}
      </div>
    );
  };

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div className={`page gpio-main-wrapper layout-${layoutPos}`}>
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Board Pins — Signal Workbench</span>
          <div className="layout-toggles">
            <button className={`btn ${showLogs ? "primary" : ""}`} onClick={() => setShowLogs(!showLogs)}>
              Logs
            </button>
            <button className={`btn ${showGraph ? "primary" : ""}`} onClick={() => setShowGraph(!showGraph)}>
              Graph
            </button>
            <select className="btn" value={layoutPos} onChange={e => setLayoutPos(e.target.value as "bottom" | "right")}>
              <option value="bottom">Bottom Layout</option>
              <option value="right">Right Layout</option>
            </select>
          </div>
        </div>
        <div className="btn-row">
          <span className={`badge ${gpioRunning ? "" : "badge-off"}`}>
            {gpioRunning ? "GPIO Active" : "GPIO Offline"}
          </span>
          {gpioMock && gpioRunning && (
            <span
              className="badge badge-warn"
              title="RPi.GPIO is not installed — pin writes are simulated only and will NOT affect real hardware"
              style={{ cursor: "help" }}
            >
              ⚠ Mock Mode
            </span>
          )}
          <select className="btn" value={pinout.board} onChange={e => save({ ...pinout, board: e.target.value })}>
            {boards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <button className="btn" onClick={() => setShowAddModal(true)}>+ Add Device</button>
          <button className="btn primary" onClick={() => save(pinout)}>Save Config</button>
        </div>
      </div>

      <div className="gpio-flex-content">
        {/* Top half: board visual + device cards */}
        <div className="gpio-layout">
          {/* Left: Interactive 40-pin header */}
          <div className="panel gpio-board-panel">
            <div className="gpio-board-title">{board?.name || "Board"} (Drag pin to graph)</div>
            <div className="gpio-header">
              <div className="gpio-col">{left.map(renderPin)}</div>
              <div className="gpio-notch">▼</div>
              <div className="gpio-col">{right.map(renderPin)}</div>
            </div>
            <div className="gpio-legend">
              <span><span className="pin-dot power" style={{ display: "inline-block", width: 10, height: 10 }} /> Power</span>
              <span><span className="pin-dot gnd" style={{ display: "inline-block", width: 10, height: 10 }} /> GND</span>
              <span><span className="pin-dot gpio" style={{ display: "inline-block", width: 10, height: 10 }} /> GPIO</span>
              <span><span className="pin-dot used" style={{ display: "inline-block", width: 10, height: 10 }} /> In Use</span>
              <span><span className="pin-dot probing" style={{ display: "inline-block", width: 10, height: 10 }} /> Probing</span>
            </div>
          </div>

          {/* Right: Device cards */}
          <div className="panel gpio-devices-panel">
            <div className="gpio-devices-scroll">
              {(pinout.devices || []).length === 0 && (
                <div className="placeholder">No devices configured. Click "+ Add Device" to start.</div>
              )}
              {(pinout.devices || []).map(dev => {
                const signalPin = Number(dev.pins?.signal);
                const gs = !isNaN(signalPin) ? gpioMap[signalPin] : undefined;
                const isOutput = dev.mode === "OUT";
                const isReserved = dev.reserved;

                return (
                  <div
                    key={dev.id}
                    className={`device-card ${isReserved ? "reserved" : ""}`}
                    draggable={!isNaN(signalPin)}
                    onDragStart={(e) => {
                      if (!isNaN(signalPin)) {
                        e.dataTransfer.setData("text/plain", String(signalPin));
                      }
                    }}
                  >
                    <div className="device-header">
                      <span className="device-icon">{deviceIcon(dev.type)}</span>
                      <div className="device-info">
                        <strong>{dev.label || dev.id}</strong>
                        <span className="muted">{dev.type} — {Object.entries(dev.pins || {}).map(([k, v]) => `${k}:${v}`).join(", ")}</span>
                      </div>
                      {!isReserved && (
                        <button className="btn danger" style={{ padding: "2px 8px", fontSize: 11 }}
                          onClick={() => removeDevice(dev.id)}>✕</button>
                      )}
                    </div>

                    {isReserved ? (
                      <div className="device-reserved">Reserved — {dev.mode}</div>
                    ) : isOutput && gs ? (
                      <div className="device-controls">
                        <button
                          className={`toggle-switch ${gs.value ? "on" : ""}`}
                          onClick={() => togglePin(signalPin, gs.value)}
                        >
                          <span className="toggle-knob" />
                        </button>
                        <span className={`value-badge ${gs.value ? "high" : "low"}`}>
                          {gs.value ? "HIGH" : "LOW"}
                        </span>
                        <button
                          className="btn"
                          style={{ fontSize: 11, padding: "2px 6px" }}
                          onClick={() => addBcmToPlot(plotPanes[0].id, signalPin)}
                        >
                          + Graph
                        </button>
                      </div>
                    ) : !isOutput && !isReserved ? (
                      <div className="device-controls">
                        <span className={`value-badge ${gs?.value ? "high" : "low"}`}>
                          {gs ? (gs.value ? "HIGH" : "LOW") : "—"}
                        </span>
                        <button
                          className={`btn ${gs?.probing ? "danger" : "primary"}`}
                          style={{ fontSize: 12, padding: "3px 10px" }}
                          onClick={() => !isNaN(signalPin) && toggleProbe(signalPin, !!gs?.probing)}
                        >
                          {gs?.probing ? "■ Stop Probe" : "▶ Probe"}
                        </button>
                        <button
                          className="btn"
                          style={{ fontSize: 11, padding: "2px 6px" }}
                          onClick={() => !isNaN(signalPin) && addBcmToPlot(plotPanes[0].id, signalPin)}
                        >
                          + Graph
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Main Panel Resizer */}
        {(showLogs || showGraph) && (
          <div 
            className={`resize-handle-main ${layoutPos}`} 
            onMouseDown={startResizePanel}
          />
        )}

        {/* Panels Area: Logs + Signal Graph */}
        {(showLogs || showGraph) && (
          <div 
            className={`gpio-panels-container ${layoutPos}`}
            style={{ [layoutPos === "bottom" ? "height" : "width"]: panelSize }}
          >
            {showLogs && (
              <div className="panel gpio-log-panel" style={{ flex: showGraph ? `${splitRatio}` : '1' }}>
                <div className="gpio-section-title">GPIO Log</div>
                <div className="gpio-log-scroll">
                  {logs.length === 0 && <div className="placeholder" style={{ padding: 12 }}>No log entries yet</div>}
                  {logs.map((l, i) => <div key={i} className="gpio-log-line">{l}</div>)}
                  <div ref={logsEndRef} />
                </div>
              </div>
            )}

            {showLogs && showGraph && (
              <div className={`resize-handle-split ${layoutPos}`} onMouseDown={startResizeSplit} />
            )}

            {showGraph && (
              <div className="panel gpio-graph-panel" style={{ flex: showLogs ? `${100 - splitRatio}` : '1' }}>
                {plotPanes.map((pane) => (
                  <PlotPaneView
                    key={pane.id}
                    pane={pane}
                    probeBuf={probeBuf}
                    gpioMap={gpioMap}
                    canClose={plotPanes.length > 1}
                    onUpdate={(patch) => updatePlotPane(pane.id, patch)}
                    onClose={() => removePlotPane(pane.id)}
                    onAddPane={addPlotPane}
                    onAddBcm={(bcm) => addBcmToPlot(pane.id, bcm)}
                    onRemoveBcm={(bcm) => removeBcmFromPlot(pane.id, bcm)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Add Device Modal */}
      {showAddModal && (
        <AddDeviceModal
          onAdd={async (dev) => {
            const next = { ...pinout, devices: [...(pinout.devices || []), dev] };
            await save(next);
            await setupDeviceOnHardware(dev);
          }}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  );
}

/* ── Interactive Plot Pane Component ───────────────────────────── */

function PlotPaneView({
  pane,
  probeBuf,
  gpioMap,
  canClose,
  onUpdate,
  onClose,
  onAddPane,
  onAddBcm,
  onRemoveBcm,
}: {
  pane: PlotPane;
  probeBuf: React.MutableRefObject<Record<number, ProbeSample[]>>;
  gpioMap: Record<number, PinApiState>;
  canClose: boolean;
  onUpdate: (patch: Partial<PlotPane>) => void;
  onClose: () => void;
  onAddPane: () => void;
  onAddBcm: (bcm: number) => void;
  onRemoveBcm: (bcm: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [hoverInfo, setHoverInfo] = useState<{ x: number; y: number; ts: number; values: Record<number, number> } | null>(null);
  const isDraggingTime = useRef(false);
  const dragStartX = useRef(0);
  const dragStartOffset = useRef(0);

  // Active BCMS: explicitly added to pane, or if none added, automatically show probing pins
  const activeBcms = useMemo(() => {
    if (pane.bcms.length > 0) return pane.bcms;
    const buf = probeBuf.current;
    return Object.keys(buf).map(Number).filter(b => buf[b]?.length > 0);
  }, [pane.bcms, probeBuf]);

  // Canvas render loop
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

      const paddingLeft = 45;
      const paddingRight = 15;
      const paddingTop = 15;
      const paddingBottom = 32;
      const graphW = W - paddingLeft - paddingRight;
      const graphH = H - paddingTop - paddingBottom;

      // Draw grid background
      ctx.strokeStyle = "#161d28";
      ctx.lineWidth = 1;

      // Horizontal scale grid
      const yTicks = 4;
      for (let i = 0; i <= yTicks; i++) {
        const y = paddingTop + (i / yTicks) * graphH;
        ctx.beginPath();
        ctx.moveTo(paddingLeft, y);
        ctx.lineTo(W - paddingRight, y);
        ctx.stroke();

        // Y-axis value labels
        ctx.fillStyle = "#586579";
        ctx.font = "10px IBM Plex Mono, monospace";
        ctx.textAlign = "right";
        const val = pane.autoScale
          ? (1 - i / yTicks).toFixed(1)
          : (pane.maxVal - (i / yTicks) * (pane.maxVal - pane.minVal)).toFixed(1);
        ctx.fillText(String(val), paddingLeft - 6, y + 3);
      }

      // Vertical time grid (10 columns)
      const xTicks = 10;
      const now = Date.now() / 1000;
      const effNow = pane.paused ? now - pane.zoomOffsetSec : now;

      for (let i = 0; i <= xTicks; i++) {
        const x = paddingLeft + (i / xTicks) * graphW;
        ctx.beginPath();
        ctx.moveTo(x, paddingTop);
        ctx.lineTo(x, H - paddingBottom);
        ctx.stroke();

        // Dual Timestamps on X-Axis
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

      // If no active signals
      if (activeBcms.length === 0) {
        ctx.fillStyle = "#8b98ad";
        ctx.font = "12px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Drag & drop pins here or start probing to graph signal", W / 2, H / 2);
      }

      // Draw Waveforms
      const buf = probeBuf.current;
      const numLanes = activeBcms.length;
      const laneH = numLanes > 1 ? graphH / numLanes : graphH;

      activeBcms.forEach((bcm, idx) => {
        const samples = buf[bcm] || [];
        const color = TRACE_COLORS[idx % TRACE_COLORS.length];
        const yTop = paddingTop + idx * laneH;
        const currentH = numLanes > 1 ? laneH - 6 : laneH;

        // Draw waveform path
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
          let normY = s.value;
          if (!pane.autoScale && pane.maxVal !== pane.minVal) {
            normY = (s.value - pane.minVal) / (pane.maxVal - pane.minVal);
          }
          normY = Math.max(0, Math.min(1, normY));

          const y = numLanes > 1
            ? yTop + currentH - normY * currentH * 0.75 - currentH * 0.12
            : paddingTop + graphH - normY * graphH * 0.85 - graphH * 0.07;

          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.stroke();

        // Draw data points
        ctx.fillStyle = color;
        for (const s of samples) {
          const ageSec = effNow - s.ts;
          if (ageSec < 0 || ageSec > pane.timeWindowSec + pane.zoomOffsetSec) continue;
          const normX = 1 - (ageSec - pane.zoomOffsetSec) / pane.timeWindowSec;
          if (normX < 0 || normX > 1) continue;
          const x = paddingLeft + normX * graphW;
          let normY = s.value;
          if (!pane.autoScale && pane.maxVal !== pane.minVal) {
            normY = (s.value - pane.minVal) / (pane.maxVal - pane.minVal);
          }
          normY = Math.max(0, Math.min(1, normY));
          const y = numLanes > 1
            ? yTop + currentH - normY * currentH * 0.75 - currentH * 0.12
            : paddingTop + graphH - normY * graphH * 0.85 - graphH * 0.07;
          ctx.beginPath();
          ctx.arc(x, y, 2.5, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      // Draw hover crosshair cursor if active
      if (hoverInfo && hoverInfo.x >= paddingLeft && hoverInfo.x <= W - paddingRight) {
        ctx.strokeStyle = "#5b9cff";
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hoverInfo.x, paddingTop);
        ctx.lineTo(hoverInfo.x, H - paddingBottom);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (!pane.paused) raf = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(raf);
  }, [pane, activeBcms, probeBuf, hoverInfo]);

  // Drop Handlers
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const bcmStr = e.dataTransfer.getData("text/plain");
    const bcm = Number(bcmStr);
    if (!isNaN(bcm)) {
      onAddBcm(bcm);
    }
  };

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
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (isDraggingTime.current) {
      const dx = e.clientX - dragStartX.current;
      const secShift = (dx / rect.width) * pane.timeWindowSec;
      onUpdate({ zoomOffsetSec: Math.max(0, dragStartOffset.current - secShift) });
    }

    setHoverInfo({ x, y, ts: Date.now(), values: {} });
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
            title={pane.paused ? "Play real-time stream" : "Pause stream"}
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
          <button
            className="plot-toolbar-btn"
            onClick={onAddPane}
            title="Add another Plot Pane"
          >
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

      {/* Main Body: Canvas + Trace Controls Sidebar */}
      <div className="plot-body">
        <div
          className={`gpio-canvas-wrapper ${isDragOver ? "drag-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => { isDraggingTime.current = false; setHoverInfo(null); }}
        >
          <canvas ref={canvasRef} className="gpio-canvas" />
        </div>

        {/* Trace Legend & Scale Controls Sidebar */}
        <div className="plot-sidebar">
          <div className="plot-sidebar-section">
            <div className="plot-sidebar-title">Mapped Pin Traces</div>
            {activeBcms.length === 0 && (
              <div className="muted" style={{ fontStyle: "italic", fontSize: 10 }}>
                No pins mapped. Drag pins here or click "+ Graph" on a device card.
              </div>
            )}
            {activeBcms.map((bcm, idx) => {
              const color = TRACE_COLORS[idx % TRACE_COLORS.length];
              const gs = gpioMap[bcm];
              return (
                <div key={bcm} className="plot-trace-badge">
                  <div className="plot-trace-info">
                    <span className="plot-trace-dot" style={{ background: color }} />
                    <strong>BCM {bcm}</strong>
                  </div>
                  <span className="plot-trace-val" style={{ color }}>
                    {gs ? (gs.value ? "HIGH (1)" : "LOW (0)") : "—"}
                  </span>
                  {pane.bcms.includes(bcm) && (
                    <button
                      className="btn danger"
                      style={{ padding: "0 4px", fontSize: 10, lineHeight: "14px" }}
                      onClick={() => onRemoveBcm(bcm)}
                      title="Remove pin trace"
                    >
                      ✕
                    </button>
                  )}
                </div>
              );
            })}
          </div>

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
                  <span className="muted" style={{ fontSize: 9 }}>Min:</span>
                  <input
                    type="number"
                    className="plot-scale-input"
                    value={pane.minVal}
                    onChange={(e) => onUpdate({ minVal: Number(e.target.value) })}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <span className="muted" style={{ fontSize: 9 }}>Max:</span>
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

/* ── Add Device Modal ─────────────────────────────────────────── */

function AddDeviceModal({ onAdd, onClose }: {
  onAdd: (dev: Device) => Promise<void>;
  onClose: () => void;
}) {
  const [id, setId] = useState("new_sensor");
  const [label, setLabel] = useState("New Sensor");
  const [type, setType] = useState("digital_input");
  const [bcm, setBcm] = useState(17);
  const [mode, setMode] = useState("IN");
  const [pull, setPull] = useState("UP");

  const add = async () => {
    const dev: Device = {
      id,
      type,
      label,
      pins: { signal: bcm },
      mode,
      enabled: true,
    };
    if (mode === "IN") {
      dev.pull = pull;
      dev.probe = true;
      dev.probe_rate_hz = 50;
    }
    if (type === "led" || type === "actuator") dev.default_value = 0;
    await onAdd(dev);
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>Add GPIO Device</h3>
        <div className="field">
          <span>Device ID</span>
          <input value={id} onChange={e => setId(e.target.value)} />
        </div>
        <div className="field">
          <span>Label</span>
          <input value={label} onChange={e => setLabel(e.target.value)} />
        </div>
        <div className="field">
          <span>Type</span>
          <select value={type} onChange={e => { setType(e.target.value); setMode(e.target.value === "digital_input" ? "IN" : "OUT"); }}>
            <option value="led">LED</option>
            <option value="digital_input">Digital Input</option>
            <option value="pwm">PWM / Actuator</option>
          </select>
        </div>
        <div className="field">
          <span>BCM Pin</span>
          <input type="number" value={bcm} onChange={e => setBcm(Number(e.target.value))} />
        </div>
        <div className="field">
          <span>Direction</span>
          <select value={mode} onChange={e => setMode(e.target.value)}>
            <option value="OUT">Output</option>
            <option value="IN">Input</option>
          </select>
        </div>
        {mode === "IN" && (
          <div className="field">
            <span>Pull</span>
            <select value={pull} onChange={e => setPull(e.target.value)}>
              <option value="NONE">None</option>
              <option value="UP">Pull-Up</option>
              <option value="DOWN">Pull-Down</option>
            </select>
          </div>
        )}
        <div className="btn-row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={add}>Add &amp; Save</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
