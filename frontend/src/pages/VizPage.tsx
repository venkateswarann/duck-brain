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
  const motorsRef = useRef<Record<string, JointData>>({});

  const [mode, setMode] = useState<"3d" | "urdf">("3d");
  const [wireframe, setWireframe] = useState<boolean>(false);
  const [robotStatus, setRobotStatus] = useState<string>("Initializing 3D URDF Engine…");
  const [urdfXml, setUrdfXml] = useState<string>("");
  const [loadingUrdf, setLoadingUrdf] = useState<boolean>(true);
  const [showJointsTable, setShowJointsTable] = useState<boolean>(true);
  const [showCameraPip, setShowCameraPip] = useState<boolean>(true);

  const motors = (snapshot?.motors || {}) as Record<string, JointData>;

  // Keep telemetry motors in ref so animation loop reads live position without re-triggering Three.js mount
  useEffect(() => {
    motorsRef.current = motors;
  }, [motors]);

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

  // Three.js + URDFLoader Real Kinematic Duck Assembly Engine
  useEffect(() => {
    if (!canvasRef.current || mode !== "3d") return;

    let animationFrameId: number;
    let scene: any;
    let camera: any;
    let renderer: any;
    let robotModel: any;

    const loadScripts = () => {
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
          const s2 = document.createElement("script");
          s2.src = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js";
          s2.onload = () => {
            const s3 = document.createElement("script");
            s3.src = "https://cdn.jsdelivr.net/npm/urdf-loader@0.10.4/umd/URDFLoader.min.js";
            s3.onload = () => runInit();
            s3.onerror = () => runInit(); // Fallback if script fails
            document.body.appendChild(s3);
          };
          document.body.appendChild(s2);
        };
        document.body.appendChild(s1);
      } else if (!windowAny.THREE.STLLoader) {
        const s2 = document.createElement("script");
        s2.src = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js";
        s2.onload = () => {
          const s3 = document.createElement("script");
          s3.src = "https://cdn.jsdelivr.net/npm/urdf-loader@0.10.4/umd/URDFLoader.min.js";
          s3.onload = () => runInit();
          s3.onerror = () => runInit();
          document.body.appendChild(s3);
        };
        document.body.appendChild(s2);
      } else {
        runInit();
      }
    };

    const init3D = () => {
      const THREE = (window as any).THREE;
      const URDFLoaderClass = (window as any).URDFLoader;
      if (!THREE || !canvasRef.current) return;

      const width = canvasRef.current.parentElement?.clientWidth || 700;
      const height = canvasRef.current.parentElement?.clientHeight || 550;

      // 1. Scene & Camera
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x080c14);

      camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      camera.position.set(0.55, 0.35, 0.75);
      camera.lookAt(0, 0.12, 0);

      // 2. Renderer
      renderer = new THREE.WebGLRenderer({
        canvas: canvasRef.current,
        antialias: true,
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;

      // 3. Lighting
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
      scene.add(ambientLight);

      const mainLight = new THREE.DirectionalLight(0xffffff, 0.9);
      mainLight.position.set(2, 4, 3);
      mainLight.castShadow = true;
      scene.add(mainLight);

      const fillLight = new THREE.DirectionalLight(0x5b9cff, 0.4);
      fillLight.position.set(-3, 2, -2);
      scene.add(fillLight);

      // 4. Grid Floor
      const grid = new THREE.GridHelper(3, 30, 0x3dd68c, 0x1e293b);
      grid.position.y = -0.22;
      scene.add(grid);

      // 5. URDFLoader Assembly
      if (URDFLoaderClass) {
        const urdfLoader = new URDFLoaderClass();

        // Custom Mesh callback for STL loading from /api/robot/assets/{filename}
        urdfLoader.loadMeshCb = (path: string, manager: any, done: (mesh: any) => void) => {
          const filename = path.split("/").pop() || path;
          if (!THREE.STLLoader) return done(new THREE.Object3D());

          const stlLoader = new THREE.STLLoader(manager);
          stlLoader.load(
            apiUrl(`/api/robot/assets/${filename}`),
            (geometry: any) => {
              geometry.computeVertexNormals();
              const lower = filename.toLowerCase();

              let color = 0xf1f5f9; // Default feather white/silver
              if (lower.includes("beak") || lower.includes("foot")) color = 0xf59e0b; // Yellow
              else if (lower.includes("switch") || lower.includes("left")) color = 0x3dd68c; // Accent Green
              else if (lower.includes("right")) color = 0xef4444; // Accent Red
              else if (lower.includes("eye") || lower.includes("charger")) color = 0x1e293b; // Dark

              const mat = new THREE.MeshStandardMaterial({
                color: color,
                roughness: 0.3,
                metalness: 0.2,
                wireframe: wireframe,
              });
              const mesh = new THREE.Mesh(geometry, mat);
              mesh.castShadow = true;
              mesh.receiveShadow = true;
              done(mesh);
            },
            undefined,
            () => {
              done(new THREE.Object3D());
            }
          );
        };

        // Load URDF XML from Backend
        urdfLoader.load(
          apiUrl("/api/robot/urdf"),
          (robot: any) => {
            robotModel = robot;
            robot.rotation.x = -Math.PI / 2; // Orient upright
            scene.add(robot);
            setRobotStatus("Full CAD URDF Robot Model Loaded");
          },
          undefined,
          () => {
            setRobotStatus("URDF Load Failed");
          }
        );
      }

      // 6. Interactive Mouse Orbit Controls
      let isDragging = false;
      let prevMousePos = { x: 0, y: 0 };

      const onMouseDown = (e: MouseEvent) => {
        isDragging = true;
        prevMousePos = { x: e.clientX, y: e.clientY };
      };

      const onMouseMove = (e: MouseEvent) => {
        if (!isDragging || !scene) return;
        const dx = e.clientX - prevMousePos.x;
        const dy = e.clientY - prevMousePos.y;

        if (robotModel) {
          robotModel.rotation.z += dx * 0.01;
        }

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

      // 7. 60 FPS Render & Kinematic Telemetry Sync Loop
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);

        if (robotModel && robotModel.setJointValue) {
          const currentMotors = motorsRef.current;
          Object.entries(currentMotors).forEach(([name, data]) => {
            if (typeof data.position === "number") {
              try {
                robotModel.setJointValue(name, data.position);
              } catch (_) {}
            }
          });

          // Wireframe sync
          robotModel.traverse((child: any) => {
            if (child.isMesh && child.material) {
              child.material.wireframe = wireframe;
            }
          });
        }

        renderer.render(scene, camera);
      };

      animate();
    };

    loadScripts();

    return () => {
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      if (renderer) {
        try {
          renderer.dispose();
          renderer.forceContextLoss();
        } catch (_) {}
      }
      if (scene) {
        try {
          scene.clear();
        } catch (_) {}
      }
    };
  }, [mode, wireframe]);

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
          <span>Open Duck Mini — URDF CAD Assembly Renderer</span>
          <span className="badge">{robotStatus}</span>
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
                3D Joint Angle Telemetry ({activeJointsCount}/{totalJointsCount})
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
