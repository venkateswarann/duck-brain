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
  const [wireframe, setWireframe] = useState<boolean>(false);
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

  // Three.js 3D WebGL Realistic Open Duck Mini Renderer
  useEffect(() => {
    if (!canvasRef.current || mode !== "3d") return;

    let animationFrameId: number;
    let scene: any;
    let camera: any;
    let renderer: any;
    let duckGroup: any;

    const jointNodes: Record<string, any> = {};

    const loadThree = () => {
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

      const width = canvasRef.current.parentElement?.clientWidth || 700;
      const height = canvasRef.current.parentElement?.clientHeight || 550;

      // 1. Scene setup
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0a0e17);

      // 2. Camera setup
      camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      camera.position.set(0.6, 0.45, 0.85);
      camera.lookAt(0, 0.18, 0);

      // 3. WebGL Renderer
      renderer = new THREE.WebGLRenderer({
        canvas: canvasRef.current,
        antialias: true,
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;

      // 4. Lights
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
      scene.add(ambientLight);

      const mainLight = new THREE.DirectionalLight(0xffffff, 0.9);
      mainLight.position.set(2, 4, 3);
      mainLight.castShadow = true;
      scene.add(mainLight);

      const fillLight = new THREE.DirectionalLight(0x5b9cff, 0.4);
      fillLight.position.set(-3, 2, -2);
      scene.add(fillLight);

      const rimLight = new THREE.PointLight(0x3dd68c, 0.6, 5);
      rimLight.position.set(0, 0.8, -0.5);
      scene.add(rimLight);

      // 5. Grid Floor
      const grid = new THREE.GridHelper(3, 30, 0x3dd68c, 0x1e293b);
      grid.position.y = -0.22;
      scene.add(grid);

      // 6. Detailed 3D Open Duck Mini Model Assembly
      duckGroup = new THREE.Group();

      // Color Palette & Materials
      const matFeather = new THREE.MeshStandardMaterial({
        color: 0xf1f5f9,
        roughness: 0.3,
        metalness: 0.1,
        wireframe: wireframe,
      });
      const matBeak = new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        roughness: 0.2,
        metalness: 0.2,
        wireframe: wireframe,
      });
      const matJoints = new THREE.MeshStandardMaterial({
        color: 0x3dd68c,
        roughness: 0.4,
        metalness: 0.6,
        wireframe: wireframe,
      });
      const matServo = new THREE.MeshStandardMaterial({
        color: 0x1e293b,
        roughness: 0.5,
        metalness: 0.7,
        wireframe: wireframe,
      });
      const matLegLeft = new THREE.MeshStandardMaterial({
        color: 0x3dd68c,
        roughness: 0.4,
        metalness: 0.2,
        wireframe: wireframe,
      });
      const matLegRight = new THREE.MeshStandardMaterial({
        color: 0xef4444,
        roughness: 0.4,
        metalness: 0.2,
        wireframe: wireframe,
      });
      const matEye = new THREE.MeshBasicMaterial({ color: 0x0f172a });

      // --- DUCK TORSO (Trunk) ---
      const torsoGroup = new THREE.Group();
      torsoGroup.position.y = 0.18;
      duckGroup.add(torsoGroup);

      // Main Chest Body Shell
      const chestGeo = new THREE.CylinderGeometry(0.08, 0.065, 0.15, 16);
      const chestMesh = new THREE.Mesh(chestGeo, matFeather);
      chestMesh.castShadow = true;
      torsoGroup.add(chestMesh);

      // Back Shell
      const backGeo = new THREE.SphereGeometry(0.075, 16, 16);
      const backMesh = new THREE.Mesh(backGeo, matFeather);
      backMesh.position.set(0, 0.02, -0.03);
      backMesh.scale.set(1, 1, 1.3);
      torsoGroup.add(backMesh);

      // Chest Badge / Power Ring
      const ringGeo = new THREE.TorusGeometry(0.02, 0.003, 12, 24);
      const ringMesh = new THREE.Mesh(ringGeo, matJoints);
      ringMesh.position.set(0, 0.02, 0.082);
      torsoGroup.add(ringMesh);

      // --- NECK & HEAD ASSEMBLY ---
      const neckGroup = new THREE.Group();
      neckGroup.position.set(0, 0.09, 0.03);
      torsoGroup.add(neckGroup);
      jointNodes["neck_pitch"] = neckGroup;

      const headPitchGroup = new THREE.Group();
      headPitchGroup.position.set(0, 0.04, 0);
      neckGroup.add(headPitchGroup);
      jointNodes["head_pitch"] = headPitchGroup;

      const headYawGroup = new THREE.Group();
      headPitchGroup.add(headYawGroup);
      jointNodes["head_yaw"] = headYawGroup;

      const headRollGroup = new THREE.Group();
      headYawGroup.add(headRollGroup);
      jointNodes["head_roll"] = headRollGroup;

      // Duck Head Sphere
      const headGeo = new THREE.SphereGeometry(0.055, 24, 24);
      const headMesh = new THREE.Mesh(headGeo, matFeather);
      headMesh.castShadow = true;
      headRollGroup.add(headMesh);

      // Duck Bill / Beak
      const beakShape = new THREE.BoxGeometry(0.05, 0.018, 0.07);
      const beakMesh = new THREE.Mesh(beakShape, matBeak);
      beakMesh.position.set(0, -0.012, 0.065);
      beakMesh.rotation.x = 0.1;
      beakMesh.castShadow = true;
      headRollGroup.add(beakMesh);

      // Eyes
      const eyeGeo = new THREE.SphereGeometry(0.007, 12, 12);
      const eyeL = new THREE.Mesh(eyeGeo, matEye);
      eyeL.position.set(0.032, 0.015, 0.04);
      const eyeR = new THREE.Mesh(eyeGeo, matEye);
      eyeR.position.set(-0.032, 0.015, 0.04);
      headRollGroup.add(eyeL);
      headRollGroup.add(eyeR);

      // --- LEFT LEG (Green Accent) ---
      const lHipYaw = new THREE.Group();
      lHipYaw.position.set(0.045, -0.07, 0);
      torsoGroup.add(lHipYaw);
      jointNodes["left_hip_yaw"] = lHipYaw;

      const lHipRoll = new THREE.Group();
      lHipYaw.add(lHipRoll);
      jointNodes["left_hip_roll"] = lHipRoll;

      const lHipPitch = new THREE.Group();
      lHipRoll.add(lHipPitch);
      jointNodes["left_hip_pitch"] = lHipPitch;

      // Servo Housing
      const servoL = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.035, 0.04), matServo);
      lHipPitch.add(servoL);

      // Left Thigh
      const lThigh = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.012, 0.11, 12), matLegLeft);
      lThigh.position.y = -0.055;
      lThigh.castShadow = true;
      lHipPitch.add(lThigh);

      const lKnee = new THREE.Group();
      lKnee.position.y = -0.11;
      lHipPitch.add(lKnee);
      jointNodes["left_knee"] = lKnee;

      // Knee Joint Ring
      const lKneeJoint = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.025, 12), matJoints);
      lKneeJoint.rotation.z = Math.PI / 2;
      lKnee.add(lKneeJoint);

      // Left Shin
      const lShin = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.01, 0.11, 12), matLegLeft);
      lShin.position.y = -0.055;
      lShin.castShadow = true;
      lKnee.add(lShin);

      const lAnkle = new THREE.Group();
      lAnkle.position.y = -0.11;
      lKnee.add(lAnkle);
      jointNodes["left_ankle"] = lAnkle;

      // Webbed Duck Foot Left
      const lFoot = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.015, 3), matBeak);
      lFoot.rotation.x = -Math.PI / 2;
      lFoot.rotation.z = Math.PI;
      lFoot.position.set(0, -0.008, 0.025);
      lFoot.scale.set(1.2, 0.4, 1.8);
      lFoot.castShadow = true;
      lAnkle.add(lFoot);

      // --- RIGHT LEG (Red Accent) ---
      const rHipYaw = new THREE.Group();
      rHipYaw.position.set(-0.045, -0.07, 0);
      torsoGroup.add(rHipYaw);
      jointNodes["right_hip_yaw"] = rHipYaw;

      const rHipRoll = new THREE.Group();
      rHipYaw.add(rHipRoll);
      jointNodes["right_hip_roll"] = rHipRoll;

      const rHipPitch = new THREE.Group();
      rHipRoll.add(rHipPitch);
      jointNodes["right_hip_pitch"] = rHipPitch;

      // Servo Housing
      const servoR = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.035, 0.04), matServo);
      rHipPitch.add(servoR);

      // Right Thigh
      const rThigh = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.012, 0.11, 12), matLegRight);
      rThigh.position.y = -0.055;
      rThigh.castShadow = true;
      rHipPitch.add(rThigh);

      const rKnee = new THREE.Group();
      rKnee.position.y = -0.11;
      rHipPitch.add(rKnee);
      jointNodes["right_knee"] = rKnee;

      // Knee Joint Ring
      const rKneeJoint = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.025, 12), matJoints);
      rKneeJoint.rotation.z = Math.PI / 2;
      rKnee.add(rKneeJoint);

      // Right Shin
      const rShin = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.01, 0.11, 12), matLegRight);
      rShin.position.y = -0.055;
      rShin.castShadow = true;
      rKnee.add(rShin);

      const rAnkle = new THREE.Group();
      rAnkle.position.y = -0.11;
      rKnee.add(rAnkle);
      jointNodes["right_ankle"] = rAnkle;

      // Webbed Duck Foot Right
      const rFoot = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.015, 3), matBeak);
      rFoot.rotation.x = -Math.PI / 2;
      rFoot.rotation.z = Math.PI;
      rFoot.position.set(0, -0.008, 0.025);
      rFoot.scale.set(1.2, 0.4, 1.8);
      rFoot.castShadow = true;
      rAnkle.add(rFoot);

      scene.add(duckGroup);

      // 7. Interactive Mouse Orbit Controls
      let isDragging = false;
      let prevMousePos = { x: 0, y: 0 };

      const onMouseDown = (e: MouseEvent) => {
        isDragging = true;
        prevMousePos = { x: e.clientX, y: e.clientY };
      };

      const onMouseMove = (e: MouseEvent) => {
        if (!isDragging || !duckGroup) return;
        const dx = e.clientX - prevMousePos.x;
        const dy = e.clientY - prevMousePos.y;

        duckGroup.rotation.y += dx * 0.01;
        duckGroup.rotation.x += dy * 0.008;

        prevMousePos = { x: e.clientX, y: e.clientY };
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

      // 8. 60 FPS Render & Joint Sync Loop
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);

        // Dynamic joint rotations from WebSocket telemetry
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
  }, [motors, mode, wireframe]);

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
          <span>Open Duck Mini — Realistic 3D Robot Visualizer</span>
          <span className="badge">
            {totalJointsCount > 0 ? `${activeJointsCount}/${totalJointsCount} Servos Active` : "Telemetry Standby"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className={`btn ${mode === "3d" ? "primary" : ""}`}
            onClick={() => setMode("3d")}
          >
            3D Robot Model
          </button>
          <button
            className={`btn ${mode === "urdf" ? "primary" : ""}`}
            onClick={() => setMode("urdf")}
          >
            URDF Source XML
          </button>
        </div>
      </div>

      <div className="split split-tree">
        {/* Left Panel — Joint State & Controls */}
        <div className="panel" style={{ padding: 14 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: "var(--accent)" }}>
            Render Options
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            <label style={{ display: "flex", justifyContent: "space-between", fontSize: 13, cursor: "pointer" }}>
              <span>3D Wireframe Mesh</span>
              <input type="checkbox" checked={wireframe} onChange={(e) => setWireframe(e.target.checked)} />
            </label>
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

        {/* Right Panel — 3D WebGL Viewport or URDF Source XML */}
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

              {/* Instruction Overlay */}
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
                🖱️ Drag mouse to orbit 3D duck model · Scroll to zoom
              </div>

              {/* Camera PIP Overlay */}
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
