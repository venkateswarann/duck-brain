import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTelemetry } from "../hooks/useTelemetry";
import { apiUrl } from "../config";
import { RobotScene, type JointInfo, type SceneStats, type ViewPreset } from "../viz/RobotScene";

interface JointData {
  id: number;
  name: string;
  position: number;
  temperature_c?: number;
  voltage_v?: number;
  online?: boolean;
}

interface RobotModel {
  robot_name: string;
  root_link: string;
  links: string[];
  movable_joints: string[];
  actuated_joints: string[];
  mesh_count: number;
  missing_meshes: string[];
}

type PoseSource = "telemetry" | "manual";

const VIEWS: { id: ViewPreset; label: string }[] = [
  { id: "iso", label: "Iso" },
  { id: "front", label: "Front" },
  { id: "side", label: "Side" },
  { id: "top", label: "Top" },
];

export default function VizPage() {
  const { snapshot } = useTelemetry();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<RobotScene | null>(null);

  const [tab, setTab] = useState<"3d" | "urdf">("3d");
  const [status, setStatus] = useState("Loading robot description…");
  const [error, setError] = useState("");
  const [joints, setJoints] = useState<JointInfo[]>([]);
  const [stats, setStats] = useState<SceneStats | null>(null);
  const [model, setModel] = useState<RobotModel | null>(null);
  const [urdfXml, setUrdfXml] = useState("");

  const [poseSource, setPoseSource] = useState<PoseSource>("telemetry");
  const [manualPose, setManualPose] = useState<Record<string, number>>({});
  const [showVisual, setShowVisual] = useState(true);
  const [showCollision, setShowCollision] = useState(false);
  const [wireframe, setWireframe] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [showFrames, setShowFrames] = useState(false);
  const [showCameraPip, setShowCameraPip] = useState(true);

  const motors = (snapshot?.motors || {}) as Record<string, JointData>;

  useEffect(() => {
    fetch(apiUrl("/api/robot/model"))
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => m && setModel(m))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (tab !== "urdf" || urdfXml) return;
    fetch(apiUrl("/api/robot/urdf"))
      .then((r) => (r.ok ? r.text() : ""))
      .then(setUrdfXml)
      .catch(() => {});
  }, [tab, urdfXml]);

  // Build the scene once the 3D tab is mounted.
  useEffect(() => {
    if (tab !== "3d" || !canvasRef.current) return;

    setStatus("Loading robot description…");
    setError("");

    const scene = new RobotScene({
      canvas: canvasRef.current,
      urdfUrl: apiUrl("/api/robot/urdf"),
      assetBase: apiUrl("/api/robot/assets"),
      onProgress: (loaded, total) => setStatus(`Loading meshes ${loaded}/${total}…`),
      onReady: (jointInfo, sceneStats) => {
        setJoints(jointInfo);
        setStats(sceneStats);
        setStatus(`Assembled · ${sceneStats.meshes} meshes · ${(sceneStats.height * 100).toFixed(1)} cm tall`);
        setManualPose((prev) => {
          if (Object.keys(prev).length) return prev;
          return Object.fromEntries(jointInfo.map((j) => [j.name, 0]));
        });
      },
      onError: (message) => setError(message),
    });
    sceneRef.current = scene;

    return () => {
      scene.dispose();
      sceneRef.current = null;
    };
  }, [tab]);

  // Push display options through to the scene.
  useEffect(() => sceneRef.current?.setShowVisual(showVisual), [showVisual, joints]);
  useEffect(() => sceneRef.current?.setShowCollision(showCollision), [showCollision, joints]);
  useEffect(() => sceneRef.current?.setWireframe(wireframe), [wireframe, joints]);
  useEffect(() => sceneRef.current?.setShowGrid(showGrid), [showGrid, joints]);
  useEffect(() => sceneRef.current?.setShowJointFrames(showFrames), [showFrames, joints]);

  // Drive the model: either live servo feedback or the manual sliders.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !joints.length) return;

    if (poseSource === "telemetry") {
      const values: Record<string, number> = {};
      Object.entries(motors).forEach(([name, m]) => {
        if (typeof m.position === "number") values[name] = m.position;
      });
      scene.setJointValues(values);
    } else {
      scene.setJointValues(manualPose);
    }
  }, [motors, manualPose, poseSource, joints]);

  // Refresh the FPS/triangle readout without re-rendering on every frame.
  useEffect(() => {
    const timer = setInterval(() => {
      const scene = sceneRef.current;
      if (scene) setStats(scene.getStats());
    }, 1000);
    return () => clearInterval(timer);
  }, [tab]);

  const setJoint = useCallback((name: string, value: number) => {
    setPoseSource("manual");
    setManualPose((prev) => ({ ...prev, [name]: value }));
  }, []);

  const resetPose = useCallback(() => {
    setManualPose(Object.fromEntries(joints.map((j) => [j.name, 0])));
    setPoseSource("manual");
  }, [joints]);

  const actuated = useMemo(() => new Set(model?.actuated_joints || []), [model]);

  const groups = useMemo(() => {
    const make = (test: (n: string) => boolean) => joints.filter((j) => test(j.name));
    return [
      { title: "Head & Neck", items: make((n) => n.startsWith("head_") || n.startsWith("neck_")) },
      { title: "Left Leg", items: make((n) => n.startsWith("left_hip") || n === "left_knee" || n === "left_ankle") },
      { title: "Right Leg", items: make((n) => n.startsWith("right_hip") || n === "right_knee" || n === "right_ankle") },
      { title: "Antennae", items: make((n) => n.includes("antenna")) },
    ].filter((g) => g.items.length > 0);
  }, [joints]);

  const liveValues = useMemo(() => {
    const out: Record<string, number> = {};
    Object.entries(motors).forEach(([name, m]) => {
      if (typeof m.position === "number") out[name] = m.position;
    });
    return out;
  }, [motors]);

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span>{model?.robot_name ? `Open Duck Mini — ${model.robot_name}` : "Open Duck Mini — 3D Model"}</span>
          <span className="badge">{status}</span>
          {error && <span className="badge" style={{ color: "var(--danger)" }}>{error}</span>}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className={`btn ${tab === "3d" ? "primary" : ""}`} onClick={() => setTab("3d")}>
            3D Viewer
          </button>
          <button className={`btn ${tab === "urdf" ? "primary" : ""}`} onClick={() => setTab("urdf")}>
            URDF Source
          </button>
        </div>
      </div>

      <div className="split split-tree">
        <div className="panel" style={{ padding: 14, overflowY: "auto" }}>
          <SectionTitle>Pose source</SectionTitle>
          <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
            <button
              className={`btn ${poseSource === "telemetry" ? "primary" : ""}`}
              style={{ flex: 1 }}
              onClick={() => setPoseSource("telemetry")}
            >
              Live telemetry
            </button>
            <button
              className={`btn ${poseSource === "manual" ? "primary" : ""}`}
              style={{ flex: 1 }}
              onClick={() => setPoseSource("manual")}
            >
              Manual
            </button>
          </div>
          {poseSource === "manual" && (
            <button className="btn" style={{ width: "100%", marginBottom: 12 }} onClick={resetPose}>
              Reset to zero pose
            </button>
          )}

          <SectionTitle>Display</SectionTitle>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
            <Toggle label="Visual geometry" checked={showVisual} onChange={setShowVisual} />
            <Toggle label="Collision geometry" checked={showCollision} onChange={setShowCollision} />
            <Toggle label="Wireframe" checked={wireframe} onChange={setWireframe} />
            <Toggle label="Grid & world axes" checked={showGrid} onChange={setShowGrid} />
            <Toggle label="Joint frames" checked={showFrames} onChange={setShowFrames} />
            <Toggle label="Camera PIP" checked={showCameraPip} onChange={setShowCameraPip} />
          </div>

          <SectionTitle>Joints ({joints.length})</SectionTitle>
          {!joints.length && <div className="muted" style={{ fontSize: 12 }}>Waiting for the model…</div>}
          {groups.map((group) => (
            <div key={group.title} style={{ marginBottom: 12 }}>
              <div
                className="muted"
                style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", marginBottom: 6 }}
              >
                {group.title} ({group.items.length})
              </div>
              {group.items.map((joint) => (
                <JointSlider
                  key={joint.name}
                  joint={joint}
                  driven={actuated.has(joint.name)}
                  live={poseSource === "telemetry"}
                  value={poseSource === "telemetry" ? liveValues[joint.name] ?? 0 : manualPose[joint.name] ?? 0}
                  onChange={(v) => setJoint(joint.name, v)}
                />
              ))}
            </div>
          ))}
        </div>

        <div
          className="panel"
          style={{ position: "relative", background: "#0b1018", overflow: "hidden", padding: 0 }}
        >
          {tab === "3d" ? (
            <div style={{ width: "100%", height: "100%", position: "relative" }}>
              <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />

              <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 6 }}>
                {VIEWS.map((v) => (
                  <button key={v.id} className="btn" onClick={() => sceneRef.current?.setView(v.id)}>
                    {v.label}
                  </button>
                ))}
              </div>

              {stats && (
                <div style={overlayStyle("top-right")}>
                  <div>{stats.fps} fps</div>
                  <div>{stats.meshes} meshes</div>
                  <div>{stats.triangles.toLocaleString()} tris</div>
                  <div>{(stats.height * 100).toFixed(1)} cm tall</div>
                </div>
              )}

              <div style={overlayStyle("bottom-left")}>
                Left-drag orbit · right-drag pan · scroll zoom · Z-up world
              </div>

              {model?.missing_meshes?.length ? (
                <div style={{ ...overlayStyle("bottom-right"), color: "var(--danger)", maxWidth: 320 }}>
                  {model.missing_meshes.length} mesh(es) missing from assets/. Run
                  <code> python3 scripts/check_robot_assets.py</code>
                </div>
              ) : null}

              {showCameraPip && snapshot?.video?.running && (
                <div
                  style={{
                    position: "absolute",
                    bottom: 12,
                    right: 12,
                    width: 190,
                    borderRadius: 8,
                    overflow: "hidden",
                    border: "1px solid var(--border)",
                    background: "#000",
                  }}
                >
                  <div style={{ padding: "2px 8px", fontSize: 10, color: "var(--accent)", fontWeight: 600 }}>
                    LIVE CAMERA
                  </div>
                  <img
                    src={apiUrl("/stream/camera")}
                    alt="camera"
                    style={{ width: "100%", height: 110, objectFit: "cover", display: "block" }}
                  />
                </div>
              )}
            </div>
          ) : (
            <div style={{ width: "100%", height: "100%", padding: 16, overflowY: "auto" }}>
              <div style={{ display: "flex", gap: 16, marginBottom: 10, flexWrap: "wrap" }}>
                <Stat label="Links" value={model?.links?.length ?? "—"} />
                <Stat label="Movable joints" value={model?.movable_joints?.length ?? "—"} />
                <Stat label="Driven by servos" value={model?.actuated_joints?.length ?? "—"} />
                <Stat label="Meshes" value={model?.mesh_count ?? "—"} />
                <Stat label="Root link" value={model?.root_link ?? "—"} />
              </div>
              <pre
                className="log-view"
                style={{
                  background: "#05080d",
                  padding: 16,
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  maxHeight: "calc(100vh - 220px)",
                }}
              >
                {urdfXml || "Loading assets/robot.urdf…"}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: "var(--accent)" }}>{children}</div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label style={{ display: "flex", justifyContent: "space-between", fontSize: 13, cursor: "pointer" }}>
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 11, textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ fontWeight: 600, fontSize: 15 }}>{value}</div>
    </div>
  );
}

function JointSlider({
  joint,
  value,
  driven,
  live,
  onChange,
}: {
  joint: JointInfo;
  value: number;
  driven: boolean;
  live: boolean;
  onChange: (v: number) => void;
}) {
  const deg = (value * 180) / Math.PI;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            title={driven ? "Driven by a servo" : "No servo mapped — pose manually"}
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: driven ? "var(--accent)" : "var(--muted)",
            }}
          />
          <span style={{ fontFamily: "monospace" }}>{joint.name}</span>
        </span>
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>{deg.toFixed(1)}°</span>
      </div>
      <input
        type="range"
        min={joint.lower}
        max={joint.upper}
        step={0.005}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: live ? "var(--muted)" : "var(--accent)" }}
      />
    </div>
  );
}

function overlayStyle(corner: "top-right" | "bottom-left" | "bottom-right"): React.CSSProperties {
  const base: React.CSSProperties = {
    position: "absolute",
    background: "rgba(11, 16, 24, 0.82)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    padding: "6px 10px",
    fontSize: 11,
    color: "var(--muted)",
    lineHeight: 1.5,
  };
  if (corner === "top-right") return { ...base, top: 12, right: 12, textAlign: "right" };
  if (corner === "bottom-left") return { ...base, bottom: 12, left: 12 };
  return { ...base, bottom: 12, right: 12 };
}
