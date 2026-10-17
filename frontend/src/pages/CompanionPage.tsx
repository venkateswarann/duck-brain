import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../config";
import { useTelemetry } from "../hooks/useTelemetry";

type Result = { ok?: boolean; clamped?: boolean; reasons?: string[]; detail?: string; command?: string };

async function call(path: string, body?: unknown, method = "POST"): Promise<Result> {
  try {
    const r = await fetch(apiUrl(path), {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    return r.ok ? data : { ok: false, detail: data.detail ?? `HTTP ${r.status}` };
  } catch (e) {
    return { ok: false, detail: String(e) };
  }
}

function Dot({ on, label, detail }: { on: boolean | null | undefined; label: string; detail?: string }) {
  const cls = on ? "badge" : on === false ? "badge badge-off" : "badge badge-warn";
  return (
    <span className={cls} title={detail}>
      {label}
      {detail ? <span className="muted"> {detail}</span> : null}
    </span>
  );
}

export default function CompanionPage() {
  const { snapshot } = useTelemetry();
  const companion = (snapshot as any)?.companion ?? {};
  const head = companion.head ?? {};
  const eyes = companion.eyes ?? {};
  const audio = companion.audio ?? {};
  const ears = companion.ears ?? {};
  const lamp = companion.lamp ?? {};

  const [status, setStatus] = useState<any>({});
  const [expressions, setExpressions] = useState<string[]>([]);
  const [last, setLast] = useState<Result | null>(null);
  const [previewTick, setPreviewTick] = useState(0);
  const [pose, setPose] = useState({ yaw: 0, pitch: 0, roll: 0 });
  const [sayText, setSayText] = useState("");
  const [earPose, setEarPose] = useState({ left: 0, right: 0 });
  const earTimer = useRef<number | undefined>(undefined);
  const poseTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const load = () => {
      fetch(apiUrl("/api/companion/status")).then((r) => r.json()).then(setStatus).catch(() => undefined);
    };
    load();
    const t = window.setInterval(load, 2000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (!eyes.online || expressions.length) return;
    fetch(apiUrl("/api/eyes/expressions"))
      .then((r) => (r.ok ? r.json() : []))
      .then(setExpressions)
      .catch(() => undefined);
  }, [eyes.online, expressions.length]);

  useEffect(() => {
    const t = window.setInterval(() => setPreviewTick((n) => n + 1), 250);
    return () => window.clearInterval(t);
  }, []);

  const run = async (path: string, body?: unknown) => setLast(await call(path, body));

  const sendPose = (next: typeof pose) => {
    setPose(next);
    window.clearTimeout(poseTimer.current);
    // Trailing debounce keeps slider drags under the head's command rate limit.
    poseTimer.current = window.setTimeout(
      () => run("/api/head/look_at", { yaw: next.yaw, pitch: next.pitch, roll: next.roll }),
      90,
    );
  };

  const sendEars = (next: typeof earPose) => {
    setEarPose(next);
    window.clearTimeout(earTimer.current);
    earTimer.current = window.setTimeout(() => run("/api/ears/set", next), 60);
  };

  const onGaze = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * 2 - 1;
    const y = ((e.clientY - r.top) / r.height) * 2 - 1;
    run("/api/eyes/look", { x: +x.toFixed(2), y: +y.toFixed(2), hold_s: 5 });
  };

  const limits = head.limits ?? {};
  const slider = (key: "yaw" | "pitch" | "roll", joint: string) => {
    const lim = limits[joint] ?? { min_deg: -60, max_deg: 60 };
    return (
      <label style={{ display: "block", marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>{key}</span>
          <span className="muted">
            {pose[key]}° (now {head.present_deg?.[joint] ?? "–"}°)
          </span>
        </div>
        <input
          type="range"
          min={lim.min_deg - 20}
          max={lim.max_deg + 20}
          value={pose[key]}
          onChange={(e) => sendPose({ ...pose, [key]: Number(e.target.value) })}
          style={{ width: "100%" }}
        />
        <div className="muted" style={{ fontSize: 11 }}>
          safe {lim.min_deg}..{lim.max_deg}° (slider goes past it on purpose, to show clamping)
        </div>
      </label>
    );
  };

  const events: any[] = head.recent_events ?? [];

  return (
    <div className="page">
      <div className="page-title">
        <span>Duck / Companion</span>
        <span className="btn-row">
          <Dot on={status.servos?.ok} label="head" detail={head.mock ? "mock" : `${status.servos?.found ?? 0}/4`} />
          <Dot on={eyes.online} label="eyes" detail={eyes.url ?? "offline"} />
          <Dot on={status.ears?.ok} label="ears" detail={status.ears?.driver ?? undefined} />
          <Dot on={status.lamp?.ok} label="lamp" detail={lamp.on ? "on" : undefined} />
          <Dot on={audio.mic} label="mic" />
          <Dot on={audio.speaker} label="speaker" detail={audio.speaking ? "talking" : undefined} />
          <Dot on={status.camera?.live} label="camera" />
          <Dot on={status.brain?.online} label="brain" detail={status.brain?.detail} />
        </span>
      </div>

      <div style={{ padding: 16, display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", overflow: "auto" }}>
        <section className="card" style={card}>
          <h3 style={h3}>Eyes</h3>
          {eyes.online ? (
            <div
              onClick={onGaze}
              title="Click to look there"
              style={{ cursor: "crosshair", background: "#000", borderRadius: 8, padding: 8 }}
            >
              <img
                src={apiUrl(`/api/eyes/preview?t=${previewTick}`)}
                alt="eye preview"
                style={{ width: "100%", display: "block" }}
              />
            </div>
          ) : (
            <div className="muted">Eyes service offline (head Pi Zero, port 8100).</div>
          )}
          <div className="muted" style={{ margin: "6px 0" }}>
            {eyes.state?.expression ?? "–"} · click the eyes to steer the gaze
          </div>
          <div className="btn-row">
            {expressions.map((name) => (
              <button
                key={name}
                className={`btn${eyes.state?.expression === name ? " primary" : ""}`}
                onClick={() => run("/api/eyes/expression", { name })}
              >
                {name}
              </button>
            ))}
            <button className="btn" onClick={() => run("/api/eyes/blink")}>blink</button>
          </div>
        </section>

        <section className="card" style={card}>
          <h3 style={h3}>Head</h3>
          {slider("yaw", "head_yaw")}
          {slider("pitch", "head_pitch")}
          {slider("roll", "head_roll")}
          <div className="btn-row" style={{ marginBottom: 12 }}>
            <button className="btn" onClick={() => run("/api/head/nod", { times: 2 })}>nod</button>
            <button className="btn" onClick={() => run("/api/head/shake", { times: 2 })}>shake</button>
            <button className="btn" onClick={() => run("/api/head/tilt", { angle: 15 })}>tilt</button>
            <button className="btn" onClick={() => run("/api/head/nod", { times: 10 })} title="asks for 10, capped at 3">
              nod ×10
            </button>
            <button
              className="btn"
              onClick={() => {
                setPose({ yaw: 0, pitch: 0, roll: 0 });
                run("/api/head/center");
              }}
            >
              center
            </button>
            <button
              className={`btn${head.idle_motion?.enabled ? " primary" : ""}`}
              onClick={() => run("/api/head/idle_motion", { enabled: !head.idle_motion?.enabled })}
              title="gentle breathing and sway layered on the head pose"
            >
              breathing {head.idle_motion?.enabled ? "on" : "off"}
            </button>
          </div>
          <button
            className="btn"
            onClick={() => run("/api/estop")}
            style={{ width: "100%", padding: 14, fontSize: 18, fontWeight: 700, background: "#5a1d1d", borderColor: "var(--danger)", color: "#fff" }}
          >
            STOP
          </button>
          {last && (
            <div style={{ marginTop: 10, fontSize: 12 }} className={last.ok === false ? "" : "muted"}>
              <span style={{ color: last.ok === false ? "var(--danger)" : last.clamped ? "var(--warn)" : "var(--accent)" }}>
                {last.ok === false ? "rejected" : last.clamped ? "clamped" : "ok"}
              </span>{" "}
              {last.command ?? ""} {(last.reasons ?? []).join("; ")} {last.detail ?? ""}
            </div>
          )}
        </section>

        <section className="card" style={card}>
          <h3 style={{ ...h3, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ flex: 1 }}>Ears &amp; lamp</span>
            {(["left", "right"] as const).map((side) => {
              const on = ears.enabled?.[side] !== false;
              return (
                <button
                  key={side}
                  className={`btn${on ? " primary" : ""}`}
                  style={{ fontSize: 11, padding: "2px 8px" }}
                  title={on ? `${side} ear on; click to switch it off (silent, never driven)` : `${side} ear off; click to switch it on`}
                  onClick={() => run("/api/ears/enable", { enabled: !on, side })}
                >
                  {side} {on ? "on" : "off"}
                </button>
              );
            })}
            {(() => {
              const anyOn = ears.enabled ? Object.values(ears.enabled).some(Boolean) : true;
              return (
                <button
                  className="btn"
                  style={{ fontSize: 11, padding: "2px 8px" }}
                  onClick={() => run("/api/ears/enable", { enabled: !anyOn })}
                >
                  {anyOn ? "ears off" : "ears on"}
                </button>
              );
            })()}
          </h3>
          {(["left", "right"] as const).map((side) => (
            <label key={side} style={{ display: "block", marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span>{side} ear</span>
                <span className="muted">
                  {earPose[side].toFixed(2)} (now {ears.position?.[side] ?? "–"})
                </span>
              </div>
              <input
                type="range"
                min={-1}
                max={1}
                step={0.05}
                value={earPose[side]}
                onChange={(e) => sendEars({ ...earPose, [side]: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
            </label>
          ))}
          <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
            -1 back/down · 0 neutral · +1 up/forward (clamped to ±{ears.limit ?? 0.9}) · driver {ears.driver ?? "–"}
            {ears.active === false ? " · not driven yet" : ""}
          </div>
          <div className="btn-row" style={{ marginBottom: 12 }}>
            {["wiggle", "perk", "droop", "flick_left", "flick_right", "alert"].map((g) => (
              <button key={g} className="btn" onClick={() => run("/api/ears/gesture", { name: g, times: 2 })}>
                {g.replace("_", " ")}
              </button>
            ))}
            <button
              className={`btn${ears.idle ? " primary" : ""}`}
              onClick={() => run("/api/ears/idle", { enabled: !ears.idle })}
              title="occasional ear twitches"
            >
              twitch {ears.idle ? "on" : "off"}
            </button>
            <button className="btn" onClick={() => run("/api/ears/release")} title="stop the servo pulses">
              release
            </button>
          </div>
          <div className="btn-row" style={{ alignItems: "center" }}>
            <button
              className={`btn${lamp.on ? " primary" : ""}`}
              onClick={() => run("/api/lamp/set", { on: !lamp.on })}
            >
              lamp {lamp.on ? "on" : "off"}
            </button>
            <button className="btn" onClick={() => run("/api/lamp/blink", { times: 3 })}>blink</button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={lamp.brightness ?? 0}
              onChange={(e) => run("/api/lamp/set", { brightness: Number(e.target.value) })}
              style={{ flex: 1 }}
              title="brightness"
            />
          </div>
          {lamp.error && <div style={{ color: "var(--danger)", fontSize: 12 }}>lamp: {lamp.error}</div>}
          {(ears.errors ?? []).map((e: string) => (
            <div key={e} style={{ color: "var(--warn)", fontSize: 12 }}>{e}</div>
          ))}
        </section>

        <section className="card" style={card}>
          <h3 style={h3}>Head camera</h3>
          {status.camera?.live ? (
            <img src={apiUrl(`/stream/video/${status.camera.stream}`)} alt="head camera" style={{ width: "100%", borderRadius: 8 }} />
          ) : (
            <div className="muted">No frames on “{status.camera?.stream ?? "head_cam"}” yet (duck-headcam on the Zero).</div>
          )}
          <form
            style={{ display: "flex", gap: 8, marginTop: 12 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (sayText.trim()) run("/api/speech/say", { text: sayText });
              setSayText("");
            }}
          >
            <input
              value={sayText}
              onChange={(e) => setSayText(e.target.value)}
              placeholder="Make the duck say…"
              style={{ flex: 1, padding: 8, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 6 }}
            />
            <button className="btn" type="submit">say</button>
          </form>
        </section>

        <section className="card" style={card}>
          <h3 style={h3}>Safety events</h3>
          {events.length === 0 && <div className="muted">No clamps or rejections yet.</div>}
          {events
            .slice()
            .reverse()
            .map((ev, i) => (
              <div key={i} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
                <span style={{ color: ev.kind === "reject" ? "var(--danger)" : "var(--warn)" }}>{ev.kind}</span>{" "}
                <span className="muted">{new Date(ev.ts * 1000).toLocaleTimeString()}</span> {ev.command}:{" "}
                {(ev.reasons ?? []).join("; ")}
              </div>
            ))}
        </section>
      </div>
    </div>
  );
}

const card: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  padding: 14,
  minWidth: 0,
};
const h3: React.CSSProperties = { margin: "0 0 10px", fontSize: 14 };
