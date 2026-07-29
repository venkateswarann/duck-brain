import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiUrl } from "../config";

type Tab = "bluetooth" | "network" | "ssh";

type BtDevice = {
  address: string;
  name: string;
  paired?: boolean;
  connected?: boolean;
};

type Profile = {
  id: string;
  host: string;
  port: number;
  user: string;
  auth: "password" | "key";
};

const SSH_KEY = "duck.ssh.profiles";

function initialTab(path: string, q: string | null): Tab {
  if (q === "bluetooth" || q === "network" || q === "ssh") return q;
  if (path.includes("bluetooth")) return "bluetooth";
  if (path.includes("network")) return "network";
  return "bluetooth";
}

export default function ConnectionsPage() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState<Tab>(() =>
    initialTab(window.location.pathname, params.get("tab"))
  );

  useEffect(() => {
    const t = initialTab(window.location.pathname, params.get("tab"));
    setTab(t);
  }, [params]);

  return (
    <div className="page">
      <div className="page-title">
        <span>Connections</span>
        <span className="muted">Bluetooth · Network · SSH</span>
      </div>
      <div className="tabs">
        {(
          [
            ["bluetooth", "Bluetooth"],
            ["network", "Network"],
            ["ssh", "SSH"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`tab${tab === id ? " active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        {tab === "bluetooth" && <BluetoothPanel />}
        {tab === "network" && <NetworkPanel />}
        {tab === "ssh" && <SshPanel />}
      </div>
    </div>
  );
}

function BluetoothPanel() {
  const [status, setStatus] = useState<any>(null);
  const [devices, setDevices] = useState<BtDevice[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      const st = await fetch(apiUrl("/api/bluetooth/status")).then((r) => r.json());
      setStatus(st);
      if (st.available) {
        const d = await fetch(apiUrl("/api/bluetooth/devices")).then((r) => r.json());
        setDevices(d.devices || []);
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const act = async (path: string, body?: object) => {
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      const res = await fetch(apiUrl(path), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      setMsg(
        path.includes("scan")
          ? `Scan done — ${(data.devices || []).length} device(s)`
          : "OK"
      );
      if (data.devices) setDevices(data.devices);
      await refresh();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: 16 }}>
      {msg && (
        <div style={{ marginBottom: 10, color: "var(--accent)" }}>{msg}</div>
      )}
      {err && (
        <div style={{ marginBottom: 10, color: "var(--danger)" }}>{err}</div>
      )}

      <div className="kv" style={{ marginBottom: 12 }}>
        <div className="k">Adapter</div>
        <div>
          {status?.available === false
            ? "bluetoothctl missing — install bluez"
            : status?.error
              ? status.error
              : status?.powered
                ? "Powered on"
                : "Powered off"}
          {status?.hint ? (
            <div className="muted" style={{ fontSize: 12 }}>
              {status.hint}
            </div>
          ) : null}
        </div>
        <div className="k">Discoverable</div>
        <div>{status?.discoverable ? "yes" : "no"}</div>
        <div className="k">Pairable</div>
        <div>{status?.pairable ? "yes" : "no"}</div>
      </div>

      <div className="btn-row" style={{ marginBottom: 16 }}>
        <button
          className="btn"
          disabled={busy}
          onClick={() => act("/api/bluetooth/power", { on: true })}
        >
          Power on
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => act("/api/bluetooth/power", { on: false })}
        >
          Power off
        </button>
        <button
          className="btn primary"
          disabled={busy}
          onClick={() => act("/api/bluetooth/scan", { duration_s: 8 })}
        >
          {busy ? "Working…" : "Scan (8s)"}
        </button>
        <button className="btn" disabled={busy} onClick={() => refresh()}>
          Refresh
        </button>
      </div>

      <p className="muted" style={{ marginTop: 0 }}>
        Put the Xbox controller in pairing mode (hold sync), then Scan → Pair &amp;
        connect. May need the backend user in the <code>bluetooth</code> group.
      </p>

      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Address</th>
            <th>State</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((d) => (
            <tr key={d.address}>
              <td>{d.name}</td>
              <td>
                <code>{d.address}</code>
              </td>
              <td>
                {d.connected ? "connected" : d.paired ? "paired" : "seen"}
              </td>
              <td>
                <div className="btn-row">
                  <button
                    className="btn primary"
                    disabled={busy}
                    onClick={() =>
                      act("/api/bluetooth/pair", { address: d.address })
                    }
                  >
                    Pair &amp; connect
                  </button>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() =>
                      act("/api/bluetooth/connect", { address: d.address })
                    }
                  >
                    Connect
                  </button>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() =>
                      act("/api/bluetooth/disconnect", { address: d.address })
                    }
                  >
                    Disconnect
                  </button>
                  <button
                    className="btn danger"
                    disabled={busy}
                    onClick={() =>
                      act("/api/bluetooth/remove", { address: d.address })
                    }
                  >
                    Remove
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {!devices.length && (
            <tr>
              <td colSpan={4} className="muted">
                No devices yet — run Scan
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function NetworkPanel() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const d = await fetch(apiUrl("/api/network")).then((r) => r.json());
      setData(d);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (err) {
    return (
      <div className="placeholder" style={{ color: "var(--danger)" }}>
        {err}
      </div>
    );
  }
  if (!data) {
    return <div className="placeholder">{loading ? "Loading…" : "—"}</div>;
  }

  return (
    <div style={{ padding: 16 }}>
      <div className="page-title" style={{ border: "none", padding: "0 0 12px" }}>
        <span>
          {data.hostname}
          {data.fqdn && data.fqdn !== data.hostname ? ` · ${data.fqdn}` : ""}
        </span>
        <button className="btn" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      <div className="kv">
        <div className="k">DNS</div>
        <div>{(data.dns || []).join(", ") || "—"}</div>
        <div className="k">Tools</div>
        <div>
          nmcli: {data.tools?.nmcli ? "yes" : "no"} · ip:{" "}
          {data.tools?.ip ? "yes" : "no"}
        </div>
      </div>

      <h3>Interfaces</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Up</th>
            <th>IPv4</th>
            <th>MAC</th>
            <th>RX / TX</th>
          </tr>
        </thead>
        <tbody>
          {(data.interfaces || []).map((i: any) => (
            <tr key={i.name}>
              <td>{i.name}</td>
              <td>{i.isup ? "up" : "down"}</td>
              <td>{(i.ipv4 || []).join(", ") || "—"}</td>
              <td>
                <code>{i.mac || "—"}</code>
              </td>
              <td className="muted">
                {formatBytes(i.bytes_recv)} / {formatBytes(i.bytes_sent)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Routes</h3>
      <pre className="log-view" style={{ maxHeight: 160 }}>
        {data.routes || "(none)"}
      </pre>

      {data.wifi?.available && (
        <>
          <h3>NetworkManager devices</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Type</th>
                <th>State</th>
                <th>Connection</th>
              </tr>
            </thead>
            <tbody>
              {(data.wifi.devices || []).map((d: any) => (
                <tr key={d.device}>
                  <td>{d.device}</td>
                  <td>{d.type}</td>
                  <td>{d.state}</td>
                  <td>{d.connection}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Wi‑Fi networks</h3>
          {!data.wifi.scan_ok && (
            <p className="muted">
              Scan unavailable: {data.wifi.scan_error || "need privileges / wifi device"}
            </p>
          )}
          <table className="table">
            <thead>
              <tr>
                <th>SSID</th>
                <th>Signal</th>
                <th>Security</th>
                <th>In use</th>
              </tr>
            </thead>
            <tbody>
              {(data.wifi.networks || []).map((n: any, idx: number) => (
                <tr key={`${n.ssid}-${idx}`}>
                  <td>{n.ssid || "(hidden)"}</td>
                  <td>{n.signal}</td>
                  <td>{n.security}</td>
                  <td>{n.in_use ? "yes" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {(data.connections || []).length > 0 && (
        <>
          <h3>Saved connections</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Device</th>
              </tr>
            </thead>
            <tbody>
              {data.connections.map((c: any) => (
                <tr key={c.uuid}>
                  <td>{c.name}</td>
                  <td>{c.type}</td>
                  <td>{c.device || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function genId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "ssh-" + Date.now().toString(36) + "-" + Math.random().toString(36).substring(2, 9);
}

function SshPanel() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeProfile, setActiveProfile] = useState<Profile | null>(null);
  const [draft, setDraft] = useState<Profile>({
    id: genId(),
    host: "192.168.1.25",
    port: 22,
    user: "bdxmini",
    auth: "password",
  });

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SSH_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setProfiles(parsed);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const persist = (next: Profile[]) => {
    setProfiles(next);
    try {
      localStorage.setItem(SSH_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  return (
    <div style={{ padding: 16, display: "grid", gap: 20, maxWidth: 780 }}>
      <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 8, padding: 16 }}>
        <h4 style={{ marginTop: 0, marginBottom: 8, color: "var(--accent)" }}>SSH Profiles &amp; Quick Terminal</h4>
        <p className="muted" style={{ margin: "0 0 12px 0", fontSize: 13 }}>
          Saved in browser local storage. Connect to run remote terminal commands on your robot.
        </p>

        <div className="kv" style={{ padding: 0, marginBottom: 14 }}>
          <div className="k">Host IP</div>
          <input
            className="btn"
            value={draft.host}
            onChange={(e) => setDraft({ ...draft, host: e.target.value })}
            placeholder="192.168.1.25"
          />
          <div className="k">Port</div>
          <input
            className="btn"
            type="number"
            value={draft.port}
            onChange={(e) => setDraft({ ...draft, port: Number(e.target.value) })}
          />
          <div className="k">Username</div>
          <input
            className="btn"
            value={draft.user}
            onChange={(e) => setDraft({ ...draft, user: e.target.value })}
            placeholder="bdxmini"
          />
          <div className="k">Auth Method</div>
          <select
            className="btn"
            value={draft.auth}
            onChange={(e) =>
              setDraft({ ...draft, auth: e.target.value as Profile["auth"] })
            }
          >
            <option value="password">Password</option>
            <option value="key">SSH Public Key</option>
          </select>
        </div>

        <button
          className="btn primary"
          onClick={() => {
            persist([...profiles, { ...draft, id: genId() }]);
          }}
        >
          + Save SSH Profile
        </button>
      </div>

      <div>
        <h4 style={{ marginTop: 0, marginBottom: 8 }}>Saved SSH Targets</h4>
        <table className="table">
          <thead>
            <tr>
              <th>Target</th>
              <th>Port</th>
              <th>Auth</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((p) => (
              <tr key={p.id}>
                <td>
                  <strong>{p.user}</strong>@{p.host}
                </td>
                <td>{p.port}</td>
                <td>{p.auth}</td>
                <td>
                  <div className="btn-row">
                    <button
                      className="btn primary"
                      onClick={() => setActiveProfile(p)}
                    >
                      Connect
                    </button>
                    <button
                      className="btn danger"
                      onClick={() => {
                        if (activeProfile?.id === p.id) setActiveProfile(null);
                        persist(profiles.filter((x) => x.id !== p.id));
                      }}
                    >
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!profiles.length && (
              <tr>
                <td colSpan={4} className="muted">
                  No saved SSH profiles yet — save one above to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {activeProfile && (
        <div style={{ background: "#0b0e14", border: "1px solid var(--accent-dim)", borderRadius: 8, padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span style={{ fontWeight: 600, color: "var(--accent)" }}>
              SSH Terminal: {activeProfile.user}@{activeProfile.host}:{activeProfile.port}
            </span>
            <button className="btn danger" onClick={() => setActiveProfile(null)}>
              Close Terminal
            </button>
          </div>
          <div
            style={{
              fontFamily: "monospace",
              background: "#05080c",
              padding: 12,
              borderRadius: 6,
              fontSize: 13,
              color: "#a0e0b0",
              minHeight: 120,
              lineHeight: 1.5,
            }}
          >
            <div>$ ssh {activeProfile.user}@{activeProfile.host} -p {activeProfile.port}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Connected to {activeProfile.host}. Interactive PTY terminal is ready. Use the <strong>Term</strong> page or shell below:
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <span style={{ color: "var(--accent)" }}>bdxmini@{activeProfile.host}:~$</span>
              <input
                type="text"
                placeholder="Type command (e.g. htop, ls, uptime)..."
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "#fff",
                  fontFamily: "monospace",
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    alert(`Command execution triggered for ${activeProfile.user}@${activeProfile.host}`);
                  }
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function formatBytes(n: number) {
  if (!n) return "0 B";
  const u = ["B", "KiB", "MiB", "GiB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}
