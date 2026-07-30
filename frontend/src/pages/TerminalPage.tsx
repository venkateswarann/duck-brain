import { useEffect, useState } from "react";
import { apiUrl, wsUrl } from "../config";
import WebTerminal, { type TerminalState } from "../components/WebTerminal";

interface Capability {
  available: boolean;
  allow_web_terminal: boolean;
  env_flag: boolean;
  hint: string;
}

export default function TerminalPage() {
  const [cap, setCap] = useState<Capability | null>(null);
  const [session, setSession] = useState(0);
  const [state, setState] = useState<TerminalState>("connecting");
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch(apiUrl("/api/terminal/capabilities"))
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => c && setCap(c.local_pty))
      .catch(() => setCap(null));
  }, []);

  if (cap && !cap.available) {
    return (
      <div className="page">
        <div className="page-title">
          <span>Terminal</span>
          <span className="muted">Disabled</span>
        </div>
        <div className="placeholder">
          <p style={{ marginTop: 0 }}>
            The local shell is off by default: unlike the SSH terminal it needs no credentials, so
            anyone who can reach this port would get a shell as the backend user.
          </p>
          <p>To enable it, both of these must be true:</p>
          <ol style={{ textAlign: "left", display: "inline-block", margin: "8px 0" }}>
            <li>
              <code>allow_web_terminal: true</code> in <code>configs/duck_config.json</code>
              {cap.allow_web_terminal ? " ✓" : " — currently false"}
            </li>
            <li>
              <code>ALLOW_WEB_TERMINAL=1</code> in the backend environment
              {cap.env_flag ? " ✓" : " — currently unset"}
            </li>
          </ol>
          <p className="muted" style={{ fontSize: 13 }}>
            e.g. <code>ALLOW_WEB_TERMINAL=1 ./scripts/run.sh</code>
          </p>
          <p className="muted" style={{ fontSize: 13 }}>
            For remote machines use the SSH terminal on the Connections page instead.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-title">
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background:
                state === "connected"
                  ? "var(--accent)"
                  : state === "error"
                    ? "var(--danger)"
                    : "var(--muted)",
            }}
          />
          Terminal — local shell
          <span className="muted" style={{ fontSize: 12 }}>
            {message || state}
          </span>
        </span>
        <div className="btn-row">
          <button className="btn" onClick={() => setSession((n) => n + 1)}>
            New session
          </button>
        </div>
      </div>
      <div
        className="panel"
        style={{ height: "calc(100vh - 150px)", padding: 8, background: "#05080c" }}
      >
        {cap && (
          <WebTerminal
            url={wsUrl("/ws/pty")}
            sessionKey={session}
            onState={(s, m) => {
              setState(s);
              setMessage(m);
            }}
          />
        )}
      </div>
    </div>
  );
}
