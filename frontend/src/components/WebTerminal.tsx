import { useCallback, useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";

export type TerminalState = "connecting" | "connected" | "error" | "closed";

export interface WebTerminalProps {
  /** WebSocket URL, e.g. wsUrl("/ws/ssh"). */
  url: string;
  /**
   * Payload merged into the initial `connect` message. Credentials live here and
   * are held in memory only.
   */
  connect?: Record<string, unknown>;
  onState?: (state: TerminalState, message: string) => void;
  /** Bumping this reconnects with a fresh terminal. */
  sessionKey?: string | number;
}

const THEME = {
  background: "#05080c",
  foreground: "#d6dde6",
  cursor: "#3dd68c",
  cursorAccent: "#05080c",
  selectionBackground: "#2a4a63",
  black: "#0b1018",
  red: "#ef4444",
  green: "#3dd68c",
  yellow: "#f59e0b",
  blue: "#5b9cff",
  magenta: "#c084fc",
  cyan: "#22d3ee",
  white: "#d6dde6",
  brightBlack: "#64748b",
  brightRed: "#f87171",
  brightGreen: "#6ee7a8",
  brightYellow: "#fbbf24",
  brightBlue: "#93c5fd",
  brightMagenta: "#d8b4fe",
  brightCyan: "#67e8f9",
  brightWhite: "#f8fafc",
};

/**
 * A real terminal emulator wired to a backend PTY over a WebSocket.
 *
 * xterm.js handles escape sequences, scrollback and selection, so full-screen
 * programs (htop, vim, less) and normal scrolling behave as in a native
 * terminal rather than a line-by-line command box.
 */
export default function WebTerminal({ url, connect, onState, sessionKey }: WebTerminalProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const termRef = useRef<Terminal | null>(null);

  // Keep the latest callback without restarting the session on every render.
  const stateRef = useRef(onState);
  stateRef.current = onState;
  const connectRef = useRef(connect);
  connectRef.current = connect;

  const report = useCallback((state: TerminalState, message = "") => {
    stateRef.current?.(state, message);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const term = new Terminal({
      cursorBlink: true,
      convertEol: false,
      scrollback: 10000,
      fontSize: 13,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      theme: THEME,
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(host);
    termRef.current = term;

    const safeFit = () => {
      try {
        fit.fit();
      } catch {
        /* element not laid out yet */
      }
    };
    safeFit();

    report("connecting", "Opening connection…");
    const socket = new WebSocket(url);
    socketRef.current = socket;

    const send = (payload: Record<string, unknown>) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
    };

    socket.onopen = () => {
      safeFit();
      send({ type: "connect", ...(connectRef.current || {}), cols: term.cols, rows: term.rows });
    };

    socket.onmessage = (event) => {
      let msg: { type?: string; data?: string; state?: string; message?: string };
      try {
        msg = JSON.parse(event.data as string);
      } catch {
        return;
      }
      if (msg.type === "output" && typeof msg.data === "string") {
        term.write(msg.data);
      } else if (msg.type === "status") {
        if (msg.state === "connected") {
          report("connected", msg.message || "");
          safeFit();
          send({ type: "resize", cols: term.cols, rows: term.rows });
        } else if (msg.state === "error") {
          report("error", msg.message || "Connection failed");
          term.write(`\r\n\x1b[31m${(msg.message || "Connection failed").replace(/\n/g, "\r\n")}\x1b[0m\r\n`);
        } else {
          report("connecting", msg.message || "");
        }
      } else if (msg.type === "exit") {
        term.write(`\r\n\x1b[33m${msg.message || "Session closed"}\x1b[0m\r\n`);
        report("closed", msg.message || "Session closed");
      }
    };

    socket.onerror = () => report("error", "WebSocket error — is the backend running?");
    socket.onclose = () => report("closed", "Disconnected");

    const dataSub = term.onData((data) => send({ type: "input", data }));

    // Keep the remote PTY's window size in step with the visible terminal so
    // full-screen programs render at the right dimensions.
    const resizeSub = term.onResize(({ cols, rows }) => send({ type: "resize", cols, rows }));
    const observer = new ResizeObserver(() => safeFit());
    observer.observe(host);

    term.focus();

    return () => {
      observer.disconnect();
      dataSub.dispose();
      resizeSub.dispose();
      if (socket.readyState === WebSocket.OPEN) {
        send({ type: "disconnect" });
      }
      socket.onclose = null;
      socket.close();
      socketRef.current = null;
      term.dispose();
      termRef.current = null;
    };
  }, [url, sessionKey, report]);

  return <div ref={hostRef} style={{ width: "100%", height: "100%", overflow: "hidden" }} />;
}
