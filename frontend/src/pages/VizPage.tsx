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

// STL Mesh mapping from URDF file links
const STL_MAP: { stl: string; parent: string; color: number; scale?: number }[] = [
  // Trunk / Body
  { stl: "body_front.stl", parent: "trunk", color: 0xf1f5f9 },
  { stl: "body_back.stl", parent: "trunk", color: 0xf1f5f9 },
  { stl: "body_middle_bottom.stl", parent: "trunk", color: 0xe2e8f0 },
  { stl: "body_middle_top.stl", parent: "trunk", color: 0xe2e8f0 },
  { stl: "power_switch.stl", parent: "trunk", color: 0x3dd68c },
  { stl: "usb_c_charger.stl", parent: "trunk", color: 0x5b9cff },
  { stl: "battery_pack_lid.stl", parent: "trunk", color: 0x334155 },
  // Head & Beak
  { stl: "head_pitch_assembly.stl", parent: "head_roll", color: 0xf8fafc },
  { stl: "beak.stl", parent: "head_roll", color: 0xf59e0b },
  // Left Leg
  { stl: "left_hip_yaw.stl", parent: "left_hip_yaw", color: 0x3dd68c },
  { stl: "left_hip_roll.stl", parent: "left_hip_roll", color: 0x3dd68c },
  { stl: "left_hip_pitch.stl", parent: "left_hip_pitch", color: 0x3dd68c },
  { stl: "left_knee.stl", parent: "left_knee", color: 0x3dd68c },
  { stl: "left_ankle.stl", parent: "left_ankle", color: 0x3dd68c },
  { stl: "left_foot.stl", parent: "left_ankle", color: 0xf59e0b },
  // Right Leg
  { stl: "right_hip_yaw.stl", parent: "right_hip_yaw", color: 0xef4444 },
  { stl: "right_hip_roll.stl", parent: "right_hip_roll", color: 0xef4444 },
  { stl: "right_hip_pitch.stl", parent: "right_hip_pitch", color: 0xef4444 },
  { stl: "right_knee.stl", parent: "right_knee", color: 0xef4444 },
  { stl: "right_ankle.stl", parent: "right_ankle", color: 0xef4444 },
  { stl: "right_foot.stl", parent: "right_ankle", color: 0xf59e0b },
];

export default function VizPage() {
  const { snapshot } = useTelemetry();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [mode, setMode] = useState<"3d" | "urdf">("3d");
  const [wireframe, setWireframe] = useState<boolean>(false);
  const [loadedStlCount, setLoadedStlCount] = useState<number>(0);
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

  // Three.js 3D Real STL CAD Mesh & Kinematic Scene Renderer
  useEffect(() => {
    if (!canvasRef.current || mode !== "3d") return;

    let animationFrameId: number;
    let scene: any;
    let camera: any;
    let renderer: any;
    let duckGroup: any;

    const jointNodes: Record<string, any> = {};
    const fallbackMeshes: any[] = [];

    const loadThreeAndSTL = () => {
      const windowAny = window as any;

      const runInit = () => {
        if (windowAny.THREE && windowAny.THREE.STLLoader) {
          init3D();
        } else {
          setTimeout(runInit, 50);
        }
      };

      if (!windowAny.THREE) {
        const s1 = document.createElement("script");
        s1.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
        s1.onload = () => {
          if (!windowAny.THREE?.STLLoader) {
            const s2 = document.createElement("script");
            s2.src = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js";
            s2.onload = () => runInit();
            document.body.appendChild(s2);
          } else {
            runInit();
          }
        };
        document.body.appendChild(s1);
      } else if (!windowAny.THREE.STLLoader) {
        const s2 = document.createElement("script");
        s2.src = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js";
        s2.onload = () => runInit();
        document.body.appendChild(s2);
      } else {
        runInit();
      }
    };

    const init3D = () => {
      const THREE = (window as any).THREE;
      if (!THREE || !canvasRef.current) return;

      const width = canvasRef.current.parentElement?.clientWidth || 700;
      const height = canvasRef.current.parentElement?.clientHeight || 550;

      // 1. Scene & Camera
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x080c14);

      camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      camera.position.set(0.65, 0.4, 0.85);
      camera.lookAt(0, 0.15, 0);

      // 2. Renderer
      renderer = new THREE.WebGLRenderer({
        canvas: canvasRef.current,
        antialias: true,
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;

      // 3. Lights
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
      scene.add(ambientLight);

      const mainLight = new THREE.DirectionalLight(0xffffff, 0.9);
      mainLight.position.set(2, 4, 3);
      mainLight.castShadow = true;
      scene.add(mainLight);

      const blueLight = new THREE.DirectionalLight(0x5b9cff, 0.4);
      blueLight.position.set(-3, 2, -2);
      scene.add(blueLight);

      // 4. Grid Floor
      const grid = new THREE.GridHelper(3, 30, 0x3dd68c, 0x1e293b);
      grid.position.y = -0.22;
      scene.add(grid);

      // 5. Open Duck Mini Scene Graph Assembly
      duckGroup = new THREE.Group();

      // Base Trunk Group
      const trunkGroup = new THREE.Group();
      trunkGroup.position.y = 0.18;
      duckGroup.add(trunkGroup);
      jointNodes["trunk"] = trunkGroup;

      // Default Fallback Geometry (used while STL loads or if STL is missing)
      const matFallback = new THREE.MeshStandardMaterial({
        color: 0x94a3b8,
        wireframe: wireframe,
      });
      const torsoFB = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.065, 0.15, 16), matFallback);
      trunkGroup.add(torsoFB);
      fallbackMeshes.push(torsoFB);

      // Head & Neck
      const neckGroup = new THREE.Group();
      neckGroup.position.set(0, 0.09, 0.03);
      trunkGroup.add(neckGroup);
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

      const headFB = new THREE.Mesh(new THREE.SphereGeometry(0.055, 16, 16), matFallback);
      headRollGroup.add(headFB);
      fallbackMeshes.push(headFB);

      // Left Leg
      const lHipYaw = new THREE.Group();
      lHipYaw.position.set(0.045, -0.07, 0);
      trunkGroup.add(lHipYaw);
      jointNodes["left_hip_yaw"] = lHipYaw;

      const lHipRoll = new THREE.Group();
      lHipYaw.add(lHipRoll);
      jointNodes["left_hip_roll"] = lHipRoll;

      const lHipPitch = new THREE.Group();
      lHipRoll.add(lHipPitch);
      jointNodes["left_hip_pitch"] = lHipPitch;

      const lKnee = new THREE.Group();
      lKnee.position.y = -0.11;
      lHipPitch.add(lKnee);
      jointNodes["left_knee"] = lKnee;

      const lAnkle = new THREE.Group();
      lAnkle.position.y = -0.11;
      lKnee.add(lAnkle);
      jointNodes["left_ankle"] = lAnkle;

      // Right Leg
      const rHipYaw = new THREE.Group();
      rHipYaw.position.set(-0.045, -0.07, 0);
      trunkGroup.add(rHipYaw);
      jointNodes["right_hip_yaw"] = rHipYaw;

      const rHipRoll = new THREE.Group();
      rHipYaw.add(rHipRoll);
      jointNodes["right_hip_roll"] = rHipRoll;

      const rHipPitch = new THREE.Group();
      rHipRoll.add(rHipPitch);
      jointNodes["right_hip_pitch"] = rHipPitch;

      const rKnee = new THREE.Group();
      rKnee.position.y = -0.11;
      rHipPitch.add(rKnee);
      jointNodes["right_knee"] = rKnee;

      const rAnkle = new THREE.Group();
      rAnkle.position.y = -0.11;
      rKnee.add(rAnkle);
      jointNodes["right_ankle"] = rAnkle;

      scene.add(duckGroup);

      // 6. Dynamic STL CAD Mesh Loading from /api/robot/assets/{filename}
      if (THREE.STLLoader) {
        const stlLoader = new THREE.STLLoader();
        let loadedCount = 0;

        STL_MAP.forEach((item) => {
          const url = apiUrl(`/api/robot/assets/${item.stl}`);
          stlLoader.load(
            url,
            (geometry: any) => {
              geometry.computeVertexNormals();
              geometry.computeBoundingBox();
              const box = geometry.boundingBox;
              if (box) {
                const size = new THREE.Vector3();
                box.getSize(size);
                if (Math.max(size.x, size.y, size.z) > 5) {
                  geometry.scale(0.001, 0.001, 0.001);
                }
              }

              const mat = new THREE.MeshStandardMaterial({
                color: item.color,
                roughness: 0.3,
                metalness: 0.2,
                wireframe: wireframe,
              });
              const mesh = new THREE.Mesh(geometry, mat);
              mesh.castShadow = true;
              mesh.receiveShadow = true;

              const parentNode = jointNodes[item.parent] || trunkGroup;
              parentNode.add(mesh);

              loadedCount += 1;
              setLoadedStlCount(loadedCount);

              // Hide fallback shapes once CAD STL meshes begin rendering
              if (loadedCount >= 1) {
                fallbackMeshes.forEach((fb) => (fb.visible = false));
              }
            },
            undefined,
            () => {
              /* Ignore missing STL files — fallback geometry stays visible */
            }
          );
        });
      }

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

      // 8. Render & Real-Time Kinematic Joint Sync Loop
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);

        // Synchronize joint angles from WebSocket telemetry
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

    loadThreeAndSTL();

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
          <span>Open Duck Mini — Real STL 3D Robot CAD Renderer</span>
          <span className="badge">
            {loadedStlCount > 0 ? `${loadedStlCount} CAD STL Meshes Loaded` : `${totalJointsCount} Joint Nodes Active`}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className={`btn ${mode === "3d" ? "primary" : ""}`}
            onClick={() => setMode("3d")}
          >
            3D STL Robot Model
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
                🖱️ Drag mouse to orbit CAD STL duck model · Scroll to zoom
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
