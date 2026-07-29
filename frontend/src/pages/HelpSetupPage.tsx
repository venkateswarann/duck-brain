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

type HelpBundle = {
  parameters: HelpParam[];
  pages: { page: string; path: string; blurb: string }[];
  setup_steps: { title: string; body: string }[];
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
  "allow_script_runner",
  "allow_web_terminal",
] as const;

export default function HelpSetupPage() {
  const [help, setHelp] = useState<HelpBundle | null>(null);
  const [cfg, setCfg] = useState<DuckConfig | null>(null);
  const [draft, setDraft] = useState<DuckConfig | null>(null);
  const [group, setGroup] = useState<string>("Robot");
  const [msg, setMsg] = useState<string>("");
  const [err, setErr] = useState<string>("");
  const [saving, setSaving] = useState(false);

  const load = () => {
    fetch(apiUrl("/api/help"))
      .then((r) => r.json())
      .then(setHelp)
      .catch(() => setErr("Could not load help metadata"));
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

  const groups = useMemo(() => {
    const g = new Set((help?.parameters || []).map((p) => p.group));
    return Array.from(g);
  }, [help]);

  useEffect(() => {
    if (groups.length && !groups.includes(group)) setGroup(groups[0]);
  }, [groups, group]);

  const paramsInGroup = (help?.parameters || []).filter((p) => p.group === group);

  const setField = (key: string, value: unknown) => {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
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

  return (
    <div className="page">
      <div className="page-title">
        <span>Help / Setup</span>
        <div className="btn-row">
          <button className="btn" onClick={resetDraft}>
            Reset
          </button>
          <button className="btn primary" onClick={save} disabled={saving || !draft}>
            {saving ? "Saving…" : "Save config"}
          </button>
        </div>
      </div>

      <div className="split" style={{ gridTemplateColumns: "220px 1fr", flex: 1 }}>
        <div className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ marginBottom: 8 }}>
            Topics
          </div>
          {["Setup", ...groups, "Pages", "JSON"].map((g) => (
            <button
              key={g}
              type="button"
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "8px 10px",
                marginBottom: 4,
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: group === g ? "#222b3c" : "transparent",
                color: "inherit",
                cursor: "pointer",
              }}
              onClick={() => setGroup(g)}
            >
              {g}
            </button>
          ))}
        </div>

        <div className="panel" style={{ padding: 16, overflow: "auto" }}>
          {msg && (
            <div
              style={{
                marginBottom: 12,
                padding: 10,
                borderRadius: 6,
                background: "#143528",
                color: "var(--accent)",
              }}
            >
              {msg}
            </div>
          )}
          {err && (
            <div
              style={{
                marginBottom: 12,
                padding: 10,
                borderRadius: 6,
                background: "#4a1f24",
                color: "var(--danger)",
              }}
            >
              {err}
            </div>
          )}

          {group === "Setup" && (
            <>
              <h3 style={{ marginTop: 0 }}>First-time setup</h3>
              <p className="muted">
                Prefer the CLI script for installing packages; use this page to tune
                runtime parameters afterward.
              </p>
              <pre className="log-view" style={{ marginBottom: 16 }}>
                {`./scripts/setup.sh
./scripts/setup.sh -y --hardware --serial /dev/ttyACM0`}
              </pre>
              {(help?.setup_steps || []).map((s) => (
                <div key={s.title} style={{ marginBottom: 14 }}>
                  <strong>{s.title}</strong>
                  <pre className="log-view" style={{ marginTop: 6 }}>
                    {s.body}
                  </pre>
                </div>
              ))}
            </>
          )}

          {group === "Pages" && (
            <>
              <h3 style={{ marginTop: 0 }}>UI map</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Page</th>
                    <th>What it does</th>
                  </tr>
                </thead>
                <tbody>
                  {(help?.pages || []).map((p) => (
                    <tr key={p.path}>
                      <td>
                        <Link to={p.path} style={{ color: "var(--blue)" }}>
                          {p.page}
                        </Link>
                      </td>
                      <td className="muted">{p.blurb}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {group === "JSON" && draft && (
            <>
              <h3 style={{ marginTop: 0 }}>Raw duck_config</h3>
              <p className="muted">
                Advanced: edit JSON then Save. Invalid JSON fields are rejected by the
                API.
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

          {group !== "Setup" &&
            group !== "Pages" &&
            group !== "JSON" &&
            paramsInGroup.map((p) => {
              const editable = EDITABLE.includes(p.key as (typeof EDITABLE)[number]);
              const value = draft ? draft[p.key] : undefined;
              return (
                <div
                  key={p.key}
                  style={{
                    marginBottom: 18,
                    paddingBottom: 16,
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      alignItems: "baseline",
                    }}
                  >
                    <code style={{ color: "var(--accent)" }}>{p.key}</code>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {p.type}
                      {p.default !== undefined
                        ? ` · default ${JSON.stringify(p.default)}`
                        : ""}
                    </span>
                  </div>
                  <div style={{ margin: "6px 0" }}>{p.summary}</div>
                  <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
                    {p.details}
                  </div>

                  {editable && draft && p.type === "bool" && (
                    <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input
                        type="checkbox"
                        checked={!!value}
                        onChange={(e) => setField(p.key, e.target.checked)}
                      />
                      {value ? "enabled" : "disabled"}
                    </label>
                  )}
                  {editable && draft && p.type === "enum" && (
                    <select
                      className="btn"
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
                      p.type === "float") && (
                      <input
                        className="btn"
                        style={{ minWidth: 280 }}
                        type={p.type === "string" ? "text" : "number"}
                        step={p.type === "float" ? "any" : "1"}
                        value={value ?? ""}
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (p.type === "string") setField(p.key, raw);
                          else if (p.type === "int")
                            setField(p.key, Number.parseInt(raw, 10) || 0);
                          else setField(p.key, Number.parseFloat(raw) || 0);
                        }}
                      />
                    )}
                  {!editable && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      Edit under JSON tab or in{" "}
                      <code>configs/duck_config.json</code> (joints / scales /
                      keymap).
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
