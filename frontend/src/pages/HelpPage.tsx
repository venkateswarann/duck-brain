import { useEffect, useState } from "react";
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

export default function HelpPage() {
  const [help, setHelp] = useState<HelpBundle | null>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    fetch(apiUrl("/api/help"))
      .then((r) => r.json())
      .then(setHelp)
      .catch(() => setErr("Could not load help metadata"));
  }, []);

  const groups = Array.from(
    new Set((help?.parameters || []).map((p) => p.group))
  );

  return (
    <div className="page">
      <div className="page-title">
        <span>Help</span>
        <div className="btn-row">
          <Link to="/settings" className="btn primary">
            ⚙ Settings
          </Link>
          <Link to="/setup" className="btn">
            🔧 Setup
          </Link>
        </div>
      </div>

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

      <div
        className="help-sections"
        style={{ display: "flex", flexDirection: "column", gap: 24, flex: 1, overflow: "auto" }}
      >
        {/* Getting Started */}
        <div className="panel" style={{ padding: 20 }}>
          <h3 style={{ marginTop: 0, color: "var(--accent)" }}>
            🚀 Getting Started
          </h3>
          <p className="muted" style={{ marginBottom: 16 }}>
            Prefer the CLI script for installing packages; use the{" "}
            <Link to="/settings" style={{ color: "var(--blue)" }}>
              Settings
            </Link>{" "}
            page to tune runtime parameters afterward. Use the{" "}
            <Link to="/setup" style={{ color: "var(--blue)" }}>
              Setup
            </Link>{" "}
            page for servo ID assignment and joint calibration.
          </p>
          <pre className="log-view" style={{ marginBottom: 16 }}>
            {`./scripts/setup.sh
./scripts/setup.sh -y --hardware --serial /dev/ttyACM0

# Robot-only (no frontend):
./scripts/setup_robot.sh

# PC frontend-only:
./scripts/setup_frontend.sh
./scripts/run_frontend.sh --backend-url http://<robot-ip>:8000`}
          </pre>
          {(help?.setup_steps || []).map((s) => (
            <div key={s.title} style={{ marginBottom: 14 }}>
              <strong>{s.title}</strong>
              <pre className="log-view" style={{ marginTop: 6 }}>
                {s.body}
              </pre>
            </div>
          ))}
        </div>

        {/* UI Pages Guide */}
        <div className="panel" style={{ padding: 20 }}>
          <h3 style={{ marginTop: 0, color: "var(--accent)" }}>
            📄 UI Pages Guide
          </h3>
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
        </div>

        {/* Parameter Reference */}
        <div className="panel" style={{ padding: 20 }}>
          <h3 style={{ marginTop: 0, color: "var(--accent)" }}>
            📖 Parameter Reference
          </h3>
          <p className="muted" style={{ marginBottom: 16 }}>
            All duck_config.json parameters. Edit these in the{" "}
            <Link to="/settings" style={{ color: "var(--blue)" }}>
              Settings
            </Link>{" "}
            page.
          </p>
          {groups.map((g) => (
            <div key={g} style={{ marginBottom: 20 }}>
              <h4
                style={{
                  color: "var(--blue)",
                  margin: "16px 0 8px",
                  borderBottom: "1px solid var(--border)",
                  paddingBottom: 6,
                }}
              >
                {g}
              </h4>
              {(help?.parameters || [])
                .filter((p) => p.group === g)
                .map((p) => (
                  <div
                    key={p.key}
                    style={{
                      marginBottom: 12,
                      paddingLeft: 12,
                      borderLeft: "2px solid var(--border)",
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
                    <div style={{ margin: "4px 0", fontSize: 14 }}>
                      {p.summary}
                    </div>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {p.details}
                    </div>
                  </div>
                ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
