import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiUrl } from "../config";

type HelpParam = {
  key: string;
  group: string;
  type: string;
  default?: unknown;
  options?: string[];
  summary: string;
  details: string;
};

type DuckConfig = Record<string, any>;

const EDITABLE = [
  "robot_id",
  "robot_name",
  "serial_port",
  "baudrate",
  "poll_hz",
  "mock_hardware",
  "serial_policy",
  "camera_device",
  "camera_width",
  "camera_height",
  "camera_rotation",
  "camera_fps",
  "camera_flip_h",
  "camera_flip_v",
  "camera_swap_rb",
  "allow_script_runner",
  "allow_web_terminal",
  "mcp_dev_mode",
  "llm_provider",
  "llm_endpoint",
  "llm_api_key",
  "llm_model",
  "llm_temperature",
  "llm_max_tokens",
] as const;

const SETTING_GROUPS = [
  "Robot",
  "Servos",
  "Camera",
  "Joints",
  "UI scales",
  "Nodes",
  "Control",
  "Security",
  "LLM Agent",
  "Raw JSON",
];

export default function SettingsPage() {
  const [help, setHelp] = useState<HelpParam[]>([]);
  const [cfg, setCfg] = useState<DuckConfig | null>(null);
  const [draft, setDraft] = useState<DuckConfig | null>(null);
  const [group, setGroup] = useState("Robot");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => {
    fetch(apiUrl("/api/help"))
      .then((r) => r.json())
      .then((h) => setHelp(h.parameters || []))
      .catch(() => setErr("Could not load parameter metadata"));
    fetch(apiUrl("/api/config"))
      .then((r) => r.json())
      .then((c) => {
        setCfg(c);
        setDraft(structuredClone(c));
      })
      .catch(() => setErr("Could not load config — is the backend running?"));
  };

  useEffect(() => {
    load();
  }, []);

  const paramsInGroup = help.filter((p) => p.group === group);

  const setField = (key: string, value: unknown) => {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  };

  const setNestedField = (path: string[], value: unknown) => {
    setDraft((d) => {
      if (!d) return d;
      const next = structuredClone(d);
      let target: any = next;
      for (let i = 0; i < path.length - 1; i++) {
        if (!(path[i] in target)) target[path[i]] = {};
        target = target[path[i]];
      }
      target[path[path.length - 1]] = value;
      return next;
    });
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setMsg("");
    setErr("");
    try {
      const res = await fetch(apiUrl("/api/config"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || JSON.stringify(body));
      setCfg(body.config);
      setDraft(structuredClone(body.config));
      setMsg(body.note || "Saved.");
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setSaving(false);
    }
  };

  const resetDraft = () => {
    if (cfg) setDraft(structuredClone(cfg));
    setMsg("");
    setErr("");
  };

  const isDirty = JSON.stringify(draft) !== JSON.stringify(cfg);

  return (
    <div className="page">
      <div className="page-title">
        <span>⚙ Settings</span>
        <div className="btn-row">
          <button className="btn" onClick={resetDraft} disabled={!isDirty}>
            Reset
          </button>
          <button
            className="btn primary"
            onClick={save}
            disabled={saving || !draft || !isDirty}
          >
            {saving ? "Saving…" : "Save config"}
          </button>
        </div>
      </div>

      <div
        className="split"
        style={{ gridTemplateColumns: "200px 1fr", flex: 1 }}
      >
        <div className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ marginBottom: 8 }}>
            Groups
          </div>
          {SETTING_GROUPS.map((g) => (
            <button
              key={g}
              type="button"
              className={`settings-group-btn${group === g ? " active" : ""}`}
              onClick={() => setGroup(g)}
            >
              {g}
            </button>
          ))}
        </div>

        <div className="panel" style={{ padding: 16, overflow: "auto" }}>
          {msg && (
            <div className="settings-msg success">{msg}</div>
          )}
          {err && (
            <div className="settings-msg error">{err}</div>
          )}

          {/* Joints editor */}
          {group === "Joints" && draft && (
            <>
              <h3 style={{ marginTop: 0 }}>Joint Configuration</h3>
              <p className="muted" style={{ marginBottom: 12 }}>
                Servo IDs and end limits (min/max) in radians.{" "}
                <Link to="/setup" style={{ color: "var(--blue)" }}>
                  Use Setup page
                </Link>{" "}
                for servo ID assignment.
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Joint</th>
                    <th>ID</th>
                    <th>Min (rad)</th>
                    <th>Max (rad)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(draft.joints || {}).map(
                    ([name, j]: [string, any]) => (
                      <tr key={name}>
                        <td>
                          <code style={{ color: "var(--accent)" }}>{name}</code>
                        </td>
                        <td>
                          <input
                            type="number"
                            className="settings-input narrow"
                            value={j.id ?? ""}
                            onChange={(e) =>
                              setNestedField(
                                ["joints", name, "id"],
                                parseInt(e.target.value) || 0
                              )
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            className="settings-input narrow"
                            value={j.min ?? ""}
                            onChange={(e) =>
                              setNestedField(
                                ["joints", name, "min"],
                                parseFloat(e.target.value) || 0
                              )
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            className="settings-input narrow"
                            value={j.max ?? ""}
                            onChange={(e) =>
                              setNestedField(
                                ["joints", name, "max"],
                                parseFloat(e.target.value) || 0
                              )
                            }
                          />
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>

              <h4 style={{ marginTop: 24, color: "var(--blue)" }}>
                Joint Offsets
              </h4>
              <p className="muted" style={{ marginBottom: 12 }}>
                Calibration offsets (rad). Use the{" "}
                <Link to="/setup" style={{ color: "var(--blue)" }}>
                  Calibration Wizard
                </Link>{" "}
                for guided calibration, or edit manually below.
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Joint</th>
                    <th>Offset (rad)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(draft.joints_offsets || {}).map(
                    ([name, val]: [string, any]) => (
                      <tr key={name}>
                        <td>
                          <code style={{ color: "var(--accent)" }}>{name}</code>
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            className="settings-input"
                            value={val ?? 0}
                            onChange={(e) =>
                              setNestedField(
                                ["joints_offsets", name],
                                parseFloat(e.target.value) || 0
                              )
                            }
                          />
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </>
          )}

          {/* UI scales editor */}
          {group === "UI scales" && draft && (
            <>
              <h3 style={{ marginTop: 0 }}>Telemetry UI Scales</h3>
              <p className="muted" style={{ marginBottom: 12 }}>
                Min/max for temperature, voltage, current, load, speed bars in
                the Devices page.
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Min</th>
                    <th>Max</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(draft.telemetry_scales || {}).map(
                    ([metric, s]: [string, any]) => (
                      <tr key={metric}>
                        <td>
                          <code style={{ color: "var(--accent)" }}>
                            {metric}
                          </code>
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            className="settings-input narrow"
                            value={s.min ?? 0}
                            onChange={(e) =>
                              setNestedField(
                                ["telemetry_scales", metric, "min"],
                                parseFloat(e.target.value) || 0
                              )
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            className="settings-input narrow"
                            value={s.max ?? 0}
                            onChange={(e) =>
                              setNestedField(
                                ["telemetry_scales", metric, "max"],
                                parseFloat(e.target.value) || 0
                              )
                            }
                          />
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </>
          )}

          {/* Nodes editor */}
          {group === "Nodes" && draft && (
            <>
              <h3 style={{ marginTop: 0 }}>Auto-Start Nodes</h3>
              <p className="muted" style={{ marginBottom: 12 }}>
                Which nodes auto-start when the backend boots.
              </p>
              {Object.entries(draft.nodes || {}).map(
                ([nodeId, enabled]: [string, any]) => (
                  <label
                    key={nodeId}
                    style={{
                      display: "flex",
                      gap: 8,
                      alignItems: "center",
                      marginBottom: 10,
                      padding: "8px 12px",
                      borderRadius: 6,
                      border: "1px solid var(--border)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={!!enabled}
                      onChange={(e) =>
                        setNestedField(["nodes", nodeId], e.target.checked)
                      }
                    />
                    <code>{nodeId}</code>
                    <span className="muted" style={{ marginLeft: "auto" }}>
                      {enabled ? "auto-start" : "manual"}
                    </span>
                  </label>
                )
              )}
            </>
          )}

          {/* Control/keymap editor */}
          {group === "Control" && draft && (
            <>
              <h3 style={{ marginTop: 0 }}>Gamepad Keymap</h3>
              <p className="muted" style={{ marginBottom: 12 }}>
                Action → axis or button mapping for Xbox / gamepad control.
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Type</th>
                    <th>ID</th>
                    <th>Label</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(
                    (draft.control as any)?.keymap || {}
                  ).map(([action, map]: [string, any]) => (
                    <tr key={action}>
                      <td>
                        <code style={{ color: "var(--accent)" }}>{action}</code>
                      </td>
                      <td>
                        <select
                          className="settings-input narrow"
                          value={map.type || "axis"}
                          onChange={(e) =>
                            setNestedField(
                              ["control", "keymap", action, "type"],
                              e.target.value
                            )
                          }
                        >
                          <option value="axis">axis</option>
                          <option value="button">button</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          className="settings-input narrow"
                          value={map.id ?? ""}
                          onChange={(e) =>
                            setNestedField(
                              ["control", "keymap", action, "id"],
                              parseInt(e.target.value) || 0
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className="settings-input"
                          value={map.label ?? ""}
                          onChange={(e) =>
                            setNestedField(
                              ["control", "keymap", action, "label"],
                              e.target.value
                            )
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {/* Raw JSON editor */}
          {group === "Raw JSON" && draft && (
            <>
              <h3 style={{ marginTop: 0 }}>Raw duck_config.json</h3>
              <p className="muted" style={{ marginBottom: 8 }}>
                Advanced: edit JSON then Save. Invalid JSON fields are rejected
                by the API.
              </p>
              <textarea
                className="log-view"
                style={{
                  width: "100%",
                  height: "calc(100% - 80px)",
                  minHeight: 420,
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  background: "#0f141c",
                }}
                value={JSON.stringify(draft, null, 2)}
                onChange={(e) => {
                  try {
                    setDraft(JSON.parse(e.target.value));
                    setErr("");
                  } catch {
                    setErr("JSON parse error — fix before saving");
                  }
                }}
              />
            </>
          )}

          {/* LLM Agent Panel */}
          {group === "LLM Agent" && draft && (
            <LlmSettingsSection
              draft={draft}
              setField={setField}
              saveConfig={save}
            />
          )}

          {/* Standard parameter groups */}
          {group !== "Joints" &&
            group !== "UI scales" &&
            group !== "Nodes" &&
            group !== "Control" &&
            group !== "LLM Agent" &&
            group !== "Raw JSON" &&
            paramsInGroup.map((p) => {
              const editable = EDITABLE.includes(
                p.key as (typeof EDITABLE)[number]
              );
              const value = draft ? draft[p.key] : undefined;
              return (
                <div key={p.key} className="settings-param">
                  <div className="settings-param-header">
                    <code style={{ color: "var(--accent)" }}>{p.key}</code>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {p.type}
                      {p.default !== undefined
                        ? ` · default ${JSON.stringify(p.default)}`
                        : ""}
                    </span>
                  </div>
                  <div style={{ margin: "6px 0" }}>{p.summary}</div>
                  <div
                    className="muted"
                    style={{ fontSize: 13, marginBottom: 8 }}
                  >
                    {p.details}
                  </div>

                  {editable && draft && p.type === "bool" && (
                    <label className="settings-toggle">
                      <input
                        type="checkbox"
                        checked={!!value}
                        onChange={(e) => setField(p.key, e.target.checked)}
                      />
                      {value ? "enabled" : "disabled"}
                      {p.key === "mcp_dev_mode" && value && (
                        <span
                          style={{
                            marginLeft: 8,
                            color: "var(--danger)",
                            fontSize: 12,
                          }}
                        >
                          ⚠️ AI models can execute dangerous operations
                        </span>
                      )}
                    </label>
                  )}
                  {editable && draft && p.type === "enum" && (
                    <select
                      className="settings-input"
                      value={String(value ?? "")}
                      onChange={(e) => setField(p.key, e.target.value)}
                    >
                      {(p.options || []).map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  )}
                  {editable &&
                    draft &&
                    (p.type === "string" ||
                      p.type === "int" ||
                      p.type === "float" ||
                      p.type === "string / int") && (
                      <input
                        className="settings-input"
                        type={p.type === "string" || p.type === "string / int" ? "text" : "number"}
                        step={p.type === "float" ? "any" : "1"}
                        value={value ?? ""}
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (p.type === "string" || p.type === "string / int")
                            setField(p.key, raw);
                          else if (p.type === "int")
                            setField(p.key, Number.parseInt(raw, 10) || 0);
                          else setField(p.key, Number.parseFloat(raw) || 0);
                        }}
                      />
                    )}
                  {!editable && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      Edit under the appropriate group tab or in Raw JSON.
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}

function LlmSettingsSection({
  draft,
  setField,
  saveConfig,
}: {
  draft: Record<string, any>;
  setField: (key: string, value: any) => void;
  saveConfig: () => void;
}) {
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const providerPresets: Record<string, { endpoint: string; model: string }> = {
    nvidia: {
      endpoint: "https://integrate.api.nvidia.com/v1",
      model: "nvidia/nemotron-3-ultra-550b-a55b",
    },
    ollama: {
      endpoint: "http://localhost:11434/v1",
      model: "qwen2.5-coder",
    },
    openai: {
      endpoint: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
    },
    custom: {
      endpoint: draft.llm_endpoint || "http://localhost:8000/v1",
      model: draft.llm_model || "custom-model",
    },
  };

  const handleProviderSelect = (prov: string) => {
    setField("llm_provider", prov);
    if (providerPresets[prov]) {
      setField("llm_endpoint", providerPresets[prov].endpoint);
      setField("llm_model", providerPresets[prov].model);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      // Auto save draft first so backend gets current endpoint & key
      await saveConfig();
      const res = await fetch(apiUrl("/api/ai/test"), { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        setTestResult({ ok: true, msg: `Connected! Reply from model (${data.model}): "${data.reply}"` });
      } else {
        setTestResult({ ok: false, msg: data.error || "Connection failed" });
      }
    } catch (err: any) {
      setTestResult({ ok: false, msg: String(err.message || err) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>🤖 LLM Agent & Script Assistant Setup</h3>
      <p className="muted" style={{ marginBottom: 16 }}>
        Configure an LLM provider endpoint (NVIDIA NIM, Ollama, OpenAI, or Custom server) to enable the AI Script Copilot in the Scripts page.
      </p>

      <div className="settings-param">
        <div className="settings-param-header">
          <code style={{ color: "var(--accent)" }}>llm_provider</code>
          <span className="muted" style={{ fontSize: 12 }}>Provider Preset</span>
        </div>
        <div style={{ margin: "6px 0" }}>Choose LLM Provider Preset</div>
        <select
          className="settings-input"
          value={draft.llm_provider || "nvidia"}
          onChange={(e) => handleProviderSelect(e.target.value)}
        >
          <option value="nvidia">NVIDIA NIM (nvidia/nemotron-3-ultra-550b-a55b)</option>
          <option value="ollama">Ollama (Local / Robot Endpoint)</option>
          <option value="openai">OpenAI (GPT-4o / GPT-4o-mini)</option>
          <option value="custom">Custom OpenAI-compatible API</option>
        </select>
      </div>

      <div className="settings-param">
        <div className="settings-param-header">
          <code style={{ color: "var(--accent)" }}>llm_endpoint</code>
          <span className="muted" style={{ fontSize: 12 }}>Base URL</span>
        </div>
        <div style={{ margin: "6px 0" }}>Base URL Endpoint (OpenAI format)</div>
        <input
          className="settings-input"
          type="text"
          value={draft.llm_endpoint || ""}
          onChange={(e) => setField("llm_endpoint", e.target.value)}
          placeholder="https://integrate.api.nvidia.com/v1"
        />
      </div>

      <div className="settings-param">
        <div className="settings-param-header">
          <code style={{ color: "var(--accent)" }}>llm_model</code>
          <span className="muted" style={{ fontSize: 12 }}>Model Identifier</span>
        </div>
        <div style={{ margin: "6px 0" }}>LLM Model Name</div>
        <input
          className="settings-input"
          type="text"
          value={draft.llm_model || ""}
          onChange={(e) => setField("llm_model", e.target.value)}
          placeholder="nvidia/nemotron-3-ultra-550b-a55b"
        />
      </div>

      <div className="settings-param">
        <div className="settings-param-header">
          <code style={{ color: "var(--accent)" }}>llm_api_key</code>
          <span className="muted" style={{ fontSize: 12 }}>Secret API Key</span>
        </div>
        <div style={{ margin: "6px 0" }}>API Key ($NVIDIA_API_KEY / Secret)</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="settings-input"
            type={showKey ? "text" : "password"}
            value={draft.llm_api_key || ""}
            onChange={(e) => setField("llm_api_key", e.target.value)}
            placeholder="nvapi-..."
            style={{ flex: 1 }}
          />
          <button
            type="button"
            className="btn"
            onClick={() => setShowKey(!showKey)}
          >
            {showKey ? "Hide" : "Show"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginTop: 16, alignItems: "center" }}>
        <button
          type="button"
          className="btn primary"
          onClick={runTest}
          disabled={testing}
        >
          {testing ? "Testing..." : "⚡ Test Connection"}
        </button>
        {testResult && (
          <span
            style={{
              fontSize: 12,
              color: testResult.ok ? "var(--accent)" : "var(--danger)",
              fontFamily: "IBM Plex Mono, monospace",
            }}
          >
            {testResult.ok ? "✓ " : "❌ "}
            {testResult.msg}
          </span>
        )}
      </div>
    </div>
  );
}

