import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiUrl, wsUrl } from "../config";
import WebTerminal, { type TerminalState } from "../components/WebTerminal";

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

/** Trim things people paste by habit: schemes, trailing slashes, user@ prefixes. */
function cleanHost(raw: string): string {
  let host = raw.trim();
  for (const prefix of ["ssh://", "http://", "https://"]) {
    if (host.toLowerCase().startsWith(prefix)) host = host.slice(prefix.length);
  }
  host = host.replace(/\/+$/, "").trim();
  if (host.includes("@")) host = host.slice(host.lastIndexOf("@") + 1);
  return host;
}

function SshPanel() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [draft, setDraft] = useState<Profile>({
    id: genId(),
    host: "",
    port: 22,
    user: "",
    auth: "password",
  });

  // Pending connection: waiting for the secret before opening the socket.
  const [pending, setPending] = useState<Profile | null>(null);
  const [password, setPassword] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");

  const [session, setSession] = useState<{
    profile: Profile;
    credentials: Record<string, unknown>;
    key: number;
  } | null>(null);
  const [state, setState] = useState<TerminalState>("connecting");
  const [message, setMessage] = useState("");
  const [available, setAvailable] = useState<boolean | null>(null);
  const [availableHint, setAvailableHint] = useState("");

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

  useEffect(() => {
    fetch(apiUrl("/api/terminal/capabilities"))
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => {
        if (!c) return;
        setAvailable(Boolean(c.ssh?.available));
        setAvailableHint(c.ssh?.hint || "");
      })
      .catch(() => setAvailable(null));
  }, []);

  const persist = (next: Profile[]) => {
    setProfiles(next);
    try {
      localStorage.setItem(SSH_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  const beginConnect = (profile: Profile) => {
    setSession(null);
    setPassword("");
    setPrivateKey("");
    setPassphrase("");
    setPending(profile);
  };

  const openSession = () => {
    if (!pending) return;
    const credentials: Record<string, unknown> =
      pending.auth === "password"
        ? { password }
        : { private_key: privateKey, passphrase: passphrase || undefined };

    setSession({
      profile: pending,
      credentials: {
        host: cleanHost(pending.host),
        port: pending.port,
        username: pending.user,
        ...credentials,
      },
      key: Date.now(),
    });
    setState("connecting");
    setMessage("");
    setPending(null);
    // Don't keep the secret in React state any longer than needed; the socket
    // payload already holds what it needs for this session.
    setPassword("");
    setPrivateKey("");
    setPassphrase("");
  };

  const canSave = cleanHost(draft.host).length > 0 && draft.user.trim().length > 0;

  return (
    <div style={{ padding: 16, display: "grid", gap: 20 }}>
      {available === false && (
        <div className="placeholder" style={{ color: "var(--danger)" }}>
          SSH support is unavailable on the backend. {availableHint}
        </div>
      )}

      <div
        style={{
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 16,
          maxWidth: 780,
        }}
      >
        <h4 style={{ marginTop: 0, marginBottom: 8, color: "var(--accent)" }}>SSH Profiles</h4>
        <p className="muted" style={{ margin: "0 0 12px 0", fontSize: 13 }}>
          Host, port and username are saved in browser local storage. Passwords and keys are never
          stored — you are asked for them each time you connect.
        </p>

        <div className="kv" style={{ padding: 0, marginBottom: 14 }}>
          <div className="k">Host</div>
          <input
            className="btn"
            value={draft.host}
            onChange={(e) => setDraft({ ...draft, host: e.target.value })}
            placeholder="10.9.9.45"
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
            placeholder="venki"
          />
          <div className="k">Auth method</div>
          <select
            className="btn"
            value={draft.auth}
            onChange={(e) => setDraft({ ...draft, auth: e.target.value as Profile["auth"] })}
          >
            <option value="password">Password</option>
            <option value="key">Private key</option>
          </select>
        </div>

        <button
          className="btn primary"
          disabled={!canSave}
          onClick={() => {
            const profile = { ...draft, host: cleanHost(draft.host), id: genId() };
            persist([...profiles, profile]);
            setDraft({ id: genId(), host: "", port: 22, user: "", auth: draft.auth });
          }}
        >
          + Save profile
        </button>
        {!canSave && (
          <span className="muted" style={{ marginLeft: 10, fontSize: 12 }}>
            Host and username are required.
          </span>
        )}
      </div>

      <div style={{ maxWidth: 780 }}>
        <h4 style={{ marginTop: 0, marginBottom: 8 }}>Saved targets</h4>
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
                <td>{p.auth === "password" ? "Password" : "Private key"}</td>
                <td>
                  <div className="btn-row">
                    <button className="btn primary" onClick={() => beginConnect(p)}>
                      Connect
                    </button>
                    <button
                      className="btn danger"
                      onClick={() => {
                        if (session?.profile.id === p.id) setSession(null);
                        if (pending?.id === p.id) setPending(null);
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

      {pending && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            openSession();
          }}
          style={{
            background: "var(--bg-panel)",
            border: "1px solid var(--accent)",
            borderRadius: 8,
            padding: 16,
            maxWidth: 780,
          }}
        >
          <h4 style={{ marginTop: 0, marginBottom: 10, color: "var(--accent)" }}>
            Authenticate — {pending.user}@{cleanHost(pending.host)}:{pending.port}
          </h4>

          {pending.auth === "password" ? (
            <label style={{ display: "block", fontSize: 13 }}>
              <div className="muted" style={{ marginBottom: 4 }}>
                Password for {pending.user}
              </div>
              <input
                className="btn"
                type="password"
                autoFocus
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{ width: "100%", maxWidth: 360 }}
              />
            </label>
          ) : (
            <>
              <label style={{ display: "block", fontSize: 13, marginBottom: 10 }}>
                <div className="muted" style={{ marginBottom: 4 }}>
                  Private key (paste the contents of e.g. ~/.ssh/id_ed25519)
                </div>
                <textarea
                  className="btn"
                  autoFocus
                  value={privateKey}
                  onChange={(e) => setPrivateKey(e.target.value)}
                  rows={6}
                  spellCheck={false}
                  placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                />
              </label>
              <label style={{ display: "block", fontSize: 13 }}>
                <div className="muted" style={{ marginBottom: 4 }}>
                  Key passphrase (leave blank if unencrypted)
                </div>
                <input
                  className="btn"
                  type="password"
                  autoComplete="off"
                  value={passphrase}
                  onChange={(e) => setPassphrase(e.target.value)}
                  style={{ width: "100%", maxWidth: 360 }}
                />
              </label>
            </>
          )}

          <div className="btn-row" style={{ marginTop: 14 }}>
            <button className="btn primary" type="submit">
              Connect
            </button>
            <button className="btn" type="button" onClick={() => setPending(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {session && (
        <div
          style={{
            background: "#05080c",
            border: "1px solid var(--border)",
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "8px 12px",
              borderBottom: "1px solid var(--border)",
              background: "var(--bg-panel)",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
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
              <strong>
                {session.profile.user}@{cleanHost(session.profile.host)}:{session.profile.port}
              </strong>
              <span className="muted">{message || state}</span>
            </span>
            <div className="btn-row">
              <button
                className="btn"
                onClick={() => setSession({ ...session, key: Date.now() })}
                title="Close and reopen the shell"
              >
                Reconnect
              </button>
              <button className="btn danger" onClick={() => setSession(null)}>
                Disconnect
              </button>
            </div>
          </div>
          <div style={{ height: 460, padding: 8 }}>
            <WebTerminal
              url={wsUrl("/ws/ssh")}
              connect={session.credentials}
              sessionKey={session.key}
              onState={(s, m) => {
                setState(s);
                setMessage(m);
              }}
            />
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
