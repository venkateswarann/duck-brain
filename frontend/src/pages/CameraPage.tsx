import { useState, useEffect } from "react";
import { useTelemetry } from "../hooks/useTelemetry";
import { apiUrl } from "../config";

export default function CameraPage() {
  const { snapshot } = useTelemetry();
  const running = snapshot?.video?.running === true;
  const nodeState = snapshot?.nodes?.["video.capture"];

  const [rotation, setRotation] = useState<number>(180); // Default 180 for inverted setup
  const [flipH, setFlipH] = useState<boolean>(false);
  const [flipV, setFlipV] = useState<boolean>(false);
  const [swapRb, setSwapRb] = useState<boolean>(false);
  const [resolution, setResolution] = useState<string>("640x480");
  const [fps, setFps] = useState<number>(15);
  const [saving, setSaving] = useState<boolean>(false);
  const [statusMsg, setStatusMsg] = useState<string>("");

  // Load current node config on mount
  useEffect(() => {
    fetch(apiUrl("/api/nodes/video.capture/config"))
      .then((res) => (res.ok ? res.json() : null))
      .then((cfg) => {
        if (cfg) {
          if (typeof cfg.rotation === "number") setRotation(cfg.rotation);
          if (typeof cfg.flip_h === "boolean") setFlipH(cfg.flip_h);
          if (typeof cfg.flip_v === "boolean") setFlipV(cfg.flip_v);
          if (typeof cfg.swap_rb === "boolean") setSwapRb(cfg.swap_rb);
          if (typeof cfg.fps === "number") setFps(cfg.fps);
          if (cfg.width && cfg.height) setResolution(`${cfg.width}x${cfg.height}`);
        }
      })
      .catch(() => {});
  }, []);

  const applyConfig = async (newRotation: number, newFlipH: boolean, newFlipV: boolean, newSwapRb: boolean, newRes: string, newFps: number) => {
    setSaving(true);
    setStatusMsg("");
    const [w, h] = newRes.split("x").map(Number);
    try {
      const res = await fetch(apiUrl("/api/nodes/video.capture/config"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rotation: newRotation,
          flip_h: newFlipH,
          flip_v: newFlipV,
          swap_rb: newSwapRb,
          width: w,
          height: h,
          fps: newFps,
        }),
      });
      if (res.ok) {
        setStatusMsg("Applied to camera node");
      } else {
        setStatusMsg("Failed to update config");
      }
    } catch (err) {
      setStatusMsg("Connection error");
    } finally {
      setSaving(false);
      setTimeout(() => setStatusMsg(""), 3000);
    }
  };

  const handleRotationChange = (deg: number) => {
    setRotation(deg);
    applyConfig(deg, flipH, flipV, swapRb, resolution, fps);
  };

  const handleFlipHChange = () => {
    const val = !flipH;
    setFlipH(val);
    applyConfig(rotation, val, flipV, swapRb, resolution, fps);
  };

  const handleFlipVChange = () => {
    const val = !flipV;
    setFlipV(val);
    applyConfig(rotation, flipH, val, swapRb, resolution, fps);
  };

  const handleSwapRbChange = () => {
    const val = !swapRb;
    setSwapRb(val);
    applyConfig(rotation, flipH, flipV, val, resolution, fps);
  };

  const handleResChange = (resStr: string) => {
    setResolution(resStr);
    applyConfig(rotation, flipH, flipV, swapRb, resStr, fps);
  };

  const handleFpsChange = (newFps: number) => {
    setFps(newFps);
    applyConfig(rotation, flipH, flipV, swapRb, resolution, newFps);
  };

  // Compute CSS transform for instant preview & display
  const cssTransform = `rotate(${rotation}deg) scaleX(${flipH ? -1 : 1}) scaleY(${flipV ? -1 : 1})`;

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Camera Stream</span>
          <span className={`status-dot status-${nodeState || "stopped"}`} />
          <span className="muted" style={{ fontSize: 13 }}>
            video.capture: {nodeState ?? "—"} · {running ? "LIVE" : "OFFLINE"}
          </span>
        </div>
        {statusMsg && (
          <span style={{ fontSize: 12, color: "var(--accent)" }}>{statusMsg}</span>
        )}
      </div>

      {/* Control Toolbar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 16,
          padding: "10px 16px",
          background: "var(--bg-panel)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {/* Rotation */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Rotation:</span>
          {[0, 90, 180, 270].map((deg) => (
            <button
              key={deg}
              className={`btn ${rotation === deg ? "primary" : ""}`}
              style={{ padding: "4px 8px", fontSize: 12 }}
              onClick={() => handleRotationChange(deg)}
            >
              {deg}° {deg === 180 ? "(Inverted)" : ""}
            </button>
          ))}
        </div>

        {/* Flips */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Flip:</span>
          <button
            className={`btn ${flipH ? "primary" : ""}`}
            style={{ padding: "4px 8px", fontSize: 12 }}
            onClick={handleFlipHChange}
          >
            Horizontal ↔
          </button>
          <button
            className={`btn ${flipV ? "primary" : ""}`}
            style={{ padding: "4px 8px", fontSize: 12 }}
            onClick={handleFlipVChange}
          >
            Vertical ↕
          </button>
          <button
            className={`btn ${swapRb ? "primary" : ""}`}
            style={{ padding: "4px 8px", fontSize: 12 }}
            onClick={handleSwapRbChange}
          >
            Swap R/B Colors 🎨
          </button>
        </div>

        {/* Resolution */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Resolution:</span>
          <select
            value={resolution}
            onChange={(e) => handleResChange(e.target.value)}
            style={{
              background: "#121820",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "4px 8px",
              fontSize: 12,
            }}
          >
            <option value="320x240">320 x 240 (Low)</option>
            <option value="640x480">640 x 480 (Standard)</option>
            <option value="800x600">800 x 600 (Medium)</option>
            <option value="1280x720">1280 x 720 (HD)</option>
          </select>
        </div>

        {/* FPS */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>FPS:</span>
          {[5, 10, 15, 20, 30].map((f) => (
            <button
              key={f}
              className={`btn ${fps === f ? "primary" : ""}`}
              style={{ padding: "4px 8px", fontSize: 12 }}
              onClick={() => handleFpsChange(f)}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Main Viewport Area */}
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "radial-gradient(circle at 50% 50%, #151d2a, #0b0e14 80%)",
          overflow: "hidden",
          padding: 24,
          position: "relative",
        }}
      >
        {running ? (
          <div
            style={{
              position: "relative",
              maxWidth: "100%",
              maxHeight: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <img
              src={apiUrl("/stream/camera")}
              alt="Live Open Duck Camera"
              style={{
                maxWidth: "100%",
                maxHeight: "75vh",
                objectFit: "contain",
                borderRadius: 12,
                boxShadow: "0 12px 36px rgba(0,0,0,0.6)",
                border: "1px solid var(--border)",
                transform: cssTransform,
                transition: "transform 0.2s ease-in-out",
              }}
            />
          </div>
        ) : (
          <div
            style={{
              textAlign: "center",
              maxWidth: 420,
              padding: 32,
              borderRadius: 16,
              background: "var(--bg-panel)",
              border: "1px solid var(--border)",
            }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: "50%",
                background: "#2a1f20",
                color: "var(--danger)",
                display: "grid",
                placeItems: "center",
                margin: "0 auto 16px",
                fontSize: 20,
              }}
            >
              📹
            </div>
            <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 8 }}>
              Camera Stream Offline
            </div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 20 }}>
              The <code>video.capture</code> node is currently not running. Start or restart it on the System / Nodes page.
            </div>
            <button
              className="btn primary"
              onClick={() => fetch(apiUrl("/api/nodes/video.capture/start"), { method: "POST" })}
            >
              Start Camera Node
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
