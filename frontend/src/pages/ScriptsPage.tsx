import Editor from "@monaco-editor/react";
import { useEffect, useState } from "react";
import { apiUrl } from "../config";

type ScriptItem = {
  name: string;
  node_id: string;
  display_name: string;
  description: string;
  resources: string[];
  state: string;
};

export default function ScriptsPage() {
  const [scripts, setScripts] = useState<ScriptItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

  const refresh = () =>
    fetch(apiUrl("/api/scripts"))
      .then((r) => r.json())
      .then((data: ScriptItem[]) => {
        setScripts(data);
        if (!selected && data.length) setSelected(data[0].name);
      });

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 2000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetch(apiUrl(`/api/scripts/${selected}`))
      .then((r) => r.json())
      .then((d) => {
        setContent(d.content || "");
        setDirty(false);
      });
  }, [selected]);

  useEffect(() => {
    if (!selected) return;
    const nodeId = `script.${selected.replace(/\.py$/, "")}`;
    const t = window.setInterval(() => {
      fetch(apiUrl(`/api/nodes/${nodeId}/logs`))
        .then((r) => r.json())
        .then((d) => setLogs(d.lines || []))
        .catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(t);
  }, [selected]);

  const save = async () => {
    if (!selected) return;
    await fetch(apiUrl(`/api/scripts/${selected}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    setDirty(false);
  };

  const run = async () => {
    if (!selected) return;
    if (dirty) await save();
    await fetch(apiUrl(`/api/scripts/${selected}/run`), { method: "POST" });
    refresh();
  };

  const stop = async () => {
    if (!selected) return;
    await fetch(apiUrl(`/api/scripts/${selected}/stop`), { method: "POST" });
    refresh();
  };

  const current = scripts.find((s) => s.name === selected);

  return (
    <div className="page">
      <div className="page-title">
        <span>Scripts</span>
        <div className="btn-row">
          <button className="btn" onClick={save} disabled={!dirty}>
            Save
          </button>
          <button className="btn primary" onClick={run}>
            Run
          </button>
          <button className="btn danger" onClick={stop}>
            Stop
          </button>
        </div>
      </div>
      <div className="split" style={{ gridTemplateColumns: "240px 1fr", flex: 1 }}>
        <div className="panel motor-list">
          {scripts.map((s) => (
            <button
              key={s.name}
              className={s.name === selected ? "active" : ""}
              onClick={() => setSelected(s.name)}
            >
              <div>
                <span className={`status-dot status-${s.state}`} />
                {s.display_name}
              </div>
              <div className="muted" style={{ fontSize: 11 }}>
                {s.name} · {s.resources.join(",") || "no lock"}
              </div>
            </button>
          ))}
        </div>
        <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
          <div className="muted" style={{ padding: "8px 12px" }}>
            {current?.description || ""} {dirty ? "· unsaved" : ""}
          </div>
          <div style={{ flex: 1, minHeight: 280 }}>
            <Editor
              height="100%"
              theme="vs-dark"
              language="python"
              value={content}
              onChange={(v) => {
                setContent(v ?? "");
                setDirty(true);
              }}
              options={{ minimap: { enabled: false }, fontSize: 13 }}
            />
          </div>
          <div
            className="log-view"
            style={{ height: 160, borderTop: "1px solid var(--border)" }}
          >
            {logs.join("\n") || "(logs)"}
          </div>
        </div>
      </div>
    </div>
  );
}
