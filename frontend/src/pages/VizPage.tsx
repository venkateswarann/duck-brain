import { useEffect, useMemo, useRef, useState } from "react";
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
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [mode, setMode] = useState<"3d" | "urdf">("3d");
  const [urdfXml, setUrdfXml] = useState<string>("");
  const [loadingUrdf, setLoadingUrdf] = useState<boolean>(true);
  const [showJointsTable, setShowJointsTable] = useState<boolean>(true);
  const [showCameraPip, setShowCameraPip] = useState<boolean>(true);

  const motors = (snapshot?.motors || {}) as Record<string, JointData>;

  // Fetch URDF XML file from backend
  useEffect(() => {
    fetch(apiUrl("/api/robot/urdf"))
      .then((res) => (res.ok ? res.text() : ""))
      .then((xml) => {
        if (xml) setUrdfXml(xml);
      })
      .catch(() => {})
      .finally(() => setLoadingUrdf(false));
  }, []);

  // Three.js 3D Canvas Scene Initialization & Render Loop
  useEffect(() => {
    if (!canvasRef.current) return;

    let animationFrameId: number;
    let scene: any;
    let camera: any;
    let renderer: any;
    let robotGroup: any;

    // Joint object references in 3D scene
    const jointNodes: Record<string, any> = {};

    const loadThree = () => {
      // Check if THREE is available or load script dynamically
      if (typeof (window as any).THREE === "undefined") {
        const script = document.createElement("script");
        script.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
        script.onload = () => init3D();
        document.body.appendChild(script);
      } else {
        init3D();
      }
    };

    const init3D = () => {
      const THREE = (window as any).THREE;
      if (!THREE || !canvasRef.current) return;

      const width = canvasRef.current.parentElement?.clientWidth || 600;
      const height = canvasRef.current.parentElement?.clientHeight || 500;

      // 1. Scene & Camera
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0d121a);

      camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      camera.position.set(0.6, 0.4, 0.8);
      camera.lookAt(0, 0.15, 0);

      // 2. Renderer
      renderer = new THREE.WebGLRenderer({
        canvas: canvasRef.current,
        antialias: true,
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = true;

      // 3. Lighting
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
      scene.add(ambientLight);

      const dirLight = new THREE.DirectionalLight(0x3dd68c, 0.8);
      dirLight.position.set(2, 4, 2);
      scene.add(dirLight);

      const backLight = new THREE.DirectionalLight(0x5b9cff, 0.5);
      backLight.position.set(-2, 2, -2);
      scene.add(backLight);

      // 4. Grid Floor
      const grid = new THREE.GridHelper(2, 20, 0x3dd68c, 0x1f2937);
      grid.position.y = -0.15;
      scene.add(grid);

      // 5. Robot 3D Assembly Hierarchy
      robotGroup = new THREE.Group();

      // Materials
      const matTorso = new THREE.MeshStandardMaterial({ color: 0x3dd68c, metalness: 0.3, roughness: 0.4 });
      const matJoint = new THREE.MeshStandardMaterial({ color: 0x5b9cff, metalness: 0.5, roughness: 0.3 });
      const matLegLeft = new THREE.MeshStandardMaterial({ color: 0x3dd68c, metalness: 0.2, roughness: 0.5 });
      const matLegRight = new THREE.MeshStandardMaterial({ color: 0xff6b6b, metalness: 0.2, roughness: 0.5 });
      const matHead = new THREE.MeshStandardMaterial({ color: 0xf0c14a, metalness: 0.4, roughness: 0.3 });

      // Trunk Body
      const torsoGeo = new THREE.BoxGeometry(0.12, 0.16, 0.1);
      const torso = new THREE.Mesh(torsoGeo, matTorso);
      torso.position.y = 0.15;
      robotGroup.add(torso);

      // Neck & Head
      const neckGroup = new THREE.Group();
      neckGroup.position.set(0, 0.1, 0.02);
      torso.add(neckGroup);
      jointNodes["neck_pitch"] = neckGroup;

      const headGroup = new THREE.Group();
      headGroup.position.set(0, 0.05, 0);
      neckGroup.add(headGroup);
      jointNodes["head_pitch"] = headGroup;

      const headMesh = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 16), matHead);
      headGroup.add(headMesh);
      // Beak
      const beak = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.06, 8), matHead);
      beak.rotation.x = Math.PI / 2;
      beak.position.set(0, -0.01, 0.05);
      headGroup.add(beak);

      // --- LEFT LEG ---
      const lHipYaw = new THREE.Group();
      lHipYaw.position.set(0.05, -0.08, 0);
      torso.add(lHipYaw);
      jointNodes["left_hip_yaw"] = lHipYaw;

      const lHipRoll = new THREE.Group();
      lHipYaw.add(lHipRoll);
      jointNodes["left_hip_roll"] = lHipRoll;

      const lHipPitch = new THREE.Group();
      lHipRoll.add(lHipPitch);
      jointNodes["left_hip_pitch"] = lHipPitch;

      const lThigh = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.1), matLegLeft);
      lThigh.position.y = -0.05;
      lHipPitch.add(lThigh);

      const lKnee = new THREE.Group();
      lKnee.position.y = -0.1;
      lHipPitch.add(lKnee);
      jointNodes["left_knee"] = lKnee;

      const lShin = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.1), matLegLeft);
      lShin.position.y = -0.05;
      lKnee.add(lShin);

      const lAnkle = new THREE.Group();
      lAnkle.position.y = -0.1;
      lKnee.add(lAnkle);
      jointNodes["left_ankle"] = lAnkle;

      const lFoot = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.01, 0.06), matLegLeft);
      lFoot.position.set(0, -0.005, 0.015);
      lAnkle.add(lFoot);

      // --- RIGHT LEG ---
      const rHipYaw = new THREE.Group();
      rHipYaw.position.set(-0.05, -0.08, 0);
      torso.add(rHipYaw);
      jointNodes["right_hip_yaw"] = rHipYaw;

      const rHipRoll = new THREE.Group();
      rHipYaw.add(rHipRoll);
      jointNodes["right_hip_roll"] = rHipRoll;

      const rHipPitch = new THREE.Group();
      rHipRoll.add(rHipPitch);
      jointNodes["right_hip_pitch"] = rHipPitch;

      const rThigh = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.1), matLegRight);
      rThigh.position.y = -0.05;
      rHipPitch.add(rThigh);

      const rKnee = new THREE.Group();
      rKnee.position.y = -0.1;
      rHipPitch.add(rKnee);
      jointNodes["right_knee"] = rKnee;

      const rShin = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.1), matLegRight);
      rShin.position.y = -0.05;
      rKnee.add(rShin);

      const rAnkle = new THREE.Group();
      rAnkle.position.y = -0.1;
      rKnee.add(rAnkle);
      jointNodes["right_ankle"] = rAnkle;

      const rFoot = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.01, 0.06), matLegRight);
      rFoot.position.set(0, -0.005, 0.015);
      rAnkle.add(rFoot);

      scene.add(robotGroup);

      // Interactive Mouse Orbit Rotation
      let isDragging = false;
      let previousMousePosition = { x: 0, y: 0 };

      const onMouseDown = (e: MouseEvent) => {
        isDragging = true;
        previousMousePosition = { x: e.clientX, y: e.clientY };
      };

      const onMouseMove = (e: MouseEvent) => {
        if (!isDragging || !robotGroup) return;
        const deltaX = e.clientX - previousMousePosition.x;
        const deltaY = e.clientY - previousMousePosition.y;

        robotGroup.rotation.y += deltaX * 0.01;
        robotGroup.rotation.x += deltaY * 0.01;

        previousMousePosition = { x: e.clientX, y: e.clientY };
      };

      const onMouseUp = () => {
        isDragging = false;
      };

      const canvas = canvasRef.current;
      if (canvas) {
        canvas.addEventListener("mousedown", onMouseDown);
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
      }

      // Render Loop
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);

        // Update joint angles from telemetry
        Object.entries(jointNodes).forEach(([name, node]) => {
          const val = motors[name]?.position ?? 0;
          if (name.includes("pitch")) {
            node.rotation.x = val;
          } else if (name.includes("roll")) {
            node.rotation.z = val;
          } else if (name.includes("yaw")) {
            node.rotation.y = val;
          } else if (name.includes("knee")) {
            node.rotation.x = val;
          } else if (name.includes("ankle")) {
            node.rotation.x = val;
          }
        });

        renderer.render(scene, camera);
      };

      animate();
    };

    loadThree();

    return () => {
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
    };
  }, [motors]);

  // Group joints into sections
  const { headJoints, leftLegJoints, rightLegJoints } = useMemo(() => {
    const head: [string, JointData][] = [];
    const left: [string, JointData][] = [];
    const right: [string, JointData][] = [];

    Object.entries(motors).forEach(([name, m]) => {
      if (name.startsWith("head_") || name.startsWith("neck_")) {
        head.push([name, m]);
      } else if (name.startsWith("left_")) {
        left.push([name, m]);
      } else if (name.startsWith("right_")) {
        right.push([name, m]);
      }
    });

    return { headJoints: head, leftLegJoints: left, rightLegJoints: right };
  }, [motors]);

  const activeJointsCount = Object.values(motors).filter((m) => m.online !== false).length;
  const totalJointsCount = Object.keys(motors).length;

  return (
    <div className="page">
      {/* Title Bar */}
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Open Duck Mini — 3D Robot URDF Visualizer</span>
          <span className="badge">
            {totalJointsCount > 0 ? `${activeJointsCount}/${totalJointsCount} Servos Active` : "Telemetry Standby"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className={`btn ${mode === "3d" ? "primary" : ""}`}
            onClick={() => setMode("3d")}
          >
            3D WebGL View
          </button>
          <button
            className={`btn ${mode === "urdf" ? "primary" : ""}`}
            onClick={() => setMode("urdf")}
          >
            URDF Structure ({urdfXml ? "assets/robot.urdf" : "Loading…"})
          </button>
        </div>
      </div>

      <div className="split split-tree">
        {/* Left Panel — Joint State & Controls */}
        <div className="panel" style={{ padding: 14 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: "var(--accent)" }}>
            Overlay Controls
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            <label style={{ display: "flex", justifyContent: "space-between", fontSize: 13, cursor: "pointer" }}>
              <span>Joint Values List</span>
              <input type="checkbox" checked={showJointsTable} onChange={(e) => setShowJointsTable(e.target.checked)} />
            </label>
            <label style={{ display: "flex", justifyContent: "space-between", fontSize: 13, cursor: "pointer" }}>
              <span>Camera Stream PIP</span>
              <input type="checkbox" checked={showCameraPip} onChange={(e) => setShowCameraPip(e.target.checked)} />
            </label>
          </div>

          <hr style={{ borderColor: "var(--border)", margin: "12px 0" }} />

          {showJointsTable && (
            <div>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: "var(--accent)" }}>
                3D Joint Angle State
              </div>

              {/* Head Section */}
              <div style={{ marginBottom: 12 }}>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                  Head &amp; Neck ({headJoints.length})
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
            </div>
          )}
        </div>

        {/* Right Panel — 3D WebGL Viewport or URDF File Tree */}
        <div
          className="panel"
          style={{
            position: "relative",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "#090d14",
            overflow: "hidden",
          }}
        >
          {mode === "3d" ? (
            <div style={{ width: "100%", height: "100%", position: "relative" }}>
              {/* 3D WebGL Canvas */}
              <canvas
                ref={canvasRef}
                style={{ width: "100%", height: "100%", display: "block", cursor: "grab" }}
              />

              {/* Controls Instruction Overlay */}
              <div
                style={{
                  position: "absolute",
                  bottom: 16,
                  left: 16,
                  background: "rgba(13, 18, 26, 0.8)",
                  backdropFilter: "blur(6px)",
                  padding: "8px 14px",
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  fontSize: 11,
                  color: "var(--muted)",
                }}
              >
                🖱️ Drag mouse to rotate 3D view · Scroll to zoom
              </div>

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
          ) : (
            <div style={{ width: "100%", height: "100%", padding: 16, overflowY: "auto" }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8, color: "var(--accent)" }}>
                assets/robot.urdf Source XML
              </div>
              <pre
                className="log-view"
                style={{
                  background: "#05080d",
                  padding: 16,
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  maxHeight: "calc(100vh - 180px)",
                }}
              >
                {loadingUrdf ? "Loading URDF definition from server…" : urdfXml || "No URDF file found."}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Sub-component for individual joint rows
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
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
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
