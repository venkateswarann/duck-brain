import { useTelemetry } from "../hooks/useTelemetry";
import { apiUrl } from "../config";

export default function CameraPage() {
  const { snapshot } = useTelemetry();
  const running = snapshot?.video?.running === true;
  const nodeState = snapshot?.nodes?.["video.capture"];

  return (
    <div className="page">
      <div className="page-title">
        <span>Camera</span>
        <span className="muted">
          video.capture: {nodeState ?? "—"} · stream{" "}
          {running ? "active" : "stopped"}
        </span>
      </div>
      <div style={{ padding: 16, height: "100%" }}>
        {running ? (
          <img
            src={apiUrl("/stream/camera")}
            alt="camera"
            style={{
              maxWidth: "100%",
              maxHeight: "calc(100% - 20px)",
              borderRadius: 8,
              border: "1px solid var(--border)",
            }}
          />
        ) : (
          <div className="placeholder">
            Camera stream offline. Start or restart the <code>video.capture</code>{" "}
            node under System / Nodes. Killing that node stops this stream.
          </div>
        )}
      </div>
    </div>
  );
}
