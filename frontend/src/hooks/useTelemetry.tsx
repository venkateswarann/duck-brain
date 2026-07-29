import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { wsUrl } from "../config";

export type TelemetrySnapshot = {
  ts: number;
  motors: Record<string, any>;
  nodes: Record<string, string>;
  system: Record<string, any>;
  video: Record<string, any>;
};

const Ctx = createContext<{
  snapshot: TelemetrySnapshot | null;
  connected: boolean;
}>({ snapshot: null, connected: false });

export function TelemetryProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<TelemetrySnapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;

    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/telemetry"));
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
      ws.onmessage = (ev) => {
        try {
          setSnapshot(JSON.parse(ev.data));
        } catch {
          /* ignore */
        }
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, []);

  const value = useMemo(() => ({ snapshot, connected }), [snapshot, connected]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTelemetry() {
  return useContext(Ctx);
}
