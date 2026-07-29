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

function SshPanel() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [draft, setDraft] = useState<Profile>({
    id: crypto.randomUUID(),
    host: "127.0.0.1",
    port: 22,
    user: "pi",
    auth: "password",
  });

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SSH_KEY);
      if (raw) setProfiles(JSON.parse(raw));
    } catch {
      /* ignore */
    }
  }, []);

  const persist = (next: Profile[]) => {
    setProfiles(next);
    localStorage.setItem(SSH_KEY, JSON.stringify(next));
  };

  return (
    <div style={{ padding: 16, display: "grid", gap: 16, maxWidth: 640 }}>
      <p className="muted" style={{ margin: 0 }}>
        Profiles stored in browser localStorage only (not on the robot).
      </p>
      <div className="kv">
        <div className="k">Host</div>
        <input
          className="btn"
          value={draft.host}
          onChange={(e) => setDraft({ ...draft, host: e.target.value })}
        />
        <div className="k">Port</div>
        <input
          className="btn"
          type="number"
          value={draft.port}
          onChange={(e) => setDraft({ ...draft, port: Number(e.target.value) })}
        />
        <div className="k">User</div>
        <input
          className="btn"
          value={draft.user}
          onChange={(e) => setDraft({ ...draft, user: e.target.value })}
        />
        <div className="k">Auth</div>
        <select
          className="btn"
          value={draft.auth}
          onChange={(e) =>
            setDraft({ ...draft, auth: e.target.value as Profile["auth"] })
          }
        >
          <option value="password">password</option>
          <option value="key">key</option>
        </select>
      </div>
      <button
        className="btn primary"
        onClick={() =>
          persist([...profiles, { ...draft, id: crypto.randomUUID() }])
        }
      >
        Save profile
      </button>
      <table className="table">
        <thead>
          <tr>
            <th>User@host</th>
            <th>Port</th>
            <th>Auth</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {profiles.map((p) => (
            <tr key={p.id}>
              <td>
                {p.user}@{p.host}
              </td>
              <td>{p.port}</td>
              <td>{p.auth}</td>
              <td>
                <button
                  className="btn danger"
                  onClick={() => persist(profiles.filter((x) => x.id !== p.id))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
