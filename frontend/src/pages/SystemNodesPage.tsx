import { useEffect, useState } from "react";
import { apiUrl } from "../config";

type NodeInfo = {
  id: string;
  name: string;
  kind: string;
  state: string;
  pid?: number;
  cpu_percent: number;
  memory_mib: number;
  open_files: number;
  host: string;
  error?: string;
  resources: string[];
  config: Record<string, unknown>;
};

const TABS = ["General", "Runtime", "Log", "Config"] as const;

export default function SystemNodesPage() {
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("General");
  const [logs, setLogs] = useState<string[]>([]);

  const refresh = () =>
    fetch(apiUrl("/api/nodes"))
      .then((r) => r.json())
      .then((data: NodeInfo[]) => {
        setNodes(data);
        if (!selected && data.length) setSelected(data[0].id);
      })
      .catch(() => undefined);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 1500);
    return () => window.clearInterval(t);
  }, [selected]);

  useEffect(() => {
    if (!selected || tab !== "Log") return;
    fetch(apiUrl(`/api/nodes/${selected}/logs`))
      .then((r) => r.json())
      .then((d) => setLogs(d.lines || []))
      .catch(() => undefined);
    const t = window.setInterval(() => {
      fetch(apiUrl(`/api/nodes/${selected}/logs`))
        .then((r) => r.json())
        .then((d) => setLogs(d.lines || []))
        .catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(t);
  }, [selected, tab]);

  const node = nodes.find((n) => n.id === selected);

  const act = async (action: string) => {
    if (!selected) return;
    await fetch(apiUrl(`/api/nodes/${selected}/${action}`), { method: "POST" });
    refresh();
  };

  return (
    <div className="page">
      <div className="page-title">
        <span>System / Nodes</span>
        <span className="muted">Kill a node to tear down its outputs</span>
      </div>
      <div className="split split-2">
        <div className="panel">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>CPU</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((n) => (
                <tr
                  key={n.id}
                  className={n.id === selected ? "selected" : ""}
                  onClick={() => setSelected(n.id)}
                >
                  <td>
                    <span className={`status-dot status-${n.state}`} />
                    {n.name}
                    <div className="muted" style={{ fontSize: 11 }}>
                      {n.id}
                    </div>
                  </td>
                  <td>{n.cpu_percent.toFixed(1)}%</td>
                  <td className="muted">{n.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
          <div className="page-title" style={{ border: "none" }}>
            <span>{node?.name ?? "Select a node"}</span>
            <div className="btn-row">
              <button className="btn primary" onClick={() => act("start")}>
                Start
              </button>
              <button className="btn" onClick={() => act("stop")}>
                Stop
              </button>
              <button className="btn" onClick={() => act("restart")}>
                Restart
              </button>
              <button className="btn danger" onClick={() => act("kill")}>
                Kill
              </button>
            </div>
          </div>
          <div className="tabs">
            {TABS.map((t) => (
              <button
                key={t}
                className={`tab${tab === t ? " active" : ""}`}
                onClick={() => setTab(t)}
              >
                {t}
              </button>
            ))}
          </div>
          <div style={{ flex: 1, overflow: "auto" }}>
            {!node && <div className="placeholder">No node selected</div>}
            {node && tab === "General" && (
              <div className="kv">
                <div className="k">PID</div>
                <div>{node.pid ?? "—"}</div>
                <div className="k">Host</div>
                <div>{node.host}</div>
                <div className="k">CPU usage</div>
                <div>{node.cpu_percent}%</div>
                <div className="k">Memory usage</div>
                <div>{node.memory_mib} MiB</div>
                <div className="k">Open files</div>
                <div>{node.open_files}</div>
                <div className="k">Resources</div>
                <div>{node.resources.join(", ") || "—"}</div>
                <div className="k">Error</div>
                <div>{node.error || "—"}</div>
              </div>
            )}
            {node && tab === "Runtime" && (
              <div className="kv">
                <div className="k">Kind</div>
                <div>{node.kind}</div>
                <div className="k">State</div>
                <div>{node.state}</div>
              </div>
            )}
            {node && tab === "Log" && (
              <div className="log-view">{logs.join("\n") || "(no logs)"}</div>
            )}
            {node && tab === "Config" && (
              <pre className="log-view">{JSON.stringify(node.config, null, 2)}</pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
