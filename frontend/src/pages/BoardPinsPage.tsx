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

/* ── Helpers ───────────────────────────────────────────────────── */

const DEVICE_ICONS: Record<string, string> = {
  led: "💡",
  digital_input: "📥",
  pwm: "🎛️",
  actuator: "🎛️",
  i2c_sensor: "📡",
  i2s_audio: "🔊",
};

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

  // Layout State
  const [showLogs, setShowLogs] = useState(true);
  const [showGraph, setShowGraph] = useState(true);
  const [layoutPos, setLayoutPos] = useState<"bottom" | "right">("bottom");
  const [panelSize, setPanelSize] = useState(250);
  const [splitRatio, setSplitRatio] = useState(50);

  // Resize Handlers
  const startResizePanel = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startSize = panelSize;
    const startPos = layoutPos === "bottom" ? e.clientY : e.clientX;
    const onMove = (ev: MouseEvent) => {
      if (layoutPos === "bottom") {
        const delta = startPos - ev.clientY; // moving mouse up increases size
        setPanelSize(Math.max(100, Math.min(startSize + delta, window.innerHeight - 200)));
      } else {
        const delta = startPos - ev.clientX; // moving mouse left increases size
        setPanelSize(Math.max(200, Math.min(startSize + delta, window.innerWidth - 350)));
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
    const isRow = layoutPos === "bottom"; // side-by-side
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
  const canvasRef = useRef<HTMLCanvasElement>(null);
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
          // Keep last 500 samples per pin
          if (buf[sample.bcm].length > 500) buf[sample.bcm] = buf[sample.bcm].slice(-500);
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

  // ── Draw signal graph ──────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let raf = 0;
    const draw = () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      const W = rect.width, H = rect.height;

      ctx.fillStyle = "#0e1116";
      ctx.fillRect(0, 0, W, H);

      // Grid lines
      ctx.strokeStyle = "#1a2130";
      ctx.lineWidth = 1;
      for (let y = 0; y < H; y += H / 4) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      for (let x = 0; x < W; x += W / 10) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }

      const colors = ["#3dd68c", "#5b9cff", "#f0c14a", "#ff6b6b", "#c084fc", "#fb923c"];
      const buf = probeBuf.current;
      const probingPins = Object.keys(buf).map(Number).filter(b => buf[b].length > 0);
      const now = Date.now() / 1000;
      const windowSec = 10;

      if (probingPins.length === 0) {
        ctx.fillStyle = "#8b98ad";
        ctx.font = "13px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Enable probe on an input pin to see its signal", W / 2, H / 2);
      }

      const laneH = probingPins.length > 0 ? (H - 20) / probingPins.length : H;

      probingPins.forEach((bcm, i) => {
        const samples = buf[bcm];
        if (!samples.length) return;
        const color = colors[i % colors.length];
        const yBase = 10 + i * laneH;
        const yH = laneH - 4;

        // Label
        ctx.fillStyle = color;
        ctx.font = "11px system-ui";
        ctx.textAlign = "left";
        ctx.fillText(`BCM${bcm}`, 4, yBase + 12);

        // Draw digital waveform
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        let started = false;
        for (const s of samples) {
          const age = now - s.ts;
          if (age > windowSec) continue;
          const x = W - (age / windowSec) * W;
          const y = yBase + yH - (s.value ? yH * 0.8 : yH * 0.15);
          if (!started) { ctx.moveTo(x, y); started = true; }
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

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

  /** Set up a device pin on the live GPIO service so it works immediately. */
  const setupDeviceOnHardware = async (dev: Device) => {
    const signalPin = Number(dev.pins?.signal);
    if (isNaN(signalPin) || dev.reserved) return;

    // Setup the pin direction + pull
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

    // For output pins, set default value
    if (dev.mode === "OUT") {
      await fetch(apiUrl("/api/gpio/write"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bcm: signalPin, value: dev.default_value || 0 }),
      });
    }

    // For input pins with probe enabled, auto-start probing
    if (dev.mode === "IN" && dev.probe) {
      await fetch(apiUrl("/api/gpio/probe/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bcm: signalPin, rate_hz: dev.probe_rate_hz || 50 }),
      });
    }
  };

  const togglePin = async (bcm: number, currentVal: number) => {
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

  const removeDevice = async (devId: string) => {
    // Clean up the pin from the live GPIO service
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
        onClick={() => p.bcm != null && setSelectedBcm(p.bcm)}
      >
        {isLeft ? (
          <>
            <span className="pin-label">{p.name}{p.bcm != null ? ` (${p.bcm})` : ""}</span>
            <span className="pin-num">{p.phys}</span>
            <span className={cls} title={`Phys ${p.phys}${p.bcm != null ? ` / BCM ${p.bcm}` : ""}${p.alt ? ` — ${p.alt.join(", ")}` : ""}`} />
          </>
        ) : (
          <>
            <span className={cls} title={`Phys ${p.phys}${p.bcm != null ? ` / BCM ${p.bcm}` : ""}${p.alt ? ` — ${p.alt.join(", ")}` : ""}`} />
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
          <span>Board Pins — Live GPIO</span>
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
          <div className="gpio-board-title">{board?.name || "Board"}</div>
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
                <div key={dev.id} className={`device-card ${isReserved ? "reserved" : ""}`}>
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
                    </div>
                  ) : !isReserved ? (
                    <div className="device-controls">
                      <span className="muted">Start gpio.pins node to control</span>
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
              <div className="gpio-section-title">Signal Graph (10s window)</div>
              <canvas ref={canvasRef} className="gpio-canvas" />
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
