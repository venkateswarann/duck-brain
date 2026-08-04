import { useEffect, useState, useCallback } from "react";
import { apiUrl } from "../config";

type ServoInfo = {
  id: number;
  position_raw: number;
  position_rad: number;
  joint_name: string | null;
};

type JointStatus = {
  joint_name: string;
  expected_id: number;
  online: boolean;
  position_rad: number | null;
};

type CalibrationState = {
  active: boolean;
  offsets: Record<string, number>;
  joint_states: Record<string, string>;
  current_joint: string | null;
};

type CalibJoint = {
  name: string;
  state: string; // pending | in_progress | calibrated | skipped
  zeroPos: number | null;
  newPos: number | null;
  offset: number | null;
};

const JOINT_ORDER = [
  "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
  "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
  "neck_pitch", "head_pitch", "head_yaw", "head_roll",
];

export default function SetupPage() {
  const [tab, setTab] = useState<"servo" | "calibration">("servo");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  // Servo ID state
  const [servoStatus, setServoStatus] = useState<JointStatus[]>([]);
  const [scanResults, setScanResults] = useState<ServoInfo[]>([]);
  const [selectedJoint, setSelectedJoint] = useState("");
  const [scanLoading, setScanLoading] = useState(false);

  // Calibration state
  const [calibActive, setCalibActive] = useState(false);
  const [calibJoints, setCalibJoints] = useState<CalibJoint[]>([]);
  const [expandedJoint, setExpandedJoint] = useState<string | null>(null);
  const [calibStep, setCalibStep] = useState<Record<string, string>>({});

  const showMsg = (m: string) => { setMsg(m); setErr(""); };
  const showErr = (e: string) => { setErr(e); setMsg(""); };

  // ── Servo ID ────────────────────────────────────────────────────

  const loadServoStatus = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/setup/servo/status"));
      const data = await res.json();
      setServoStatus(data.joints || []);
    } catch {
      showErr("Could not load servo status");
    }
  }, []);

  useEffect(() => {
    loadServoStatus();
  }, [loadServoStatus]);

  const scanBus = async () => {
    setScanLoading(true);
    try {
      const res = await fetch(apiUrl("/api/setup/servo/scan"), { method: "POST" });
      const data = await res.json();
      setScanResults(data.servos || []);
      showMsg(`Found ${data.count} servo(s) on bus`);
      await loadServoStatus();
    } catch {
      showErr("Scan failed");
    } finally {
      setScanLoading(false);
    }
  };

  const assignServoId = async () => {
    if (!selectedJoint) return;
    // Find the unassigned servo (usually ID 1)
    const unassigned = scanResults.find(
      (s) => !s.joint_name || s.id === 1
    );
    if (!unassigned) {
      showErr("No unassigned servo found. Scan first.");
      return;
    }
    const expected = servoStatus.find((j) => j.joint_name === selectedJoint);
    if (!expected) return;

    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/setup/servo/set-id"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_id: unassigned.id,
          new_id: expected.expected_id,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");
      showMsg(
        `Servo ID changed: ${unassigned.id} → ${expected.expected_id} (${selectedJoint})`
      );
      setSelectedJoint("");
      setScanResults([]);
      await loadServoStatus();
    } catch (e: any) {
      showErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  const allOnline = servoStatus.every((j) => j.online);

  // ── Calibration ─────────────────────────────────────────────────

  const loadCalibStatus = async () => {
    try {
      const res = await fetch(apiUrl("/api/setup/calibration/status"));
      const data: CalibrationState = await res.json();
      setCalibActive(data.active);
      if (data.active) {
        setCalibJoints(
          JOINT_ORDER.map((name) => ({
            name,
            state: data.joint_states[name] || "pending",
            zeroPos: null,
            newPos: null,
            offset: data.offsets[name] ?? null,
          }))
        );
      }
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    loadCalibStatus();
  }, []);

  const startCalibration = async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/setup/calibration/start"), {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");
      setCalibActive(true);
      setCalibJoints(
        JOINT_ORDER.map((name) => ({
          name,
          state: "pending",
          zeroPos: null,
          newPos: null,
          offset: null,
        }))
      );
      setCalibStep({});
      showMsg("Calibration session started. Motors.telemetry paused.");
    } catch (e: any) {
      showErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  const stopCalibration = async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/setup/calibration/stop"), {
        method: "POST",
      });
      await res.json();
      setCalibActive(false);
      showMsg("Calibration session ended. Motors.telemetry resumed.");
    } catch (e: any) {
      showErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  const moveToZero = async () => {
    try {
      const res = await fetch(apiUrl("/api/setup/calibration/move-to-zero"), {
        method: "POST",
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail);
      }
      showMsg("All joints moved to zero position");
    } catch (e: any) {
      showErr(e.message);
    }
  };

  const calibrateJointStep = async (
    jointName: string,
    step: string
  ) => {
    try {
      let endpoint = "";
      let body: any = { joint_name: jointName };

      switch (step) {
        case "begin":
          await moveToZero();
          endpoint = "/api/setup/calibration/joint/read-position";
          break;
        case "release":
          endpoint = "/api/setup/calibration/joint/disable-torque";
          break;
        case "record":
          endpoint = "/api/setup/calibration/joint/read-position";
          break;
        case "test": {
          const joint = calibJoints.find((j) => j.name === jointName);
          if (!joint || joint.offset === null) return;
          endpoint = "/api/setup/calibration/joint/goto-zero";
          body.offset = joint.offset;
          // First enable torque
          await fetch(apiUrl("/api/setup/calibration/joint/enable-torque"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ joint_name: jointName }),
          });
          break;
        }
        case "accept": {
          const j = calibJoints.find((jt) => jt.name === jointName);
          if (!j || j.offset === null) return;
          endpoint = "/api/setup/calibration/joint/set-offset";
          body.offset = j.offset;
          break;
        }
        case "skip":
          endpoint = "/api/setup/calibration/joint/skip";
          break;
        case "retry":
          // Re-enable torque and reset
          await fetch(apiUrl("/api/setup/calibration/joint/enable-torque"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ joint_name: jointName }),
          });
          setCalibJoints((prev) =>
            prev.map((jt) =>
              jt.name === jointName
                ? { ...jt, state: "pending", zeroPos: null, newPos: null, offset: null }
                : jt
            )
          );
          setCalibStep((prev) => ({ ...prev, [jointName]: "" }));
          return;
        default:
          return;
      }

      if (!endpoint) return;

      const res = await fetch(apiUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");

      // Update state based on step
      setCalibJoints((prev) =>
        prev.map((jt) => {
          if (jt.name !== jointName) return jt;
          const updated = { ...jt };
          switch (step) {
            case "begin":
              updated.zeroPos = data.position_rad;
              updated.state = "in_progress";
              break;
            case "record":
              updated.newPos = data.position_rad;
              if (updated.zeroPos !== null) {
                updated.offset = Math.round(
                  (data.position_rad - updated.zeroPos) * 10000
                ) / 10000;
              }
              break;
            case "accept":
              updated.state = "calibrated";
              break;
            case "skip":
              updated.state = "skipped";
              break;
          }
          return updated;
        })
      );

      setCalibStep((prev) => ({ ...prev, [jointName]: step }));
    } catch (e: any) {
      showErr(e.message);
    }
  };

  const saveCalibration = async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/setup/calibration/save"), {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");
      showMsg(data.note || "Offsets saved to duck_config.json");
    } catch (e: any) {
      showErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  const emergencyStop = async () => {
    try {
      await fetch(apiUrl("/api/setup/calibration/emergency-stop"), {
        method: "POST",
      });
      setCalibActive(false);
      showMsg("⛔ Emergency stop — all torque disabled");
    } catch {
      showErr("Emergency stop failed!");
    }
  };

  const calibratedCount = calibJoints.filter(
    (j) => j.state === "calibrated"
  ).length;
  const totalJoints = calibJoints.length;

  return (
    <div className="page">
      <div className="page-title">
        <span>🔧 Setup</span>
        <div className="btn-row">
          {calibActive && (
            <button className="btn danger estop-btn" onClick={emergencyStop}>
              ⛔ Emergency Stop
            </button>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="setup-tabs">
        <button
          className={`setup-tab${tab === "servo" ? " active" : ""}`}
          onClick={() => setTab("servo")}
        >
          🔌 Servo IDs
        </button>
        <button
          className={`setup-tab${tab === "calibration" ? " active" : ""}`}
          onClick={() => setTab("calibration")}
        >
          🎯 Joint Calibration
        </button>
      </div>

      {msg && <div className="settings-msg success">{msg}</div>}
      {err && <div className="settings-msg error">{err}</div>}

      {/* ── Servo ID Tab ─────────────────────────────────────────── */}
      {tab === "servo" && (
        <div style={{ flex: 1, overflow: "auto" }}>
          <div className="panel" style={{ padding: 20, marginBottom: 16 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 16,
              }}
            >
              <h3 style={{ margin: 0 }}>Servo Status</h3>
              <button
                className="btn primary"
                onClick={scanBus}
                disabled={scanLoading}
              >
                {scanLoading ? "Scanning…" : "🔍 Scan Bus"}
              </button>
            </div>

            {allOnline && servoStatus.length > 0 && (
              <div className="setup-banner success">
                ✓ All {servoStatus.length} Servos Configured
              </div>
            )}

            <table className="table">
              <thead>
                <tr>
                  <th>Joint</th>
                  <th>Expected ID</th>
                  <th>Status</th>
                  <th>Position</th>
                </tr>
              </thead>
              <tbody>
                {servoStatus.map((j) => (
                  <tr key={j.joint_name}>
                    <td>
                      <code style={{ color: "var(--accent)" }}>
                        {j.joint_name}
                      </code>
                    </td>
                    <td>{j.expected_id}</td>
                    <td>
                      <span
                        className={`servo-status ${
                          j.online ? "online" : "offline"
                        }`}
                      >
                        {j.online ? "✓ Online" : "✗ Offline"}
                      </span>
                    </td>
                    <td className="muted">
                      {j.position_rad !== null
                        ? `${j.position_rad} rad`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Assign ID workflow */}
          {!allOnline && (
            <div className="panel" style={{ padding: 20 }}>
              <h3 style={{ marginTop: 0 }}>Assign Servo ID</h3>
              <div className="setup-instructions">
                <div className="setup-step">
                  <span className="step-num">1</span>
                  Connect <strong>one</strong> new servo to the bus
                </div>
                <div className="setup-step">
                  <span className="step-num">2</span>
                  Click <strong>Scan Bus</strong> above
                </div>
                <div className="setup-step">
                  <span className="step-num">3</span>
                  Select the target joint below
                </div>
                <div className="setup-step">
                  <span className="step-num">4</span>
                  Click <strong>Assign ID</strong>
                </div>
              </div>

              {scanResults.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div className="muted" style={{ marginBottom: 8 }}>
                    Found servos:{" "}
                    {scanResults.map((s) => `ID ${s.id}`).join(", ")}
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <select
                      className="settings-input"
                      value={selectedJoint}
                      onChange={(e) => setSelectedJoint(e.target.value)}
                    >
                      <option value="">Select joint…</option>
                      {servoStatus
                        .filter((j) => !j.online)
                        .map((j) => (
                          <option key={j.joint_name} value={j.joint_name}>
                            {j.joint_name} (ID {j.expected_id})
                          </option>
                        ))}
                    </select>
                    <button
                      className="btn primary"
                      onClick={assignServoId}
                      disabled={!selectedJoint || loading}
                    >
                      {loading ? "Assigning…" : "Assign ID"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Calibration Tab ──────────────────────────────────────── */}
      {tab === "calibration" && (
        <div style={{ flex: 1, overflow: "auto" }}>
          {/* Safety warning */}
          {!calibActive && (
            <div className="panel" style={{ padding: 20, marginBottom: 16 }}>
              <div className="setup-banner warning">
                ⚠️ Robot will move to its zero position. Place robot on a stand
                before starting. Motors.telemetry will be paused during
                calibration.
              </div>
              <button
                className="btn primary"
                onClick={startCalibration}
                disabled={loading}
                style={{ marginTop: 12 }}
              >
                {loading ? "Starting…" : "🎯 Start Calibration Session"}
              </button>
            </div>
          )}

          {calibActive && (
            <>
              {/* Progress bar */}
              <div className="panel" style={{ padding: 16, marginBottom: 16 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 8,
                  }}
                >
                  <span>
                    Progress: {calibratedCount} / {totalJoints} calibrated
                  </span>
                  <div className="btn-row">
                    <button className="btn" onClick={moveToZero}>
                      Move All to Zero
                    </button>
                    <button
                      className="btn primary"
                      onClick={saveCalibration}
                      disabled={calibratedCount === 0 || loading}
                    >
                      {loading ? "Saving…" : "💾 Save Config"}
                    </button>
                    <button className="btn" onClick={stopCalibration}>
                      End Session
                    </button>
                  </div>
                </div>
                <div className="calib-progress-bar">
                  <div
                    className="calib-progress-fill"
                    style={{
                      width: `${
                        totalJoints ? (calibratedCount / totalJoints) * 100 : 0
                      }%`,
                    }}
                  />
                </div>
              </div>

              {/* Joint cards */}
              {calibJoints.map((joint) => (
                <div
                  key={joint.name}
                  className={`calib-card ${joint.state}`}
                  onClick={() =>
                    setExpandedJoint(
                      expandedJoint === joint.name ? null : joint.name
                    )
                  }
                >
                  <div className="calib-card-header">
                    <code style={{ color: "var(--accent)", fontSize: 14 }}>
                      {joint.name}
                    </code>
                    <span className={`calib-status ${joint.state}`}>
                      {joint.state === "pending" && "⏳ Pending"}
                      {joint.state === "in_progress" && "🔄 In Progress"}
                      {joint.state === "calibrated" && "✓ Calibrated"}
                      {joint.state === "skipped" && "⏭ Skipped"}
                    </span>
                  </div>

                  {joint.offset !== null && (
                    <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                      Offset: {joint.offset} rad
                    </div>
                  )}

                  {expandedJoint === joint.name && (
                    <div
                      className="calib-card-body"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {/* Step-by-step calibration controls */}
                      {(joint.state === "pending" || joint.state === "in_progress") && (
                        <div className="calib-steps">
                          <div className="calib-step-row">
                            <button
                              className="btn"
                              onClick={() =>
                                calibrateJointStep(joint.name, "begin")
                              }
                              disabled={
                                calibStep[joint.name] === "begin"
                              }
                            >
                              1. Begin (Move to Zero)
                            </button>
                            {joint.zeroPos !== null && (
                              <span className="muted">
                                Zero pos: {joint.zeroPos} rad
                              </span>
                            )}
                          </div>

                          <div className="calib-step-row">
                            <button
                              className="btn"
                              onClick={() =>
                                calibrateJointStep(joint.name, "release")
                              }
                              disabled={joint.zeroPos === null}
                            >
                              2. Release Motor
                            </button>
                            {calibStep[joint.name] === "release" && (
                              <span style={{ color: "var(--warning)" }}>
                                🔓 Motor released — move joint by hand
                              </span>
                            )}
                          </div>

                          <div className="calib-step-row">
                            <button
                              className="btn"
                              onClick={() =>
                                calibrateJointStep(joint.name, "record")
                              }
                              disabled={calibStep[joint.name] !== "release"}
                            >
                              3. Record Position
                            </button>
                            {joint.offset !== null && (
                              <span>
                                Offset:{" "}
                                <strong style={{ color: "var(--accent)" }}>
                                  {joint.offset} rad
                                </strong>
                              </span>
                            )}
                          </div>

                          <div className="calib-step-row">
                            <button
                              className="btn"
                              onClick={() =>
                                calibrateJointStep(joint.name, "test")
                              }
                              disabled={joint.offset === null}
                            >
                              4. Test Zero (with offset)
                            </button>
                          </div>

                          <div className="calib-step-row" style={{ marginTop: 8 }}>
                            <button
                              className="btn primary"
                              onClick={() =>
                                calibrateJointStep(joint.name, "accept")
                              }
                              disabled={joint.offset === null}
                            >
                              ✓ Accept
                            </button>
                            <button
                              className="btn"
                              onClick={() =>
                                calibrateJointStep(joint.name, "retry")
                              }
                            >
                              ↻ Retry
                            </button>
                            <button
                              className="btn"
                              onClick={() =>
                                calibrateJointStep(joint.name, "skip")
                              }
                            >
                              ⏭ Skip
                            </button>
                          </div>
                        </div>
                      )}

                      {joint.state === "calibrated" && (
                        <div style={{ padding: "8px 0" }}>
                          <span style={{ color: "var(--accent)" }}>
                            ✓ Offset recorded: {joint.offset} rad
                          </span>
                          <button
                            className="btn"
                            style={{ marginLeft: 12 }}
                            onClick={() =>
                              calibrateJointStep(joint.name, "retry")
                            }
                          >
                            ↻ Redo
                          </button>
                        </div>
                      )}

                      {joint.state === "skipped" && (
                        <div style={{ padding: "8px 0" }}>
                          <span className="muted">Skipped — offset stays at 0</span>
                          <button
                            className="btn"
                            style={{ marginLeft: 12 }}
                            onClick={() =>
                              calibrateJointStep(joint.name, "retry")
                            }
                          >
                            ↻ Calibrate
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}

              {/* Offset summary */}
              <div className="panel" style={{ padding: 16, marginTop: 16 }}>
                <h4 style={{ marginTop: 0 }}>Offset Summary</h4>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Joint</th>
                      <th>Offset (rad)</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calibJoints.map((j) => (
                      <tr key={j.name}>
                        <td>
                          <code style={{ color: "var(--accent)" }}>
                            {j.name}
                          </code>
                        </td>
                        <td>{j.offset !== null ? j.offset : "—"}</td>
                        <td>
                          <span className={`calib-status ${j.state}`}>
                            {j.state}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
