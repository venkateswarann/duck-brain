import Editor, { type OnMount } from "@monaco-editor/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiUrl } from "../config";

type TreeNode = {
  type: "dir" | "file";
  name: string;
  path: string;
  children?: TreeNode[];
  size?: number;
  editable?: boolean;
  python?: boolean;
  node_id?: string;
  display_name?: string;
  description?: string;
  resources?: string[];
  registered?: boolean;
  state?: string;
};

type TreeResponse = { root: string; writable: boolean; tree: TreeNode };
type Template = { id: string; label: string; hint: string; resources: string[] };

type Modal =
  | { kind: "new-file"; folder: string }
  | { kind: "new-folder"; folder: string }
  | { kind: "rename"; path: string; isDir: boolean }
  | { kind: "delete"; path: string; isDir: boolean };

const RESOURCES = ["camera0", "serial"];

const LANGUAGES: Record<string, string> = {
  py: "python",
  json: "json",
  md: "markdown",
  yaml: "yaml",
  yml: "yaml",
  sh: "shell",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  csv: "plaintext",
  txt: "plaintext",
};

function encodePath(path: string) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function parentOf(path: string) {
  const index = path.lastIndexOf("/");
  return index === -1 ? "" : path.slice(0, index);
}

function languageFor(path: string) {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return LANGUAGES[ext] ?? "plaintext";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init);
  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    const detail = (data as { detail?: string }).detail;
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return data as T;
}

function collectFiles(node: TreeNode | null, into: Map<string, TreeNode> = new Map()) {
  if (!node) return into;
  if (node.path) into.set(node.path, node);
  node.children?.forEach((child) => collectFiles(child, into));
  return into;
}

export default function ScriptsPage() {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [writable, setWritable] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [activeDir, setActiveDir] = useState("");
  // Last clicked row (file or folder) — what Rename and Delete act on.
  const [focus, setFocus] = useState<{ path: string; isDir: boolean } | null>(null);
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [readOnlyReason, setReadOnlyReason] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [modal, setModal] = useState<Modal | null>(null);
  const [status, setStatus] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [showCopilot, setShowCopilot] = useState(true);

  const nodes = useMemo(() => collectFiles(tree), [tree]);
  const current = selected ? nodes.get(selected) : undefined;
  const saveRef = useRef<() => void>(() => undefined);

  const notify = useCallback((kind: "info" | "error", text: string) => {
    setStatus({ kind, text });
    window.setTimeout(() => setStatus((prev) => (prev?.text === text ? null : prev)), 4000);
  }, []);

  const refreshTree = useCallback(async () => {
    try {
      const data = await api<TreeResponse>("/api/scripts/tree");
      setTree(data.tree);
      setWritable(data.writable);
    } catch (err) {
      notify("error", (err as Error).message);
    }
  }, [notify]);

  useEffect(() => {
    refreshTree();
    api<Template[]>("/api/scripts/templates").then(setTemplates).catch(() => undefined);
    const timer = window.setInterval(refreshTree, 3000);
    return () => window.clearInterval(timer);
  }, [refreshTree]);

  // Open the first top-level script the first time the tree arrives.
  useEffect(() => {
    if (selected || !tree?.children) return;
    const first = tree.children.find((child) => child.type === "file" && child.python);
    if (first) setSelected(first.path);
  }, [tree, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setReadOnlyReason("");
    api<{ content: string }>(`/api/scripts/file/${encodePath(selected)}`)
      .then((data) => {
        if (cancelled) return;
        setContent(data.content);
        setDirty(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setContent("");
        setDirty(false);
        setReadOnlyReason((err as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const nodeId = current?.node_id;
  useEffect(() => {
    if (!nodeId) {
      setLogs([]);
      return;
    }
    const poll = () =>
      api<{ lines: string[] }>(`/api/nodes/${nodeId}/logs`)
        .then((data) => setLogs(data.lines || []))
        .catch(() => undefined);
    poll();
    const timer = window.setInterval(poll, 1000);
    return () => window.clearInterval(timer);
  }, [nodeId]);

  const save = useCallback(async () => {
    if (!selected || !dirty) return;
    try {
      await api(`/api/scripts/file/${encodePath(selected)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      setDirty(false);
      notify("info", `Saved ${selected}`);
    } catch (err) {
      notify("error", (err as Error).message);
    }
  }, [content, dirty, notify, selected]);
  saveRef.current = save;

  const run = async () => {
    if (!selected) return;
    if (dirty) await save();
    try {
      await api(`/api/scripts/run/${encodePath(selected)}`, { method: "POST" });
      notify("info", `Started ${selected}`);
    } catch (err) {
      notify("error", (err as Error).message);
    }
    refreshTree();
  };

  const stop = async () => {
    if (!selected) return;
    try {
      await api(`/api/scripts/stop/${encodePath(selected)}`, { method: "POST" });
      notify("info", `Stopped ${selected}`);
    } catch (err) {
      notify("error", (err as Error).message);
    }
    refreshTree();
  };

  const onEditorMount: OnMount = (editor, monaco) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveRef.current());
  };

  const openFolder = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    setActiveDir(path);
    setFocus({ path, isDir: true });
  };

  const selectFile = (node: TreeNode) => {
    setSelected(node.path);
    setActiveDir(parentOf(node.path));
    setFocus({ path: node.path, isDir: false });
  };

  const afterMutation = async (message: string, nextSelection?: string | null) => {
    if (nextSelection !== undefined) setSelected(nextSelection);
    setModal(null);
    notify("info", message);
    await refreshTree();
  };

  const createFile = async (form: {
    folder: string;
    name: string;
    template: string;
    displayName: string;
    description: string;
    resources: string[];
  }) => {
    try {
      const data = await api<{ path: string }>("/api/scripts/file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder: form.folder,
          name: form.name,
          template: form.template,
          display_name: form.displayName,
          description: form.description,
          resources: form.resources,
        }),
      });
      if (form.folder) setExpanded((prev) => new Set(prev).add(form.folder));
      await afterMutation(`Created ${data.path}`, data.path);
    } catch (err) {
      notify("error", (err as Error).message);
    }
  };

  const createFolder = async (folder: string, name: string) => {
    try {
      const data = await api<{ path: string }>("/api/scripts/folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder, name }),
      });
      setExpanded((prev) => new Set(prev).add(data.path));
      await afterMutation(`Created ${data.path}/`);
    } catch (err) {
      notify("error", (err as Error).message);
    }
  };

  const rename = async (from: string, to: string) => {
    try {
      const data = await api<{ path: string }>("/api/scripts/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from, to }),
      });
      setFocus({ path: data.path, isDir: focus?.isDir ?? false });
      await afterMutation(
        `Renamed to ${data.path}`,
        selected === from ? data.path : selected,
      );
    } catch (err) {
      notify("error", (err as Error).message);
    }
  };

  const remove = async (path: string) => {
    try {
      await api(`/api/scripts/file/${encodePath(path)}`, { method: "DELETE" });
      const clearSelection = selected === path || selected?.startsWith(`${path}/`);
      setFocus(null);
      if (activeDir === path || activeDir.startsWith(`${path}/`)) setActiveDir(parentOf(path));
      await afterMutation(`Deleted ${path}`, clearSelection ? null : selected);
    } catch (err) {
      notify("error", (err as Error).message);
    }
  };

  const renderNode = (node: TreeNode, depth: number) => {
    const indent = { paddingLeft: 10 + depth * 14 };
    if (node.type === "dir") {
      const open = expanded.has(node.path);
      return (
        <div key={node.path}>
          <button
            className={`tree-row ${activeDir === node.path ? "active" : ""}`}
            style={indent}
            onClick={() => openFolder(node.path)}
          >
            <span className="tree-caret">{open ? "▾" : "▸"}</span>
            <span>{open ? "📂" : "📁"}</span>
            <span className="tree-name">{node.name}</span>
          </button>
          {open && node.children?.map((child) => renderNode(child, depth + 1))}
        </div>
      );
    }
    const openable = node.editable !== false;
    return (
      <button
        key={node.path}
        className={`tree-row ${selected === node.path ? "active" : ""} ${openable ? "" : "locked"}`}
        style={indent}
        onClick={() => openable && selectFile(node)}
        title={node.description || node.path}
      >
        <span className="tree-caret" />
        {node.python ? (
          <span className={`status-dot status-${node.state || "stopped"}`} style={{ margin: 0 }} />
        ) : (
          <span style={{ opacity: 0.5 }}>·</span>
        )}
        <span className="tree-name">{node.name}</span>
        {node.state === "running" && <span className="tree-tag">run</span>}
      </button>
    );
  };

  const running = current?.state === "running";

  return (
    <div className="page">
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>Scripts</span>
          <span className="muted" style={{ fontSize: 12 }}>
            robot_scripts/{selected ? ` · ${selected}` : ""}
            {dirty ? " · unsaved" : ""}
          </span>
          {status && (
            <span
              style={{
                fontSize: 12,
                color: status.kind === "error" ? "var(--danger)" : "var(--accent)",
              }}
            >
              {status.text}
            </span>
          )}
        </div>
        <div className="btn-row">
          <button
            className="btn"
            disabled={!writable}
            onClick={() => setModal({ kind: "new-file", folder: activeDir })}
          >
            New Script
          </button>
          <button
            className="btn"
            disabled={!writable}
            onClick={() => setModal({ kind: "new-folder", folder: activeDir })}
          >
            New Folder
          </button>
          <button
            className="btn"
            disabled={!writable || !focus}
            title={focus ? `Rename ${focus.path}` : "Select a file or folder first"}
            onClick={() => focus && setModal({ kind: "rename", ...focus })}
          >
            Rename
          </button>
          <button
            className="btn danger"
            disabled={!writable || !focus}
            title={focus ? `Delete ${focus.path}` : "Select a file or folder first"}
            onClick={() => focus && setModal({ kind: "delete", ...focus })}
          >
            Delete
          </button>
          <button className="btn" onClick={save} disabled={!dirty}>
            Save
          </button>
          <button className="btn primary" onClick={run} disabled={!current?.python}>
            Run
          </button>
          <button className="btn danger" onClick={stop} disabled={!running}>
            Stop
          </button>
          <button
            className={`btn ${showCopilot ? "primary" : ""}`}
            onClick={() => setShowCopilot(!showCopilot)}
            title="Toggle AI Script Copilot Drawer"
          >
            🤖 AI Copilot
          </button>
        </div>
      </div>

      <div className="split" style={{ gridTemplateColumns: showCopilot ? "240px 1fr 380px" : "290px 1fr", flex: 1 }}>
        <div className="panel">
          <div className="tree">
            {tree?.children?.length ? (
              tree.children.map((child) => renderNode(child, 0))
            ) : (
              <div className="placeholder">robot_scripts/ is empty.</div>
            )}
          </div>
        </div>

        <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              gap: 12,
              alignItems: "baseline",
              flexWrap: "wrap",
            }}
          >
            <strong style={{ fontSize: 13 }}>
              {current?.display_name || current?.name || "No file selected"}
            </strong>
            <span className="muted" style={{ fontSize: 12, flex: 1 }}>
              {current?.description || "Select a script on the left, or create a new one."}
            </span>
            {current?.python && (
              <span className="muted" style={{ fontSize: 11 }}>
                {current.node_id} · {current.state}
                {current.resources?.length ? ` · locks ${current.resources.join(", ")}` : ""}
              </span>
            )}
          </div>

          <div style={{ flex: 1, minHeight: 240 }}>
            {readOnlyReason ? (
              <div className="placeholder">{readOnlyReason}</div>
            ) : (
              <Editor
                height="100%"
                theme="vs-dark"
                language={languageFor(selected || "")}
                path={selected || "untitled"}
                value={content}
                onMount={onEditorMount}
                onChange={(value) => {
                  setContent(value ?? "");
                  setDirty(true);
                }}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  readOnly: !writable,
                  scrollBeyondLastLine: false,
                }}
              />
            )}
          </div>

          <div
            className="log-view"
            style={{ height: 170, flex: "none", borderTop: "1px solid var(--border)" }}
          >
            {logs.join("\n") || "(no output yet — press Run)"}
          </div>
        </div>

        {showCopilot && (
          <AiCopilotDrawer
            selectedPath={selected}
            currentContent={content}
            onApplyContent={(newCode) => {
              setContent(newCode);
              setDirty(true);
              notify("info", "Applied AI generated code to editor");
            }}
            onClose={() => setShowCopilot(false)}
          />
        )}
      </div>

      {modal && (
        <ModalHost
          modal={modal}
          templates={templates}
          onClose={() => setModal(null)}
          onCreateFile={createFile}
          onCreateFolder={createFolder}
          onRename={rename}
          onDelete={remove}
        />
      )}
    </div>
  );
}

function ModalHost({
  modal,
  templates,
  onClose,
  onCreateFile,
  onCreateFolder,
  onRename,
  onDelete,
}: {
  modal: Modal;
  templates: Template[];
  onClose: () => void;
  onCreateFile: (form: {
    folder: string;
    name: string;
    template: string;
    displayName: string;
    description: string;
    resources: string[];
  }) => void;
  onCreateFolder: (folder: string, name: string) => void;
  onRename: (from: string, to: string) => void;
  onDelete: (path: string) => void;
}) {
  const [folder, setFolder] = useState(
    modal.kind === "new-file" || modal.kind === "new-folder" ? modal.folder : "",
  );
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("blank");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [resources, setResources] = useState<string[]>([]);
  const [target, setTarget] = useState(modal.kind === "rename" ? modal.path : "");

  const activeTemplate = templates.find((t) => t.id === template);

  useEffect(() => {
    if (activeTemplate) setResources(activeTemplate.resources);
  }, [template]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggleResource = (value: string) =>
    setResources((prev) =>
      prev.includes(value) ? prev.filter((r) => r !== value) : [...prev, value],
    );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        {modal.kind === "new-file" && (
          <>
            <h3>New script</h3>
            <label className="field">
              <span>Folder (blank = robot_scripts root)</span>
              <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="my_scripts" />
            </label>
            <label className="field">
              <span>File name</span>
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="stream_usb_cam.py"
              />
            </label>
            <label className="field">
              <span>Template</span>
              <select value={template} onChange={(e) => setTemplate(e.target.value)}>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
              {activeTemplate && (
                <span style={{ fontSize: 11 }}>{activeTemplate.hint}</span>
              )}
            </label>
            <label className="field">
              <span>Display name (optional)</span>
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </label>
            <label className="field">
              <span>Description (optional)</span>
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <div className="field">
              <span>Exclusive hardware locks</span>
              <div className="chip-row">
                {RESOURCES.map((res) => (
                  <button
                    key={res}
                    type="button"
                    className={`chip ${resources.includes(res) ? "on" : ""}`}
                    onClick={() => toggleResource(res)}
                  >
                    {res}
                  </button>
                ))}
              </div>
            </div>
            <div className="btn-row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button
                className="btn primary"
                disabled={!name.trim()}
                onClick={() =>
                  onCreateFile({
                    folder: folder.trim(),
                    name: name.trim(),
                    template,
                    displayName: displayName.trim(),
                    description: description.trim(),
                    resources,
                  })
                }
              >
                Create
              </button>
            </div>
          </>
        )}

        {modal.kind === "new-folder" && (
          <>
            <h3>New folder</h3>
            <label className="field">
              <span>Parent folder (blank = robot_scripts root)</span>
              <input value={folder} onChange={(e) => setFolder(e.target.value)} />
            </label>
            <label className="field">
              <span>Folder name</span>
              <input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <div className="btn-row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button
                className="btn primary"
                disabled={!name.trim()}
                onClick={() => onCreateFolder(folder.trim(), name.trim())}
              >
                Create
              </button>
            </div>
          </>
        )}

        {modal.kind === "rename" && (
          <>
            <h3>Rename or move</h3>
            <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
              Editing the whole path moves the {modal.isDir ? "folder" : "file"}.
            </p>
            <label className="field">
              <span>Path inside robot_scripts/</span>
              <input autoFocus value={target} onChange={(e) => setTarget(e.target.value)} />
            </label>
            <div className="btn-row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button
                className="btn primary"
                disabled={!target.trim() || target.trim() === modal.path}
                onClick={() => onRename(modal.path, target.trim())}
              >
                Rename
              </button>
            </div>
          </>
        )}

        {modal.kind === "delete" && (
          <>
            <h3>Delete {modal.isDir ? "folder" : "file"}</h3>
            <p style={{ fontSize: 13 }}>
              Delete <code>{modal.path}</code>
              {modal.isDir ? " and everything inside it" : ""}? This cannot be undone.
            </p>
            <div className="btn-row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button className="btn danger" onClick={() => onDelete(modal.path)}>
                Delete
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── AI Copilot Drawer Component ────────────────────────────── */

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
};

function AiCopilotDrawer({
  selectedPath,
  currentContent,
  onApplyContent,
  onClose,
}: {
  selectedPath: string | null;
  currentContent: string;
  onApplyContent: (code: string) => void;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Hello! I am your DCS AI Script Copilot. Ask me to write, explain, or debug Python scripts for Open Duck Mini.",
    },
  ]);
  const [inputPrompt, setInputPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendPrompt = async (customText?: string) => {
    const text = (customText || inputPrompt).trim();
    if (!text || loading) return;

    const newHistory: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(newHistory);
    setInputPrompt("");
    setLoading(true);

    try {
      const res = await fetch(apiUrl("/api/ai/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: text,
          current_script: currentContent,
          script_path: selectedPath,
          history: messages.slice(-6).map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error calling AI endpoint");

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.content || "No response content returned.",
          reasoning: data.reasoning,
        },
      ]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `⚠️ Error: ${err.message || err}. Please verify LLM Agent configuration in Settings.`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const extractCodeBlocks = (text: string): { text: string; codeBlocks: string[] } => {
    const regex = /```(?:python|py)?\n([\s\S]*?)```/g;
    const blocks: string[] = [];
    let match;
    while ((match = regex.exec(text)) !== null) {
      blocks.push(match[1].trim());
    }
    return { text, codeBlocks: blocks };
  };

  return (
    <div className="ai-copilot-drawer">
      {/* Header */}
      <div className="ai-copilot-header">
        <div className="ai-copilot-title">
          <span>🤖 AI Script Copilot</span>
          <span className="calib-status calibrated" style={{ fontSize: 9 }}>
            Active
          </span>
        </div>
        <button
          className="btn"
          style={{ padding: "1px 6px", fontSize: 11 }}
          onClick={onClose}
          title="Close Copilot Drawer"
        >
          ✕
        </button>
      </div>

      {/* Quick Action Chips */}
      <div className="ai-chips-row">
        <button
          className="ai-chip"
          onClick={() => sendPrompt("Explain this script and how it controls the robot.")}
        >
          ⚡ Explain Script
        </button>
        <button
          className="ai-chip"
          onClick={() => sendPrompt("Check this script for bugs, error handling, or performance issues and fix it.")}
        >
          🐛 Debug & Fix
        </button>
        <button
          className="ai-chip"
          onClick={() => sendPrompt("Write a script that moves head_yaw and head_pitch in a smooth wave motion pattern.")}
        >
          🦾 Wave Motion
        </button>
        <button
          className="ai-chip"
          onClick={() => sendPrompt("Write a python script that continuously reads motor voltage, current, and temperature and logs telemetry.")}
        >
          📊 Telemetry Logger
        </button>
      </div>

      {/* Messages Feed */}
      <div className="ai-chat-messages">
        {messages.map((m, idx) => {
          const isUser = m.role === "user";
          const { codeBlocks } = !isUser ? extractCodeBlocks(m.content) : { codeBlocks: [] };

          return (
            <div key={idx} className={`ai-msg ${isUser ? "user" : "assistant"}`}>
              {/* Reasoning / Thinking Box */}
              {m.reasoning && (
                <details className="ai-reasoning-box" open={false}>
                  <summary className="ai-reasoning-summary">
                    🧠 Model Thinking Process ({m.reasoning.length} chars)
                  </summary>
                  <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{m.reasoning}</div>
                </details>
              )}

              {/* Main Content Bubble */}
              <div className="ai-msg-bubble">{m.content}</div>

              {/* Code Actions for Code Blocks */}
              {codeBlocks.map((code, cIdx) => (
                <div key={cIdx} className="ai-code-block">
                  <div className="ai-code-header">
                    <span>Python Code</span>
                    <button
                      className="btn primary"
                      style={{ padding: "2px 8px", fontSize: 10 }}
                      onClick={() => onApplyContent(code)}
                      title="Apply code to active editor script"
                    >
                      📝 Apply to Editor
                    </button>
                  </div>
                  <pre className="ai-code-pre">{code}</pre>
                </div>
              ))}
            </div>
          );
        })}
        {loading && (
          <div className="ai-msg assistant">
            <div className="ai-msg-bubble muted" style={{ fontStyle: "italic" }}>
              ⏳ Generating response & thinking...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Box */}
      <div className="ai-chat-input-box">
        <textarea
          className="ai-chat-textarea"
          placeholder="Ask AI Copilot to write or edit script... (Enter to send)"
          value={inputPrompt}
          onChange={(e) => setInputPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendPrompt();
            }
          }}
        />
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            className="btn primary"
            disabled={!inputPrompt.trim() || loading}
            onClick={() => sendPrompt()}
            style={{ fontSize: 11, padding: "4px 12px" }}
          >
            {loading ? "Thinking..." : "Send Prompt ↵"}
          </button>
        </div>
      </div>
    </div>
  );
}

