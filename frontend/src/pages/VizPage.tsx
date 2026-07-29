import { useMemo, useState } from "react";
import { useTelemetry } from "../hooks/useTelemetry";
import { apiUrl } from "../config";

interface JointData {
  id: number;
  name: string;
  position: number;
  position_raw?: number;
  temperature_c?: number;
  voltage_v?: number;
  online?: boolean;
}

export default function VizPage() {
  const { snapshot } = useTelemetry();
  const [showSkeleton, setShowSkeleton] = useState(true);
  const [showJointsTable, setShowJointsTable] = useState(true);
  const [showCameraPip, setShowCameraPip] = useState(true);

  const motors = (snapshot?.motors || {}) as Record<string, JointData>;

  // Group joints into Head, Left Leg, Right Leg
  const { headJoints, leftLegJoints, rightLegJoints, otherJoints } = useMemo(() => {
    const head: [string, JointData][] = [];
    const left: [string, JointData][] = [];
    const right: [string, JointData][] = [];
    const other: [string, JointData][] = [];

    Object.entries(motors).forEach(([name, m]) => {
      if (name.startsWith("head_") || name.startsWith("neck_")) {
        head.push([name, m]);
      } else if (name.startsWith("left_")) {
        left.push([name, m]);
      } else if (name.startsWith("right_")) {
        right.push([name, m]);
      } else {
        other.push([name, m]);
      }
    });

    return {
      headJoints: head,
      leftLegJoints: left,
      rightLegJoints: right,
      otherJoints: other,
    };
  }, [motors]);

  // Helper to safely get joint angle in radians
  const getPos = (name: string): number => motors[name]?.position ?? 0;

  // Compute 2D skeleton joint positions based on forward kinematics
  const neckPitch = getPos("neck_pitch");
  const headPitch = getPos("head_pitch");
  const leftHipPitch = getPos("left_hip_pitch");
  const leftKnee = getPos("left_knee");
  const leftAnkle = getPos("left_ankle");
  const rightHipPitch = getPos("right_hip_pitch");
  const rightKnee = getPos("right_knee");
  const rightAnkle = getPos("right_ankle");

  // Kinematic calculations for 2D side-view rendering (angles in radians)
  const l1 = 65; // Thigh length
  const l2 = 65; // Shin length
  const l3 = 25; // Foot length

  // Right leg coordinates (offset slightly)
  const rHipX = 190;
  const rHipY = 220;
  const rKneeAngle = rHipY + Math.cos(rightHipPitch) * l1;
  const rKneeX = rHipX + Math.sin(rightHipPitch) * l1;
  const rKneeY = rKneeAngle;
  const rAnkleAngle = rightHipPitch + rightKnee;
  const rAnkleX = rKneeX + Math.sin(rAnkleAngle) * l2;
  const rAnkleY = rKneeY + Math.cos(rAnkleAngle) * l2;
  const rFootAngle = rAnkleAngle + rightAnkle;
  const rFootX = rAnkleX + Math.cos(rFootAngle) * l3;
  const rFootY = rAnkleY + Math.sin(rFootAngle) * l3;

  // Left leg coordinates
  const lHipX = 210;
  const lHipY = 220;
  const lKneeAngle = lHipY + Math.cos(leftHipPitch) * l1;
  const lKneeX = lHipX + Math.sin(leftHipPitch) * l1;
  const lKneeY = lKneeAngle;
  const lAnkleAngle = leftHipPitch + leftKnee;
  const lAnkleX = lKneeX + Math.sin(lAnkleAngle) * l2;
  const lAnkleY = lKneeY + Math.cos(lAnkleAngle) * l2;
  const lFootAngle = lAnkleAngle + leftAnkle;
  const lFootX = lAnkleX + Math.cos(lFootAngle) * l3;
  const lFootY = lAnkleY + Math.sin(lFootAngle) * l3;

  // Head coordinates
  const headBaseX = 200;
  const headBaseY = 140;
  const headAngle = neckPitch + headPitch;
  const headX = headBaseX + Math.sin(headAngle) * 35;
  const headY = headBaseY - Math.cos(headAngle) * 35;

  const activeJointsCount = Object.values(motors).filter((m) => m.online !== false).length;
  const totalJointsCount = Object.keys(motors).length;

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Robot Kinematics & Visualizer</span>
          <span className="badge">
            {totalJointsCount > 0 ? `${activeJointsCount}/${totalJointsCount} Servos Active` : "Telemetry Standby"}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--muted)" }}>
          Open Duck Mini Kinematic Pose
        </div>
      </div>

      <div className="split split-tree">
        {/* Left Sidebar Panel - Joint Status & Controls */}
        <div className="panel" style={{ padding: 14 }}>
          {/* Display Controls */}
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: "var(--accent)" }}>
            Layers & Overlay
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, cursor: "pointer" }}>
              <span>2D Kinematic Skeleton</span>
              <input type="checkbox" checked={showSkeleton} onChange={(e) => setShowSkeleton(e.target.checked)} />
            </label>
            <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, cursor: "pointer" }}>
              <span>Joint Values List</span>
              <input type="checkbox" checked={showJointsTable} onChange={(e) => setShowJointsTable(e.target.checked)} />
            </label>
            <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, cursor: "pointer" }}>
              <span>Camera Stream PIP</span>
              <input type="checkbox" checked={showCameraPip} onChange={(e) => setShowCameraPip(e.target.checked)} />
            </label>
          </div>

          <hr style={{ borderColor: "var(--border)", margin: "12px 0" }} />

          {/* Joint Telemetry Groups */}
          {showJointsTable && (
            <div>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: "var(--accent)" }}>
                Joint Telemetry
              </div>

              {/* Head Section */}
              <div style={{ marginBottom: 12 }}>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                  Head & Neck ({headJoints.length})
                </div>
                {headJoints.map(([name, m]) => (
                  <JointRow key={name} name={name} joint={m} />
                ))}
              </div>

              {/* Left Leg Section */}
              <div style={{ marginBottom: 12 }}>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                  Left Leg ({leftLegJoints.length})
                </div>
                {leftLegJoints.map(([name, m]) => (
                  <JointRow key={name} name={name} joint={m} />
                ))}
              </div>

              {/* Right Leg Section */}
              <div style={{ marginBottom: 12 }}>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                  Right Leg ({rightLegJoints.length})
                </div>
                {rightLegJoints.map(([name, m]) => (
                  <JointRow key={name} name={name} joint={m} />
                ))}
              </div>

              {otherJoints.length > 0 && (
                <div>
                  <div className="muted" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                    Other Servos ({otherJoints.length})
                  </div>
                  {otherJoints.map(([name, m]) => (
                    <JointRow key={name} name={name} joint={m} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Main Viewport Panel */}
        <div
          className="panel"
          style={{
            position: "relative",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "radial-gradient(circle at 50% 45%, #182232 0%, #0d121a 75%)",
            overflow: "hidden",
            padding: 16,
          }}
        >
          {/* Main SVG Vector Kinematic Skeleton Render */}
          {showSkeleton ? (
            <div style={{ position: "relative", width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg
                width="400"
                height="420"
                viewBox="0 0 400 420"
                style={{ filter: "drop-shadow(0 10px 25px rgba(0,0,0,0.5))" }}
              >
                <defs>
                  {/* Gradients */}
                  <linearGradient id="torsoGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3dd68c" stopOpacity="0.8" />
                    <stop offset="100%" stopColor="#1f8f5a" stopOpacity="0.9" />
                  </linearGradient>
                  <linearGradient id="headGrad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#5b9cff" />
                    <stop offset="100%" stopColor="#2b6cd4" />
                  </linearGradient>
                </defs>

                {/* Grid Floor */}
                <ellipse cx="200" cy="370" rx="140" ry="25" fill="none" stroke="#2a384e" strokeWidth="1.5" strokeDasharray="4 4" />
                <line x1="60" y1="370" x2="340" y2="370" stroke="#2a384e" strokeWidth="1" />

                {/* --- RIGHT LEG (Behind) --- */}
                <g opacity="0.6">
                  {/* Thigh */}
                  <line x1={rHipX} y1={rHipY} x2={rKneeX} y2={rKneeY} stroke="#ff6b6b" strokeWidth="8" strokeLinecap="round" />
                  {/* Shin */}
                  <line x1={rKneeX} y1={rKneeY} x2={rAnkleX} y2={rAnkleY} stroke="#ff6b6b" strokeWidth="6" strokeLinecap="round" />
                  {/* Foot */}
                  <line x1={rAnkleX} y1={rAnkleY} x2={rFootX} y2={rFootY} stroke="#ff8888" strokeWidth="4" strokeLinecap="round" />
                  {/* Joints */}
                  <circle cx={rHipX} cy={rHipY} r="5" fill="#ffffff" />
                  <circle cx={rKneeX} cy={rKneeY} r="4" fill="#ffffff" />
                  <circle cx={rAnkleX} cy={rAnkleY} r="3" fill="#ffffff" />
                </g>

                {/* --- TORSO BODY --- */}
                <rect x="160" y="140" width="80" height="85" rx="16" fill="url(#torsoGrad)" stroke="#51e6a2" strokeWidth="2" />
                <rect x="175" y="155" width="50" height="30" rx="6" fill="#121820" opacity="0.7" />
                <text x="200" y="174" fill="#3dd68c" fontSize="10" fontWeight="bold" textAnchor="middle">
                  DUCK MINI
                </text>

                {/* Torso Status LED */}
                <circle cx="200" cy="200" r="4" fill={activeJointsCount > 0 ? "#3dd68c" : "#ff6b6b"}>
                  <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite" />
                </circle>

                {/* --- NECK & HEAD --- */}
                <line x1={headBaseX} y1={headBaseY} x2={headX} y2={headY} stroke="#5b9cff" strokeWidth="7" strokeLinecap="round" />
                {/* Head Body */}
                <circle cx={headX} cy={headY} r="22" fill="url(#headGrad)" stroke="#7cb0ff" strokeWidth="2" />
                {/* Duck Beak / Nose */}
                <polygon points={`${headX + 18},${headY - 4} ${headX + 38},${headY + 2} ${headX + 18},${headY + 8}`} fill="#f0c14a" />
                {/* Eye */}
                <circle cx={headX + 8} cy={headY - 6} r="4" fill="#ffffff" />
                <circle cx={headX + 9} cy={headY - 6} r="2" fill="#0e1116" />

                {/* --- LEFT LEG (Foreground) --- */}
                <g>
                  {/* Thigh */}
                  <line x1={lHipX} y1={lHipY} x2={lKneeX} y2={lKneeY} stroke="#3dd68c" strokeWidth="8" strokeLinecap="round" />
                  {/* Shin */}
                  <line x1={lKneeX} y1={lKneeY} x2={lAnkleX} y2={lAnkleY} stroke="#3dd68c" strokeWidth="6" strokeLinecap="round" />
                  {/* Foot */}
                  <line x1={lAnkleX} y1={lAnkleY} x2={lFootX} y2={lFootY} stroke="#60eabb" strokeWidth="5" strokeLinecap="round" />
                  {/* Joints */}
                  <circle cx={lHipX} cy={lHipY} r="6" fill="#ffffff" stroke="#3dd68c" strokeWidth="2" />
                  <circle cx={lKneeX} cy={lKneeY} r="5" fill="#ffffff" stroke="#3dd68c" strokeWidth="2" />
                  <circle cx={lAnkleX} cy={lAnkleY} r="4" fill="#ffffff" stroke="#3dd68c" strokeWidth="2" />
                </g>
              </svg>

              {/* Legend overlay */}
              <div
                style={{
                  position: "absolute",
                  bottom: 16,
                  left: 16,
                  background: "rgba(14, 17, 22, 0.75)",
                  backdropFilter: "blur(6px)",
                  padding: "8px 14px",
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  fontSize: 11,
                  display: "flex",
                  gap: 16,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "#3dd68c" }} />
                  <span>Left Leg (Front)</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "#ff6b6b" }} />
                  <span>Right Leg (Back)</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "#5b9cff" }} />
                  <span>Head / Neck</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="muted" style={{ padding: 40, textAlign: "center" }}>
              Kinematic Skeleton Overlay Hidden
            </div>
          )}

          {/* Camera PIP Thumbnail Overlay */}
          {showCameraPip && snapshot?.video?.running && (
            <div
              style={{
                position: "absolute",
                top: 16,
                right: 16,
                width: 180,
                borderRadius: 8,
                overflow: "hidden",
                border: "2px solid var(--accent)",
                boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
                background: "#000",
              }}
            >
              <div style={{ background: "rgba(0,0,0,0.8)", padding: "2px 8px", fontSize: 10, color: "var(--accent)", fontWeight: 600 }}>
                LIVE CAMERA PIP
              </div>
              <img
                src={apiUrl("/stream/camera")}
                alt="pip"
                style={{ width: "100%", height: 110, objectFit: "cover", display: "block" }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Sub-component for individual joint rows in the left sidebar
function JointRow({ name, joint }: { name: string; joint: JointData }) {
  const rad = joint?.position ?? 0;
  const deg = (rad * (180 / Math.PI)).toFixed(1);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "4px 6px",
        fontSize: 12,
        borderRadius: 4,
        marginBottom: 2,
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.05)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, overflow: "hidden" }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: joint?.online !== false ? "var(--accent)" : "var(--danger)",
          }}
        />
        <span style={{ fontFamily: "monospace", color: "var(--text)" }}>{name}</span>
      </div>
      <div style={{ textAlign: "right" }}>
        <span style={{ fontWeight: 600, color: "var(--accent)" }}>{rad.toFixed(2)} rad</span>
        <span className="muted" style={{ fontSize: 10, marginLeft: 6 }}>({deg}°)</span>
      </div>
    </div>
  );
}
