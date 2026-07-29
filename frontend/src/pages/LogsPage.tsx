import { useEffect, useRef, useState } from "react";
import { apiUrl, wsUrl } from "../config";

interface LogEntry {
  ts: number;
  node_id: string;
  line: string;
  level: "INFO" | "WARN" | "ERROR";
}

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [selectedNode, setSelectedNode] = useState<string>("ALL");
  const [selectedLevel, setSelectedLevel] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [connected, setConnected] = useState<boolean>(false);

  const consoleEndRef = useRef<HTMLDivElement>(null);

  // Initial fetch + WebSocket stream
  useEffect(() => {
    // 1. Fetch initial log history
    fetch(apiUrl("/api/logs/all?limit=500"))
      .then((res) => (res.ok ? res.json() : { logs: [] }))
      .then((data) => {
        if (Array.isArray(data.logs)) {
          setLogs(data.logs);
        }
      })
      .catch(() => {});

    // 2. Subscribe to live WebSocket log stream
    const socket = new WebSocket(wsUrl("/ws/logs/all"));

    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);

    socket.onmessage = (event) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        if (entry && entry.line) {
          setLogs((prev) => {
            const next = [...prev, entry];
            return next.length > 2000 ? next.slice(-2000) : next;
          });
        }
      } catch {
        /* ignore invalid frame */
      }
    };

    return () => {
      socket.close();
    };
  }, []);

  // Auto scroll to bottom
  useEffect(() => {
    if (autoScroll && consoleEndRef.current) {
      consoleEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, autoScroll]);

  // Unique list of nodes from log entries
  const availableNodes = Array.from(new Set(logs.map((l) => l.node_id))).sort();

  // Filtered log list
  const filteredLogs = logs.filter((l) => {
    if (selectedNode !== "ALL" && l.node_id !== selectedNode) return false;
    if (selectedLevel !== "ALL" && l.level !== selectedLevel) return false;
    if (
      searchQuery &&
      !l.line.toLowerCase().includes(searchQuery.toLowerCase()) &&
      !l.node_id.toLowerCase().includes(searchQuery.toLowerCase())
    ) {
      return false;
    }
    return true;
  });

  const clearLogs = () => setLogs([]);

  const copyLogs = () => {
    const text = filteredLogs
      .map(
        (l) =>
          `[${new Date(l.ts * 1000).toISOString()}] [${l.node_id}] [${l.level}] ${l.line}`
      )
      .join("\n");
    navigator.clipboard.writeText(text);
    alert("Logs copied to clipboard!");
  };

  return (
    <div className="page">
      {/* Title Bar */}
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Central System &amp; Script Console</span>
          <span className={`status-dot ${connected ? "status-running" : "status-error"}`} />
          <span className="muted" style={{ fontSize: 13 }}>
            {connected ? "LIVE WebSocket Stream" : "Reconnecting…"} · {filteredLogs.length} entries
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={copyLogs}>
            Copy Logs
          </button>
          <button className="btn danger" onClick={clearLogs}>
            Clear Console
          </button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 16,
          padding: "10px 16px",
          background: "var(--bg-panel)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {/* Node Filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Source Node:</span>
          <select
            value={selectedNode}
            onChange={(e) => setSelectedNode(e.target.value)}
            style={{
              background: "#121820",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "4px 8px",
              fontSize: 12,
            }}
          >
            <option value="ALL">All Nodes &amp; Scripts</option>
            {availableNodes.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>

        {/* Level Filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Severity:</span>
          {["ALL", "INFO", "WARN", "ERROR"].map((lvl) => (
            <button
              key={lvl}
              className={`btn ${selectedLevel === lvl ? "primary" : ""}`}
              style={{ padding: "3px 8px", fontSize: 12 }}
              onClick={() => setSelectedLevel(lvl)}
            >
              {lvl}
            </button>
          ))}
        </div>

        {/* Keyword Search */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, minWidth: 200 }}>
          <span className="muted" style={{ fontSize: 12 }}>Search:</span>
          <input
            type="text"
            className="btn"
            style={{ flex: 1, fontSize: 12, padding: "4px 8px" }}
            placeholder="Filter log text (e.g. error, serial, started)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* Auto Scroll Toggle */}
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          <span>Auto-scroll</span>
        </label>
      </div>

      {/* Central Terminal Output Window */}
      <div
        style={{
          flex: 1,
          background: "#080b10",
          fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
          fontSize: 12,
          padding: 14,
          overflowY: "auto",
          lineHeight: 1.6,
        }}
      >
        {filteredLogs.length > 0 ? (
          filteredLogs.map((entry, idx) => {
            const timeStr = new Date(entry.ts * 1000).toLocaleTimeString();
            const levelColor =
              entry.level === "ERROR"
                ? "var(--danger)"
                : entry.level === "WARN"
                ? "var(--warn)"
                : "var(--accent)";

            return (
              <div
                key={idx}
                style={{
                  display: "flex",
                  gap: 12,
                  padding: "2px 0",
                  borderBottom: "1px solid rgba(255,255,255,0.02)",
                }}
              >
                <span className="muted" style={{ userSelect: "none", minWidth: 70 }}>
                  {timeStr}
                </span>
                <span
                  style={{
                    padding: "0 6px",
                    borderRadius: 4,
                    background: "rgba(255,255,255,0.06)",
                    color: "var(--blue)",
                    fontSize: 11,
                    userSelect: "none",
                  }}
                >
                  {entry.node_id}
                </span>
                <span
                  style={{
                    color: levelColor,
                    fontWeight: 600,
                    fontSize: 11,
                    minWidth: 42,
                    userSelect: "none",
                  }}
                >
                  [{entry.level}]
                </span>
                <span style={{ color: "#d0d8e8", wordBreak: "break-all" }}>
                  {entry.line}
                </span>
              </div>
            );
          })
        ) : (
          <div className="placeholder" style={{ textAlign: "center", padding: 40 }}>
            No log entries match the current filter criteria.
          </div>
        )}
        <div ref={consoleEndRef} />
      </div>
    </div>
  );
}
